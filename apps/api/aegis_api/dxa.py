"""Optional OVITO DXA post-analysis for Aegis jobs.

User-friendly paths (any one is enough):
  1. ``pip install -U ovito`` into the Aegis API / .venv interpreter (preferred)
  2. OVITO Pro ``ovitos`` on PATH
  3. ``AEGIS_OVITO_BIN`` pointing at ``ovitos.exe`` / ``ovitos``

See https://docs.ovito.org/python/introduction/installation.html
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


# Map Aegis crystal ids → OVITO DislocationAnalysisModifier.Lattice names
_CRYSTAL_TO_OVITO = {
    "bcc": "BCC",
    "fcc": "FCC",
    "hcp": "HCP",
    "diamond": "CubicDiamond",
    # WC-like hex: closest built-in DXA lattice (approximate)
    "hex": "HCP",
}


def _resolve_ovitos_bin() -> str | None:
    env = (os.environ.get("AEGIS_OVITO_BIN") or "").strip()
    if env:
        p = Path(env)
        if p.exists():
            return str(p)
        found = shutil.which(env)
        if found:
            return found
    return shutil.which("ovitos") or shutil.which("ovito")


def _try_import_ovito() -> tuple[bool, str | None, Any]:
    """Return (ok, version_str, module_or_None).

    Ignores a local ``engines/ovito`` path shadow (namespace without the real API).
    """
    try:
        import ovito  # type: ignore

        # Real package exposes io / modifiers; a shadowed folder does not
        if not hasattr(ovito, "io") and not hasattr(ovito, "version"):
            # Namespace package from engines/ on PYTHONPATH — not usable
            return False, None, None
        ver = getattr(ovito, "version", None)
        if isinstance(ver, (tuple, list)) and len(ver) >= 3:
            ver_s = f"{ver[0]}.{ver[1]}.{ver[2]}"
        elif ver is not None:
            ver_s = str(ver)
        else:
            ver_s = str(getattr(ovito, "__version__", "unknown"))
        # Confirm DXA imports resolve
        from ovito.io import import_file  # noqa: F401
        from ovito.modifiers import DislocationAnalysisModifier  # noqa: F401

        return True, ver_s, ovito
    except Exception:  # noqa: BLE001
        return False, None, None


def discover_ovito() -> dict[str, Any]:
    """Probe local OVITO for Engines status and DXA readiness."""
    ovitos = _resolve_ovitos_bin()
    mod_ok, ver, _ = _try_import_ovito()
    found = bool(ovitos) or mod_ok
    if mod_ok and ovitos:
        mode = "module+ovitos"
        msg = (
            f"OVITO Python module {ver} + ovitos at {ovitos}. "
            "DXA uses the module in-process when possible."
        )
    elif mod_ok:
        mode = "module"
        msg = (
            f"OVITO Python module {ver} (pip). "
            "DXA runs in-process — no separate ovitos needed."
        )
    elif ovitos:
        mode = "ovitos"
        msg = (
            f"OVITO ovitos at {ovitos}. "
            "DXA runs via subprocess (or pip install -U ovito into the Aegis venv)."
        )
    else:
        mode = "missing"
        msg = (
            "OVITO not found. Easiest: in the Aegis venv run "
            "`pip install -U ovito` (see https://docs.ovito.org/python/). "
            "Or install OVITO Pro and set AEGIS_OVITO_BIN to ovitos.exe."
        )
    return {
        "ovito_found": found,
        "ovito_path": ovitos,
        "ovito_mode": mode,
        "ovito_version": ver,
        "ovito_message": msg,
        "install_hint": "pip install -U ovito",
        "docs_url": "https://docs.ovito.org/python/",
    }


def _crystal_from_job(job_dir: Path) -> str:
    mat_path = job_dir / "material.json"
    if mat_path.exists():
        try:
            mat = json.loads(mat_path.read_text(encoding="utf-8"))
            cry = str(mat.get("crystal") or "bcc")
            from lammps import crystal as crystal_reg

            return crystal_reg.normalize_crystal(cry)
        except Exception:  # noqa: BLE001
            pass
    return "bcc"


def _pick_dump(job_dir: Path) -> Path | None:
    """Prefer residual cascade dumps; fall back to any non-initial trajectory."""
    preferred: list[Path] = []
    for pattern in (
        "dump.cascade*.lammpstrj",
        "dump.implant*.lammpstrj",
        "dump.surface*.lammpstrj",
        "dump.interstitial*.lammpstrj",
        "dump.*.lammpstrj",
    ):
        preferred.extend(sorted(job_dir.glob(pattern)))
    dumps = [d for d in preferred if "initial" not in d.name and "stage" not in d.name]
    # de-dupe preserving order
    seen: set[str] = set()
    uniq: list[Path] = []
    for d in dumps:
        key = d.resolve().as_posix()
        if key in seen:
            continue
        seen.add(key)
        uniq.append(d)
    return uniq[-1] if uniq else None


def _ovito_lattice_name(crystal: str) -> str:
    return _CRYSTAL_TO_OVITO.get(crystal, "BCC")


def _summarize_dxa_data(data: Any, *, dump_name: str, crystal: str, lattice: str, how: str) -> dict[str, Any]:
    attrs = dict(getattr(data, "attributes", {}) or {})
    length = attrs.get("DislocationAnalysis.total_line_length")
    volume = attrs.get("DislocationAnalysis.cell_volume")
    try:
        length_f = float(length) if length is not None else None
    except (TypeError, ValueError):
        length_f = None
    try:
        volume_f = float(volume) if volume is not None else None
    except (TypeError, ValueError):
        volume_f = None
    density = None
    if length_f is not None and volume_f and volume_f > 0:
        density = length_f / volume_f

    # Crystal structure type counts from DXA (when present)
    type_fracs: dict[str, float] = {}
    for key, val in attrs.items():
        if "CrystalAnalysis" in key or "StructureType" in key or key.startswith("DislocationAnalysis.count"):
            try:
                type_fracs[key] = float(val)
            except (TypeError, ValueError):
                type_fracs[key] = val  # type: ignore[assignment]

    n_segments = None
    try:
        network = getattr(data, "dislocations", None)
        if network is not None and hasattr(network, "lines"):
            n_segments = len(network.lines)
        elif network is not None and hasattr(network, "segments"):
            n_segments = len(network.segments)
    except Exception:  # noqa: BLE001
        n_segments = None

    note = "OVITO DXA — complementary to Aegis WS proxy"
    if crystal == "hex":
        note += " (WC hex mapped to HCP lattice for DXA — approximate)"

    dxa_attrs = {k: v for k, v in attrs.items() if "DislocationAnalysis" in k or "CrystalAnalysis" in k}

    return {
        "status": "ok",
        "dump": dump_name,
        "crystal": crystal,
        "ovito_lattice": lattice,
        "how": how,
        "dislocation_length_A": length_f,
        "cell_volume_A3": volume_f,
        "dislocation_density_per_A2": density,
        "n_dislocation_segments": n_segments,
        "dxa_attributes": dxa_attrs,
        "crystal_type_fractions": type_fracs,
        "ca_file": "dislocations.ca",
        "note": note,
        "ovito_docs": "https://docs.ovito.org/python/reference/pipelines/modifiers/dislocation_analysis.html",
    }


def _run_dxa_inprocess(dump: Path, out_path: Path, crystal: str, job_dir: Path) -> dict[str, Any]:
    from ovito.io import export_file, import_file  # type: ignore
    from ovito.modifiers import DislocationAnalysisModifier  # type: ignore

    lattice_name = _ovito_lattice_name(crystal)
    lattice_enum = getattr(DislocationAnalysisModifier.Lattice, lattice_name, DislocationAnalysisModifier.Lattice.BCC)
    pipeline = import_file(str(dump))
    mod = DislocationAnalysisModifier()
    mod.input_crystal_structure = lattice_enum
    pipeline.modifiers.append(mod)
    data = pipeline.compute()
    summary = _summarize_dxa_data(
        data, dump_name=dump.name, crystal=crystal, lattice=lattice_name, how="in-process"
    )
    ca_path = job_dir / "dislocations.ca"
    try:
        export_file(data, str(ca_path), "ca")
        summary["ca_file"] = ca_path.name
        summary["ca_hint"] = "Open dislocations.ca in OVITO desktop to inspect the network."
    except Exception as exc:  # noqa: BLE001
        summary["ca_file"] = None
        summary["ca_hint"] = f"CA export skipped: {exc}"
    out_path.write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")
    return summary


def _dxa_script_text(dump: Path, out_path: Path, crystal: str, ca_path: Path) -> str:
    lattice_name = _ovito_lattice_name(crystal)
    return f'''# Auto-generated by Aegis — OVITO DXA
from ovito.io import import_file, export_file
from ovito.modifiers import DislocationAnalysisModifier
import json

dump = r"{dump.as_posix()}"
out = r"{out_path.as_posix()}"
ca = r"{ca_path.as_posix()}"
crystal = {crystal!r}
lattice_name = {lattice_name!r}

pipeline = import_file(dump)
mod = DislocationAnalysisModifier()
mod.input_crystal_structure = getattr(
    DislocationAnalysisModifier.Lattice, lattice_name, DislocationAnalysisModifier.Lattice.BCC
)
pipeline.modifiers.append(mod)
data = pipeline.compute()
attrs = dict(data.attributes)
length = attrs.get("DislocationAnalysis.total_line_length")
volume = attrs.get("DislocationAnalysis.cell_volume")
try:
    length_f = float(length) if length is not None else None
except Exception:
    length_f = None
try:
    volume_f = float(volume) if volume is not None else None
except Exception:
    volume_f = None
density = (length_f / volume_f) if (length_f is not None and volume_f and volume_f > 0) else None
n_segments = None
try:
    net = data.dislocations
    if net is not None:
        n_segments = len(getattr(net, "lines", getattr(net, "segments", [])) or [])
except Exception:
    pass
dxa_attrs = {{k: v for k, v in attrs.items() if "DislocationAnalysis" in k or "CrystalAnalysis" in k}}
type_fracs = {{}}
for key, val in attrs.items():
    if "CrystalAnalysis" in key or "StructureType" in key or key.startswith("DislocationAnalysis.count"):
        try:
            type_fracs[key] = float(val)
        except Exception:
            type_fracs[key] = val
note = "OVITO DXA — complementary to Aegis WS proxy"
if crystal == "hex":
    note += " (WC hex mapped to HCP lattice for DXA — approximate)"
ca_name = None
ca_hint = None
try:
    export_file(data, ca, "ca")
    ca_name = "dislocations.ca"
    ca_hint = "Open dislocations.ca in OVITO desktop to inspect the network."
except Exception as exc:
    ca_hint = f"CA export skipped: {{exc}}"
summary = {{
    "status": "ok",
    "dump": r"{dump.name}",
    "crystal": crystal,
    "ovito_lattice": lattice_name,
    "how": "ovitos",
    "dislocation_length_A": length_f,
    "cell_volume_A3": volume_f,
    "dislocation_density_per_A2": density,
    "n_dislocation_segments": n_segments,
    "dxa_attributes": dxa_attrs,
    "crystal_type_fractions": type_fracs,
    "ca_file": ca_name,
    "ca_hint": ca_hint,
    "note": note,
    "ovito_docs": "https://docs.ovito.org/python/reference/pipelines/modifiers/dislocation_analysis.html",
}}
open(out, "w", encoding="utf-8").write(json.dumps(summary, indent=2, default=str))
print("Aegis DXA written")
'''


def run_dxa_on_job(job_dir: Path, *, crystal: str | None = None) -> dict[str, Any]:
    """Run DXA if OVITO is available; otherwise write an honest stub summary."""
    info = discover_ovito()
    out_path = job_dir / "dxa_summary.json"
    target = _pick_dump(job_dir)
    cry = crystal or _crystal_from_job(job_dir)

    if not info["ovito_found"]:
        summary = {
            "status": "unavailable",
            "ovito_found": False,
            "message": info["ovito_message"],
            "install_hint": info.get("install_hint"),
            "docs_url": info.get("docs_url"),
            "dump": target.name if target else None,
            "crystal": cry,
            "dislocation_length_A": None,
            "note": "Aegis never fabricates DXA networks. Install OVITO to enable.",
        }
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    if target is None:
        summary = {
            "status": "unavailable",
            "ovito_found": True,
            "message": "No trajectory dump found for DXA (need dump.*.lammpstrj after the initial frame).",
            "dump": None,
            "crystal": cry,
            "dislocation_length_A": None,
            "note": "Run a cascade/implant/surface/interstitial job first, then refresh DXA.",
        }
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    # Prefer in-process module (pip install ovito) — friendliest for coding
    mod_ok, _, _ = _try_import_ovito()
    if mod_ok:
        try:
            return _run_dxa_inprocess(target, out_path, cry, job_dir)
        except Exception as exc:  # noqa: BLE001
            # Fall through to ovitos if module path fails
            if not info.get("ovito_path"):
                summary = {
                    "status": "failed",
                    "message": f"In-process OVITO DXA failed: {exc}",
                    "ovito_found": True,
                    "crystal": cry,
                    "dump": target.name,
                }
                out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
                return summary

    ovitos = info.get("ovito_path")
    if not ovitos:
        summary = {
            "status": "failed",
            "message": (
                "OVITO module failed and ovitos is not available. "
                "Reinstall with `pip install -U ovito` or set AEGIS_OVITO_BIN."
            ),
            "ovito_found": True,
            "crystal": cry,
            "dump": target.name,
        }
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    script = job_dir / "_aegis_dxa.py"
    ca_path = job_dir / "dislocations.ca"
    script.write_text(_dxa_script_text(target, out_path, cry, ca_path), encoding="utf-8")
    try:
        proc = subprocess.run(
            [ovitos, str(script)],
            cwd=job_dir,
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        if out_path.exists():
            return json.loads(out_path.read_text(encoding="utf-8"))
        return {
            "status": "failed",
            "message": (proc.stderr or proc.stdout or "DXA script failed")[:800],
            "ovito_found": True,
            "crystal": cry,
            "dump": target.name,
            "how": "ovitos",
        }
    except Exception as exc:  # noqa: BLE001
        summary = {
            "status": "failed",
            "message": str(exc),
            "ovito_found": True,
            "crystal": cry,
            "dump": target.name,
        }
        out_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary


def load_dxa_summary(job_dir: Path) -> dict[str, Any] | None:
    path = job_dir / "dxa_summary.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def install_ovito_hint() -> dict[str, Any]:
    """Return copy-paste install instructions for the current interpreter."""
    py = sys.executable
    return {
        "python": py,
        "pip_command": f'"{py}" -m pip install -U ovito',
        "conda_command": (
            "conda install --strict-channel-priority "
            "-c https://conda.ovito.org -c conda-forge ovito"
        ),
        "env_var": "AEGIS_OVITO_BIN",
        "env_example": r"AEGIS_OVITO_BIN=C:\Program Files\OVITO Pro\ovitos.exe",
        "docs_url": "https://docs.ovito.org/python/introduction/installation.html",
        "note": (
            "Prefer pip into the Aegis .venv so DXA runs in-process. "
            "OVITO Pro's ovitos works without pip if AEGIS_OVITO_BIN or PATH is set."
        ),
    }
