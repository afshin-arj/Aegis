"""Orchestrate structure builders and write structure.data + structure_meta.json."""

from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any


def structure_kind_value(params: dict[str, Any]) -> str:
    raw = params.get("structure_kind") or "single_crystal"
    return str(getattr(raw, "value", raw) or "single_crystal").strip().lower()


def needs_structure_file(params: dict[str, Any]) -> bool:
    return structure_kind_value(params) not in {"", "single_crystal"}


def resolve_atomsk_bin() -> str | None:
    env = (os.environ.get("AEGIS_ATOMSK_BIN") or "").strip()
    if env and Path(env).exists():
        return env
    which = shutil.which("atomsk") or shutil.which("atomsk.exe")
    if which:
        return which
    # Repo-local bootstrap install
    here = Path(__file__).resolve()
    root = here.parents[3]  # engines/lammps/structure → repo
    for cand in (
        root / "third_party" / "atomsk" / "atomsk.exe",
        root / "third_party" / "atomsk" / "atomsk",
    ):
        if cand.exists():
            return str(cand)
    return None


def build_structure(
    job_dir: Path,
    *,
    material: dict[str, Any],
    params: dict[str, Any],
    import_source: Path | None = None,
) -> dict[str, Any]:
    """Build structure.data in job_dir. Raises ValueError on failure."""
    kind = structure_kind_value(params)
    job_dir = Path(job_dir)
    job_dir.mkdir(parents=True, exist_ok=True)
    out_data = job_dir / "structure.data"

    if kind == "single_crystal":
        raise ValueError("single_crystal does not use structure.data — use lattice create_atoms")

    if kind == "import":
        from lammps.structure.import_backend import import_structure

        src = import_source
        if src is None:
            rel = params.get("structure_import_path")
            if not rel:
                raise ValueError("structure_kind=import requires structure_import_path or upload")
            src = Path(str(rel))
            if not src.is_absolute():
                src = job_dir / src
        meta = import_structure(src, out_data)
        meta["kind"] = kind
        (job_dir / "structure_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
        return meta

    atomsk = resolve_atomsk_bin()
    use_atomsk = bool(atomsk) and kind in {"polycrystal", "polycrystal_void", "bicrystal"}

    if use_atomsk:
        try:
            from lammps.structure.atomsk_backend import build_with_atomsk

            meta = build_with_atomsk(out_data, material=material, params=params, atomsk_bin=atomsk)
            meta["kind"] = kind
            meta["backend"] = "atomsk"
            (job_dir / "structure_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return meta
        except Exception as exc:  # noqa: BLE001
            # Fall through to ASE with note
            atomsk_err = str(exc)
    else:
        atomsk_err = None

    try:
        from lammps.structure.ase_backend import build_with_ase
    except ImportError as exc:
        raise ValueError(
            "ASE is required to build nanostructures. Re-run setup_and_run.cmd "
            "(pip install ase) or see docs/structures.md."
        ) from exc

    meta = build_with_ase(out_data, material=material, params=params)
    meta["kind"] = kind
    meta["backend"] = "ase"
    if atomsk_err:
        meta["atomsk_fallback_reason"] = atomsk_err
    (job_dir / "structure_meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    if not out_data.exists():
        raise ValueError("structure builder did not write structure.data")
    return meta
