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
    return {"bcc": "bcc", "fcc": "fcc", "hcp": "hcp", "diamond": "diamond", "hex": "hcp"}.get(cry, "bcc")


def build_with_atomsk(
    out_data: Path,
    *,
    material: dict[str, Any],
    params: dict[str, Any],
    atomsk_bin: str,
) -> dict[str, Any]:
    kind = str(getattr(params.get("structure_kind"), "value", params.get("structure_kind")) or "").lower()
    if kind not in {"polycrystal", "polycrystal_void", "void"}:
        raise ValueError(f"Atomsk builder does not support structure_kind={kind}")

    sym = _host_symbol(material)
    cry = _crystal_flag(material)
    a = float(material.get("lattice_constant_A") or 3.165)
    nx = int(params.get("nx") or 8)
    ny = int(params.get("ny") or 8)
    nz = int(params.get("nz") or 8)
    n_grains = max(2, min(int(params.get("poly_n_grains") or 4), 64))
    seed = int(params.get("poly_seed") or 42)

    work = Path(tempfile.mkdtemp(prefix="aegis_atomsk_"))
    try:
        # Create oriented crystal then polycrystalize
        crystal_xsf = work / "crystal.xsf"
        poly_lmp = work / "poly.lmp"
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
            # Atomsk polycrystal syntax varies; try documented form then fallback
            try:
                _run(cmd_poly, work)
            except RuntimeError:
                # Fallback: --polycrystal N box
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
            # Single crystal to lmp
            cmd_lmp = [atomsk_bin, str(crystal_xsf), str(poly_lmp), "lmp"]
            _run(cmd_lmp, work)
            src = poly_lmp

        if not src.exists():
            # Atomsk may write .lmp with different name
            cands = list(work.glob("*.lmp")) + list(work.glob("*.data"))
            if not cands:
                raise RuntimeError("Atomsk did not produce a LAMMPS data file")
            src = cands[0]

        out_data.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, out_data)

        removed = 0
        artificial_void = False
        if kind in {"void", "polycrystal_void"}:
            # Punch void with ASE on the Atomsk result
            from ase.io import read, write

            atoms = read(str(out_data), format="lammps-data")
            from lammps.structure.ase_backend import _punch_voids

            removed = _punch_voids(atoms, params, __import__("random").Random(seed))
            artificial_void = True
            write(str(out_data), atoms, format="lammps-data", atom_style="atomic", masses=True)

        n = _count_atoms(out_data)
        return {
            "atom_count": n,
            "host_symbol": sym,
            "n_grains": n_grains if "poly" in kind else 1,
            "artificial_void": artificial_void,
            "void_atoms_removed": removed,
            "note": "Built with Atomsk",
        }
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
