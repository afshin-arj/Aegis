"""Lattice constant relax / DFT export-import helpers."""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


def discover_ase() -> dict[str, Any]:
    try:
        import ase  # type: ignore  # noqa: F401

        return {"ase_found": True, "ase_message": f"ASE {getattr(ase, '__version__', '')} — nanostructures + optional DFT relax"}
    except Exception:  # noqa: BLE001
        return {
            "ase_found": False,
            "ase_message": "ASE not installed — required for nanostructure builders (pip install ase / setup_and_run.cmd)",
        }


def discover_atomsk() -> dict[str, Any]:
    import os

    env = (os.environ.get("AEGIS_ATOMSK_BIN") or "").strip()
    if env and Path(env).exists():
        return {"atomsk_found": True, "atomsk_path": env}
    path = shutil.which("atomsk") or shutil.which("atomsk.exe")
    if path:
        return {"atomsk_found": True, "atomsk_path": path}
    # Repo-local bootstrap install + common Windows installer paths
    root = Path(__file__).resolve().parents[3]
    candidates = [
        root / "third_party" / "atomsk" / "atomsk.exe",
        root / "third_party" / "atomsk" / "atomsk",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Atomsk" / "atomsk.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Atomsk" / "atomsk.exe",
    ]
    for cand in candidates:
        if cand.exists():
            return {"atomsk_found": True, "atomsk_path": str(cand)}
    local = root / "third_party" / "atomsk"
    if local.is_dir():
        for hit in local.rglob("atomsk.exe"):
            return {"atomsk_found": True, "atomsk_path": str(hit)}
        for hit in local.rglob("atomsk"):
            if hit.is_file():
                return {"atomsk_found": True, "atomsk_path": str(hit)}
    return {
        "atomsk_found": False,
        "atomsk_path": None,
        "atomsk_message": (
            "Optional — ASE Voronoi builds polycrystal without Atomsk. "
            "Install from https://github.com/pierrehirel/atomsk or set AEGIS_ATOMSK_BIN."
        ),
    }


def export_poscar(material: dict[str, Any], *, nx: int = 1, ny: int = 1, nz: int = 1) -> str:
    """Minimal conventional-cell POSCAR for DFT export.

    Alloys and WC hex are refused — a silent single-host POSCAR would mislead experts.
    """
    from lammps import crystal as crystal_reg

    cry = crystal_reg.normalize_crystal(material.get("crystal"))
    elems = [
        e["symbol"]
        for e in material.get("composition") or []
        if float(e.get("atomic_percent") or 0) > 0
    ]
    if cry == "hex" or len(elems) > 1:
        raise ValueError(
            "POSCAR export supports single-host bcc/fcc/hcp/diamond only. "
            "Alloys and WC (hex) need a multi-species DFT cell — export via ASE/Atomsk "
            "or structure_kind=import, not this single-host POSCAR helper."
        )
    a = float(material.get("lattice_constant_A", 3.165))
    c = crystal_reg.resolve_c_A(material, cry)
    host = elems[0] if elems else "X"
    offsets = crystal_reg.basis_offsets(cry)
    # Scale box
    if cry in {"hcp", "hex"} and c:
        # Orthorhombic-ish export
        scale_a, scale_b, scale_c = a * nx, a * (3**0.5 / 2.0) * ny, c * nz
        coords = []
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    for ox, oy, oz in offsets:
                        coords.append(
                            (
                                (i + ox) / nx,
                                (j + oy) / ny,
                                (k + oz) / nz,
                            )
                        )
    else:
        # Cubic / diamond: honor nx, ny, nz independently
        nx = max(int(nx), 1)
        ny = max(int(ny), 1)
        nz = max(int(nz), 1)
        scale_a, scale_b, scale_c = a * nx, a * ny, a * nz
        coords = []
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    for ox, oy, oz in offsets:
                        coords.append(
                            (
                                (i + ox) / nx,
                                (j + oy) / ny,
                                (k + oz) / nz,
                            )
                        )

    lines = [
        f"Aegis {host} {cry}",
        "1.0",
        f"{scale_a:.8f} 0.0 0.0",
        f"0.0 {scale_b:.8f} 0.0",
        f"0.0 0.0 {scale_c:.8f}",
        host,
        str(len(coords)),
        "Direct",
    ]
    for x, y, z in coords:
        lines.append(f"{x:.8f} {y:.8f} {z:.8f}")
    return "\n".join(lines) + "\n"


def try_ase_relax(material: dict[str, Any]) -> dict[str, Any]:
    """Best-effort ASE EMT box relax for compatible elements; else return export hint."""
    ase_info = discover_ase()
    if not ase_info["ase_found"]:
        return {
            "status": "unavailable",
            "message": ase_info["ase_message"],
            "poscar": export_poscar(material),
        }
    try:
        from ase.build import bulk  # type: ignore
        from ase.calculators.emt import EMT  # type: ignore
        from ase.constraints import ExpCellFilter  # type: ignore
        from ase.optimize import BFGS  # type: ignore

        elems = [e["symbol"] for e in material.get("composition") or [] if e.get("atomic_percent", 0) > 0]
        host = elems[0] if elems else "Cu"
        cry = str(material.get("crystal", "fcc")).lower()
        a0 = float(material.get("lattice_constant_A", 3.6))
        if len(elems) > 1 or cry in {"hex", "diamond"}:
            return {
                "status": "unsupported",
                "message": (
                    "ASE EMT relax supports single-host bcc/fcc/hcp only. "
                    "Alloys / WC / diamond need DFT — POSCAR export is refused for multi-species."
                ),
                "poscar": None,
                "note": "Build a DFT cell externally or use structure_kind=import.",
            }
        # EMT supports limited crystals; never silently map diamond/hex → fcc
        if cry not in {"bcc", "fcc", "hcp"}:
            try:
                poscar = export_poscar(material)
            except ValueError as exc:
                return {
                    "status": "unsupported",
                    "message": str(exc),
                    "poscar": None,
                }
            return {
                "status": "unsupported",
                "message": f"ASE EMT relax does not support crystal '{cry}'. Export POSCAR for DFT.",
                "poscar": poscar,
                "note": "Use exported POSCAR with your DFT code, then import a/c.",
            }
        crystalname = cry
        atoms = bulk(host, crystalname, a=a0, cubic=True)
        atoms.calc = EMT()
        ucf = ExpCellFilter(atoms)
        BFGS(ucf, logfile=None).run(fmax=0.05)
        cell = atoms.cell.lengths()
        return {
            "status": "ok",
            "method": "ase-emt",
            "lattice_constant_A": float(cell[0]),
            "lattice_c_A": float(cell[2]) if cry in {"hcp", "hex"} else None,
            "note": "EMT relax — teaching estimate only, not production DFT.",
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "status": "failed",
            "message": str(exc),
            "poscar": export_poscar(material),
            "note": "Use exported POSCAR with your DFT code, then import a/c.",
        }


def parse_lattice_from_poscar(text: str) -> dict[str, float]:
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 5:
        raise ValueError("POSCAR too short")
    scale = float(lines[1].split()[0])
    a1 = [float(x) for x in lines[2].split()[:3]]
    a3 = [float(x) for x in lines[4].split()[:3]]
    import math

    a = scale * math.sqrt(a1[0] ** 2 + a1[1] ** 2 + a1[2] ** 2)
    c = scale * math.sqrt(a3[0] ** 2 + a3[1] ** 2 + a3[2] ** 2)
    return {"lattice_constant_A": a, "lattice_c_A": c}


def write_structure_json(path: Path, material: dict[str, Any], lattice: dict[str, Any]) -> None:
    payload = {**material, **lattice, "source": "aegis-lattice-relax"}
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
