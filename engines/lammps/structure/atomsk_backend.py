"""Atomsk CLI structure builders (polycrystal preferred when binary present)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any


def _host_symbol(material: dict[str, Any]) -> str:
    for c in material.get("composition") or []:
        if float(c.get("atomic_percent") or 0) > 0:
            return str(c.get("symbol") or "W")
    return "W"


def _crystal_flag(material: dict[str, Any]) -> str:
    from lammps import crystal as crystal_reg

    cry = crystal_reg.normalize_crystal(str(material.get("crystal") or "bcc"))
    if cry == "hex":
        raise ValueError(
            "Atomsk structure builders do not support crystal=hex (WC) — use ASE WC builders "
            "(void / nanowire / precipitate) or structure_kind=import."
        )
    mapping = {"bcc": "bcc", "fcc": "fcc", "hcp": "hcp", "diamond": "diamond"}
    if cry not in mapping:
        raise ValueError(
            f"Atomsk structure builders do not support crystal='{cry}' — "
            "use bcc/fcc/hcp/diamond (or import a LAMMPS data file)."
        )
    return mapping[cry]


def build_with_atomsk(
    out_data: Path,
    *,
    material: dict[str, Any],
    params: dict[str, Any],
    atomsk_bin: str,
) -> dict[str, Any]:
    kind = str(getattr(params.get("structure_kind"), "value", params.get("structure_kind")) or "").lower()
    if kind not in {"polycrystal", "polycrystal_void", "void", "bicrystal"}:
        raise ValueError(f"Atomsk builder does not support structure_kind={kind}")

    sym = _host_symbol(material)
    cry = _crystal_flag(material)
    a = float(material.get("lattice_constant_A") or 3.165)
    nx = int(params.get("nx") or 8)
    ny = int(params.get("ny") or 8)
    nz = int(params.get("nz") or 8)
    n_grains = max(2, min(int(params.get("poly_n_grains") or 4), 64))
    seed = int(params.get("poly_seed") or 42)
    theta = float(params.get("gb_misorientation_deg") or 15.0)
    gb_normal = str(params.get("gb_normal") or "001").strip().lower()
    merge_axis = "Z"
    if gb_normal in {"100", "1 0 0", "[100]"}:
        merge_axis = "X"
    elif gb_normal in {"010", "0 1 0", "[010]"}:
        merge_axis = "Y"

    work = Path(tempfile.mkdtemp(prefix="aegis_atomsk_"))
    gb_meta: dict[str, Any] = {}
    try:
        crystal_xsf = work / "crystal.xsf"
        poly_lmp = work / "poly.lmp"

        if kind == "bicrystal":
            half = {
                "X": (max(2, nx // 2), ny, nz),
                "Y": (nx, max(2, ny // 2), nz),
                "Z": (nx, ny, max(2, nz // 2)),
            }[merge_axis]
            g1 = work / "grain1.xsf"
            g2 = work / "grain2.xsf"
            bi = work / "bicrystal.lmp"
            _run(
                [
                    atomsk_bin,
                    "--create",
                    cry,
                    str(a),
                    sym,
                    str(g1),
                    "-duplicate",
                    str(half[0]),
                    str(half[1]),
                    str(half[2]),
                ],
                work,
            )
            # Second grain: copy then rotate about merge axis by misorientation
            shutil.copy2(g1, g2)
            try:
                _run(
                    [atomsk_bin, str(g2), "-rotate", merge_axis, f"{theta:.6f}", str(g2)],
                    work,
                )
            except RuntimeError:
                _run(
                    [
                        atomsk_bin,
                        str(g1),
                        "-rotate",
                        merge_axis,
                        f"{theta:.6f}",
                        str(g2),
                    ],
                    work,
                )
            try:
                _run(
                    [
                        atomsk_bin,
                        "--merge",
                        merge_axis,
                        "2",
                        str(g1),
                        str(g2),
                        str(bi),
                        "lmp",
                    ],
                    work,
                )
            except RuntimeError:
                # Alternate merge syntax
                _run(
                    [
                        atomsk_bin,
                        "--merge",
                        "2",
                        str(g1),
                        str(g2),
                        merge_axis,
                        str(bi),
                        "lmp",
                    ],
                    work,
                )
            src = bi if bi.exists() else poly_lmp
            gb_meta = {
                "method": "atomsk-merge-bicrystal",
                "misorientation_deg": theta,
                "merge_axis": merge_axis,
                "gb_normal": gb_normal,
                "n_grains": 2,
            }
            n_grains = 2
        else:
            cmd_create = [
                atomsk_bin,
                "--create",
                cry,
                str(a),
                sym,
                str(crystal_xsf),
                "-duplicate",
                str(nx),
                str(ny),
                str(nz),
            ]
            _run(cmd_create, work)
            if kind in {"polycrystal", "polycrystal_void"}:
                cmd_poly = [
                    atomsk_bin,
                    str(crystal_xsf),
                    "-polycrystal",
                    str(n_grains),
                    "random",
                    str(seed),
                    str(poly_lmp),
                    "lmp",
                ]
                try:
                    _run(cmd_poly, work)
                except RuntimeError:
                    cmd_poly = [
                        atomsk_bin,
                        "--polycrystal",
                        f"{cry} {a} {sym}",
                        f"{n_grains} random",
                        str(poly_lmp),
                        "lmp",
                    ]
                    _run(cmd_poly, work)
                src = poly_lmp
            else:
                cmd_lmp = [atomsk_bin, str(crystal_xsf), str(poly_lmp), "lmp"]
                _run(cmd_lmp, work)
                src = poly_lmp

        if not src.exists():
            cands = list(work.glob("*.lmp")) + list(work.glob("*.data"))
            if not cands:
                raise RuntimeError("Atomsk did not produce a LAMMPS data file")
            src = cands[0]

        out_data.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out_data)

        removed = 0
        artificial_void = False
        if kind in {"void", "polycrystal_void"}:
            from ase.io import read, write

            atoms = read(str(out_data), format="lammps-data")
            from lammps.structure.ase_backend import _punch_voids

            removed = _punch_voids(atoms, params, __import__("random").Random(seed))
            artificial_void = True
            write(str(out_data), atoms, format="lammps-data", atom_style="atomic", masses=True)

        n = _count_atoms(out_data)
        box_A = None
        try:
            from ase.io import read as ase_read

            atoms_box = ase_read(str(out_data), format="lammps-data")
            cell = atoms_box.get_cell()
            box_A = [float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])]
        except Exception:  # noqa: BLE001
            box_A = None
        meta_out: dict[str, Any] = {
            "atom_count": n,
            "host_symbol": sym,
            "n_grains": n_grains if ("poly" in kind or kind == "bicrystal") else 1,
            "artificial_void": artificial_void,
            "void_atoms_removed": removed,
            "gb": gb_meta,
            "note": "Built with Atomsk",
        }
        if box_A:
            meta_out["box_A"] = box_A
        return meta_out
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _run(cmd: list[str], cwd: Path) -> None:
    proc = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise RuntimeError(
            f"Atomsk failed ({proc.returncode}): {(proc.stderr or proc.stdout or '')[-800:]}"
        )


def _count_atoms(path: Path) -> int:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        if "atoms" in line.lower() and line.strip()[:1].isdigit():
            try:
                return int(line.split()[0])
            except ValueError:
                continue
    return 0
