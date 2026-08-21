"""Import external LAMMPS data / dump into structure.data."""

from __future__ import annotations

import re
import shutil
from pathlib import Path
from typing import Any


def _norm_sym(sym: str) -> str:
    s = str(sym or "").strip()
    if not s:
        return ""
    if len(s) == 1:
        return s.upper()
    return s[0].upper() + s[1:].lower()


def _box_A_from_data(path: Path) -> list[float] | None:
    xlo = xhi = ylo = yhi = zlo = zhi = None
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    for line in text.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[2] == "xlo" and parts[3] == "xhi":
            xlo, xhi = float(parts[0]), float(parts[1])
        elif len(parts) >= 4 and parts[2] == "ylo" and parts[3] == "yhi":
            ylo, yhi = float(parts[0]), float(parts[1])
        elif len(parts) >= 4 and parts[2] == "zlo" and parts[3] == "zhi":
            zlo, zhi = float(parts[0]), float(parts[1])
        if xlo is not None and ylo is not None and zlo is not None:
            break
    if None in (xlo, xhi, ylo, yhi, zlo, zhi):
        return None
    return [float(xhi) - float(xlo), float(yhi) - float(ylo), float(zhi) - float(zlo)]


def import_structure(src: Path, out_data: Path) -> dict[str, Any]:
    src = Path(src)
    if not src.exists():
        raise ValueError(f"import structure not found: {src}")
    out_data.parent.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower()
    if suffix in {".data", ".lmp", ""} or "data" in src.name.lower():
        shutil.copy2(src, out_data)
        n_guess = _count_atoms_data(out_data)
        type_symbols = _type_symbols_from_file(out_data)
        meta: dict[str, Any] = {
            "backend": "import",
            "source": str(src),
            "atom_count": n_guess,
            "note": "Imported LAMMPS data file",
        }
        box = _box_A_from_data(out_data)
        if box:
            meta["box_A"] = box
        if type_symbols:
            meta["type_symbols"] = type_symbols
            meta["n_atom_types"] = len(type_symbols)
            meta["type_symbols_resolved"] = True
        else:
            n_types = _count_atom_types(out_data)
            if n_types:
                meta["n_atom_types"] = n_types
                meta["type_symbols_resolved"] = False
                meta["note"] = (
                    "Imported LAMMPS data file (no element symbols in file). "
                    "Host composition must declare exactly the same number of species as atom types, "
                    "in type order; otherwise the import is rejected."
                )
            else:
                meta["type_symbols_resolved"] = False
        return meta
    # Try ASE for dumps / xyz / cfg
    try:
        from ase.io import read, write

        atoms = read(str(src))
        type_symbols = _ordered_symbols(atoms.get_chemical_symbols())
        write(
            str(out_data),
            atoms,
            format="lammps-data",
            atom_style="atomic",
            masses=True,
            specorder=type_symbols or None,
        )
        cell = atoms.get_cell()
        return {
            "backend": "import",
            "source": str(src),
            "atom_count": len(atoms),
            "type_symbols": type_symbols,
            "n_atom_types": len(type_symbols) if type_symbols else None,
            "type_symbols_resolved": bool(type_symbols),
            "box_A": [float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])],
            "note": f"Imported via ASE from {src.name}",
        }
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"could not import structure from {src}: {exc}") from exc


def _ordered_symbols(symbols: list[str]) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for raw in symbols:
        s = _norm_sym(raw)
        if not s or s.lower() in seen:
            continue
        seen.add(s.lower())
        out.append(s)
    return out


def _type_symbols_from_file(path: Path) -> list[str] | None:
    """Best-effort element order from an imported data file via ASE."""
    try:
        from ase.io import read

        atoms = read(str(path), format="lammps-data")
        syms = _ordered_symbols(atoms.get_chemical_symbols())
        return syms or None
    except Exception:  # noqa: BLE001
        return None


def _count_atoms_data(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "atoms" in line.lower() and line.strip()[0:1].isdigit():
            try:
                return int(line.split()[0])
            except ValueError:
                continue
    return 0


def _count_atom_types(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        m = re.match(r"^\s*(\d+)\s+atom\s+types\s*$", line, re.I)
        if m:
            return int(m.group(1))
    return 0
