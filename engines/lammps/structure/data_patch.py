"""Patch LAMMPS data files (extra atom types for implant/surface ions)."""

from __future__ import annotations

import re
from pathlib import Path


def ensure_atom_types(path: Path, n_types: int, type_masses: dict[int, float]) -> None:
    """Ensure data file declares at least n_types and lists masses for each."""
    path = Path(path)
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines(keepends=True)
    out: list[str] = []
    current_types = 1
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r"^(\s*)(\d+)\s+atom\s+types\s*$", line, re.I)
        if m:
            current_types = int(m.group(2))
            n_types = max(n_types, current_types)
            out.append(f"{m.group(1)}{n_types} atom types\n")
            i += 1
            continue
        if re.match(r"^Masses\b", line, re.I):
            out.append(line if line.endswith("\n") else line + "\n")
            i += 1
            if i < len(lines) and lines[i].strip() == "":
                out.append(lines[i])
                i += 1
            seen: dict[int, str] = {}
            while i < len(lines):
                raw = lines[i]
                if raw.strip() == "":
                    break
                if re.match(r"^\s*\d+\s+\S+", raw):
                    tid = int(raw.split()[0])
                    seen[tid] = raw if raw.endswith("\n") else raw + "\n"
                    i += 1
                    continue
                break
            for tid in range(1, n_types + 1):
                if tid in seen:
                    out.append(seen[tid])
                elif tid in type_masses:
                    out.append(f"{tid} {type_masses[tid]:.6f}\n")
                else:
                    raise ValueError(
                        f"structure.data missing mass for atom type {tid} "
                        f"(need masses for types 1..{n_types})"
                    )
            continue
        out.append(line if line.endswith("\n") else line + "\n")
        i += 1
    path.write_text("".join(out), encoding="utf-8")
