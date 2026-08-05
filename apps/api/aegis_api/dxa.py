"""Optional OVITO DXA post-analysis for Aegis jobs."""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any


def discover_ovito() -> dict[str, Any]:
    ovitos = shutil.which("ovitos") or shutil.which("ovito")
    mod_ok = False
    try:
        import ovito  # type: ignore  # noqa: F401

        mod_ok = True
    except Exception:  # noqa: BLE001
        mod_ok = False
    return {
        "ovito_found": bool(ovitos) or mod_ok,
        "ovito_path": ovitos,
        "ovito_message": (
            "OVITO Python / ovitos available"
            if (ovitos or mod_ok)
            else "OVITO not found — install OVITO and ensure ovitos is on PATH for DXA"
        ),
    }


def run_dxa_on_job(job_dir: Path) -> dict[str, Any]:
    """Run DXA if OVITO is available; otherwise write an honest stub summary."""
    info = discover_ovito()
    out_path = job_dir / "dxa_summary.json"
    dumps = sorted(job_dir.glob("dump.cascade*.lammpstrj")) + sorted(
        job_dir.glob("dump.*.lammpstrj")
    )
    dumps = [d for d in dumps if "initial" not in d.name and "stage" not in d.name]
    target = dumps[-1] if dumps else None

    if not info["ovito_found"] or target is None:
        summary = {
            "status": "unavailable",
            "ovito_found": info["ovito_found"],
            "message": info["ovito_message"]
            if info["ovito_found"]
            else "OVITO not installed — DXA skipped",
            "dump": target.name if target else None,
            "crystal_type_fractions": {},
            "dislocation_length_A": None,
            "note": "Aegis never fabricates DXA networks. Install OVITO to enable.",
        }
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    script = job_dir / "_aegis_dxa.py"
    script.write_text(
        f"""
from ovito.io import import_file
from ovito.modifiers import DislocationAnalysisModifier
import json
pipeline = import_file(r"{target.as_posix()}")
pipeline.modifiers.append(DislocationAnalysisModifier())
data = pipeline.compute()
fracs = {{}}
try:
    fracs = dict(data.attributes)
except Exception:
    fracs = {{}}
length = None
try:
    length = float(data.attributes.get("DislocationAnalysis.total_line_length", 0))
except Exception:
    pass
summary = {{
    "status": "ok",
    "dump": r"{target.name}",
    "crystal_type_fractions": fracs,
    "dislocation_length_A": length,
    "note": "OVITO DXA — complementary to Aegis WS proxy",
}}
open(r"{out_path.as_posix()}", "w", encoding="utf-8").write(json.dumps(summary, indent=2))
print("Aegis DXA written")
""",
        encoding="utf-8",
    )
    ovitos = info.get("ovito_path") or "ovitos"
    try:
        proc = subprocess.run(
            [ovitos, str(script)],
            cwd=job_dir,
            capture_output=True,
            text=True,
            timeout=300,
            check=False,
        )
        if out_path.exists():
            return json.loads(out_path.read_text(encoding="utf-8"))
        return {
            "status": "failed",
            "message": (proc.stderr or proc.stdout or "DXA script failed")[:500],
            "ovito_found": True,
        }
    except Exception as exc:  # noqa: BLE001
        summary = {"status": "failed", "message": str(exc), "ovito_found": True}
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


def load_dxa_summary(job_dir: Path) -> dict[str, Any] | None:
    path = job_dir / "dxa_summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
