"""Job adapter for first-passage diagnostics on cascade anneal event logs."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from first_passage.kps import first_passage_from_events
from kmc.provenance import build_provenance, merge_router_warnings


def run_first_passage(
    job_dir: Path,
    *,
    temperature_K: float = 600.0,
    router: dict[str, Any] | None = None,
) -> dict[str, Any]:
    events: list[dict[str, Any]] = []
    for name in ("kart_summary.json", "ml_kmc_summary.json"):
        path = job_dir / name
        if not path.exists():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        ev = data.get("events")
        if isinstance(ev, list) and ev:
            events = ev
            break
        for run in data.get("runs") or []:
            if isinstance(run, dict) and run.get("events"):
                events = list(run["events"])
                break
        if events:
            break
    result = first_passage_from_events(events, temperature_K=temperature_K)
    warnings = list((router or {}).get("warnings") or [])
    if (result.get("basins") or {}).get("trapping_risk") == "high":
        warnings.append("High flicker ratio — first-passage escape should replace local hops in this basin.")
    if not events:
        warnings.append("No event log yet — MFPT uses default barriers only.")
    prov = build_provenance(
        "first_passage",
        synthetic=not events,
        prefactor_model="constant",
        structure_class="as_cascade",
        trapping_risk=(result.get("basins") or {}).get("trapping_risk") or "unknown",
        validation_status="unvalidated",
        target_time_s=float((result.get("mfpt") or {}).get("mfpt_s") or 0),
        flicker_ratio=(result.get("basins") or {}).get("flicker_ratio"),
        warnings=warnings,
    )
    out = {
        **result,
        "engine": "first_passage",
        "status": "diagnosed" if events else "stubbed",
        "n_events_in": len(events),
        "provenance": merge_router_warnings(prov, router),
    }
    work = job_dir / "kps_work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (job_dir / "kps_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
