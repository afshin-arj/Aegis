from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from kmc.provenance import build_provenance, merge_router_warnings


def discover_mmonca() -> dict[str, Any]:
    """Locate optional MMonCa object-KMC binary (Phase-3 comparison path)."""
    bin_env = os.environ.get("AEGIS_MMONCA_BIN", "").strip()
    root = os.environ.get("AEGIS_MMONCA_ROOT", "").strip()
    candidates: list[Path] = []
    if bin_env:
        candidates.append(Path(bin_env))
    if root:
        r = Path(root)
        candidates.extend([r / "mmonca", r / "bin" / "mmonca", r / "MMonCa", r / "mmonca.exe"])
    repo = Path(__file__).resolve().parents[2]
    tp = repo / "third_party" / "mmonca"
    if tp.exists():
        candidates.extend([tp / "mmonca", tp / "bin" / "mmonca", tp / "mmonca.exe"])
    which = shutil.which("mmonca")
    if which:
        candidates.append(Path(which))

    binary = next((str(c.resolve()) for c in candidates if c and c.exists() and c.is_file()), None)
    if binary:
        msg = "MMonCa binary discovered. Phase-3 OKMC coupling is optional/stub-first."
    elif tp.exists() or (root and Path(root).exists()):
        msg = "MMonCa sources/path present but binary not found. Build upstream and set AEGIS_MMONCA_BIN."
    else:
        msg = (
            "MMonCa not configured. Optional object-KMC comparison engine — "
            "set AEGIS_MMONCA_BIN or clone under third_party/mmonca. See engines/mmonca/SETUP.md."
        )
    return {
        "mmonca_found": binary is not None,
        "mmonca_path": binary,
        "mmonca_root": str(Path(root)) if root else (str(tp) if tp.exists() else None),
        "mmonca_message": msg,
    }


def run_okmc_stub_or_real(
    job_dir: Path,
    *,
    temperature_K: float = 600.0,
    max_events: int = 1000,
    router: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write MMonCa-oriented handoff from defects; stub event evolution if binary missing."""
    info = discover_mmonca()
    work = job_dir / "mmonca_work"
    work.mkdir(parents=True, exist_ok=True)

    defects: dict[str, Any] = {}
    if (job_dir / "defects.json").exists():
        try:
            defects = json.loads((job_dir / "defects.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            defects = {}
    summary = defects.get("summary") or {}
    n_v = int(summary.get("vacancies") or 0)
    n_i = int(summary.get("interstitials") or 0)

    handoff = {
        "format": "aegis-mmonca-handoff-v1",
        "temperature_K": temperature_K,
        "max_events": max_events,
        "objects": {
            "vacancies": n_v,
            "interstitials": n_i,
            "clusters": int(summary.get("clusters") or 0),
        },
        "notes": [
            "Phase-3 optional OKMC path for comparison with k-ART.",
            "Aegis does not redistribute MMonCa; configure locally.",
        ],
    }
    (work / "handoff.json").write_text(json.dumps(handoff, indent=2), encoding="utf-8")

    # Synthetic object evolution for UI (vacancy–SIA recombination flavoured)
    n = max(5, min(int(max_events), 40))
    events = []
    v, i = float(n_v), float(n_i)
    for step in range(1, n + 1):
        # Prefer recombination while both species remain
        if v > 0 and i > 0 and step % 3 != 0:
            v -= 0.5
            i -= 0.5
            kind = "recombination"
        elif v > i:
            v = max(0.0, v - 0.25)
            kind = "vacancy_hop"
        else:
            i = max(0.0, i - 0.25)
            kind = "sia_hop"
        events.append(
            {
                "event": step,
                "kind": kind,
                "vacancies": round(v, 2),
                "interstitials": round(i, 2),
                "time_s": 1e-9 * step * (600.0 / max(temperature_K, 1.0)),
                "source": "aegis-mmonca-stub",
            }
        )

    out: dict[str, Any] = {
        "format": "aegis-mmonca-summary-v2",
        "engine": "mmonca",
        "temperature_K": temperature_K,
        "max_events": max_events,
        "status": "stubbed" if not info["mmonca_found"] else "handoff_ready",
        "message": (
            info["mmonca_message"]
            if not info["mmonca_found"]
            else "MMonCa binary present; handoff written. Full OKMC launch is operator-driven in Phase-3."
        ),
        "mmonca_found": info["mmonca_found"],
        "handoff": "mmonca_work/handoff.json",
        "events": events,
        "final_objects": {
            "vacancies": events[-1]["vacancies"] if events else n_v,
            "interstitials": events[-1]["interstitials"] if events else n_i,
        },
        "provenance": merge_router_warnings(
            build_provenance(
                "mmonca_compare",
                synthetic=True,
                prefactor_model="unknown",
                structure_class="as_cascade",
                trapping_risk="unknown",
                validation_status="stub" if not info["mmonca_found"] else "handoff_ready",
                target_time_s=0.0,
                warnings=[
                    "MMonCa path is comparison-only — not the primary post-cascade kMC tier.",
                    "Event curve is Aegis synthetic until real OKMC launch is wired.",
                ],
            ),
            router,
        ),
    }
    (job_dir / "mmonca_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (work / "run_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
