from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from kart.handoff import build_kart_package, parse_energy_dat, synthetic_events


EXPECTED_COMMIT = os.environ.get("AEGIS_KART_COMMIT", "62d66adf")


def discover_kart() -> dict[str, Any]:
    root = os.environ.get("AEGIS_KART_ROOT", "").strip()
    bin_env = os.environ.get("AEGIS_KART_BIN", "").strip()
    candidates: list[Path] = []
    if bin_env:
        candidates.append(Path(bin_env))
    if root:
        r = Path(root)
        candidates.extend(
            [
                r / "kart",
                r / "bin" / "kart",
                r / "build" / "kart",
                r / "KART",
                r / "kart.exe",
            ]
        )
    repo = Path(__file__).resolve().parents[2]
    tp = repo / "third_party" / "kart"
    if not root:
        root_path = tp if tp.exists() else None
    else:
        root_path = Path(root) if Path(root).exists() else None
        if root_path is None and tp.exists():
            root_path = tp
    if tp.exists():
        candidates.extend([tp / "kart", tp / "bin" / "kart", tp / "kart.exe"])

    binary = None
    for c in candidates:
        if c and c.exists() and c.is_file():
            binary = str(c.resolve())
            break
    which = shutil.which("kart")
    if not binary and which:
        binary = which

    msg = []
    if root_path is None:
        msg.append(
            "KART root not found. Clone groupe_mousseau/kart into third_party/kart "
            f"and checkout {EXPECTED_COMMIT}, then build. See engines/kart/SETUP.md."
        )
    elif binary is None:
        msg.append(
            f"KART sources may be present at {root_path}, but no binary was found. "
            "Build per kart-doc / SETUP.md; set AEGIS_KART_BIN."
        )
    else:
        msg.append("KART binary discovered. Phase-2 writes kart_work handoff packages per anneal T.")

    return {
        "kart_root": str(root_path) if root_path else None,
        "kart_found": binary is not None,
        "kart_binary": binary,
        "kart_commit_expected": EXPECTED_COMMIT,
        "kart_message": " ".join(msg),
    }


def _defect_counts(job_dir: Path) -> tuple[int, int]:
    path = job_dir / "defects.json"
    if not path.exists():
        return 0, 0
    try:
        summary = json.loads(path.read_text(encoding="utf-8")).get("summary") or {}
    except json.JSONDecodeError:
        return 0, 0
    return int(summary.get("vacancies") or 0), int(summary.get("interstitials") or 0)


def _run_one_temperature(
    job_dir: Path,
    *,
    temperature_K: float,
    max_events: int,
    max_wall_s: float,
    max_kmc_time_s: float,
    material: dict[str, Any] | None,
    potential: dict[str, Any] | None,
    info: dict[str, Any],
) -> dict[str, Any]:
    n_vac, n_sia = _defect_counts(job_dir)
    handoff = build_kart_package(
        job_dir,
        temperature_K=temperature_K,
        max_events=max_events,
        max_wall_s=max_wall_s,
        max_kmc_time_s=max_kmc_time_s,
        material=material,
        potential=potential,
    )
    work = job_dir / handoff["work_dir"]
    out: dict[str, Any] = {
        "temperature_K": temperature_K,
        "max_events": max_events,
        "max_wall_s": max_wall_s,
        "max_kmc_time_s": max_kmc_time_s,
        "handoff": handoff["work_dir"],
        "status": "stubbed",
        "message": "",
        "events": [],
        "wall_elapsed_s": 0.0,
    }

    if not info.get("kart_found"):
        out["message"] = "KART binary not available — handoff written; events stubbed."
        out["events"] = synthetic_events(
            temperature_K=temperature_K,
            max_events=max_events,
            max_kmc_time_s=max_kmc_time_s,
            n_vac=n_vac,
            n_sia=n_sia,
        )
        out["status"] = "stubbed"
        (work / "kart_run_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    # Attempt a bounded invocation in the handoff directory.
    # Full production anneals typically use KMC.sh; Aegis probes the binary and
    # picks up Energy.dat if the user/runtime produced one.
    binary = info["kart_binary"]
    t0 = time.perf_counter()
    try:
        proc = subprocess.run(
            [binary, "--help"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=min(30.0, max(5.0, max_wall_s)),
            check=False,
        )
        out["stdout_tail"] = (proc.stdout or proc.stderr or "")[-2000:]
        out["exit_code"] = proc.returncode
    except subprocess.TimeoutExpired:
        out["message"] = "KART probe timed out."
        out["status"] = "timeout"
    except Exception as exc:  # noqa: BLE001
        out["message"] = f"KART invocation failed: {exc}"
        out["status"] = "error"

    out["wall_elapsed_s"] = round(time.perf_counter() - t0, 3)
    events = parse_energy_dat(work / "Energy.dat")
    if events:
        out["events"] = events[: max_events]
        out["status"] = "annealed"
        out["message"] = (
            f"Parsed {len(out['events'])} events from Energy.dat at T={temperature_K} K."
        )
    else:
        out["events"] = synthetic_events(
            temperature_K=temperature_K,
            max_events=min(max_events, 25),
            max_kmc_time_s=max_kmc_time_s,
            n_vac=n_vac,
            n_sia=n_sia,
        )
        out["status"] = "handoff_ready"
        out["message"] = (
            "KART binary present; aegis-kart-handoff-v2 package written under kart_work/. "
            "Launch via KMC.sh.aegis (WSL/Linux). Events shown are Aegis stubs until Energy.dat exists."
        )

    (work / "kart_run_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def run_anneal_stub_or_real(
    job_dir: Path,
    *,
    temperature_K: float = 600.0,
    max_events: int = 1000,
    max_wall_s: float = 600.0,
    max_kmc_time_s: float = 1.0,
    temperatures: list[float] | None = None,
    material: dict[str, Any] | None = None,
    potential: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Phase-2 anneal path: per-T handoff packages + optional DOE over temperatures."""
    info = discover_kart()
    temps = [float(t) for t in (temperatures or [temperature_K]) if float(t) > 0]
    if not temps:
        temps = [float(temperature_K)]

    # Load material/potential from job dir when not provided
    if material is None and (job_dir / "material.json").exists():
        material = json.loads((job_dir / "material.json").read_text(encoding="utf-8"))
    if potential is None and (job_dir / "potential.json").exists():
        potential = json.loads((job_dir / "potential.json").read_text(encoding="utf-8"))

    runs = [
        _run_one_temperature(
            job_dir,
            temperature_K=T,
            max_events=int(max_events),
            max_wall_s=float(max_wall_s),
            max_kmc_time_s=float(max_kmc_time_s),
            material=material,
            potential=potential,
            info=info,
        )
        for T in temps
    ]

    primary = runs[0]
    summary: dict[str, Any] = {
        "format": "aegis-kart-summary-v2",
        "engine": "kart",
        "doe": len(runs) > 1,
        "temperatures_K": temps,
        "kart_found": bool(info.get("kart_found")),
        "kart_message": info.get("kart_message", ""),
        "runs": runs,
        # Back-compat fields for older UI consumers
        "temperature_K": primary["temperature_K"],
        "max_events": max_events,
        "status": primary["status"] if len(runs) == 1 else "doe_complete",
        "message": (
            primary["message"]
            if len(runs) == 1
            else f"DOE complete: {len(runs)} anneal temperatures."
        ),
        "events": primary.get("events") or [],
        "handoff": primary.get("handoff"),
    }
    (job_dir / "kart_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


# Backwards-compatible alias used by older imports
def _write_cascade_handoff(job_dir: Path, temperature_K: float, max_events: int) -> Path:
    meta = build_kart_package(
        job_dir,
        temperature_K=temperature_K,
        max_events=max_events,
        max_wall_s=600.0,
        max_kmc_time_s=1.0,
    )
    return job_dir / "kart_handoff.json"
