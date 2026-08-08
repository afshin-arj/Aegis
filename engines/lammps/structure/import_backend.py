"""Import external LAMMPS data / dump into structure.data."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def import_structure(src: Path, out_data: Path) -> dict[str, Any]:
    src = Path(src)
    if not src.exists():
        raise ValueError(f"import structure not found: {src}")
    out_data.parent.mkdir(parents=True, exist_ok=True)
    suffix = src.suffix.lower()
    if suffix in {".data", ".lmp", ""} or "data" in src.name.lower():
        shutil.copy2(src, out_data)
        n_guess = _count_atoms_data(out_data)
        return {
            "backend": "import",
            "source": str(src),
            "atom_count": n_guess,
            "note": "Imported LAMMPS data file",
        }
    # Try ASE for dumps / xyz / cfg
    try:
        from ase.io import read, write

        atoms = read(str(src))
        write(str(out_data), atoms, format="lammps-data", atom_style="atomic", masses=True)
        return {
            "backend": "import",
            "source": str(src),
            "atom_count": len(atoms),
            "note": f"Imported via ASE from {src.name}",
        }
    except Exception as exc:  # noqa: BLE001
        raise ValueError(f"could not import structure from {src}: {exc}") from exc


def _count_atoms_data(path: Path) -> int:
    text = path.read_text(encoding="utf-8", errors="replace")
    for line in text.splitlines():
        if "atoms" in line.lower() and line.strip()[0:1].isdigit():
            try:
                return int(line.split()[0])
            except ValueError:
                continue
    return 0
