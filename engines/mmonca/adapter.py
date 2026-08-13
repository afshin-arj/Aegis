from __future__ import annotations

import json
import os
import shutil
from pathlib import Path
from typing import Any

from kmc.provenance import build_provenance, merge_router_warnings
from mmonca.handoff import collect_okmc_objects


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
        msg = "MMonCa binary discovered. Comparison-only OKMC — Aegis writes object handoff v2 and probes the binary."
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
    """Write MMonCa object handoff v2; probe binary when present; never claim primary kMC."""
    info = discover_mmonca()
    work = job_dir / "mmonca_work"
    work.mkdir(parents=True, exist_ok=True)
    pack = collect_okmc_objects(job_dir)
    objects = list(pack.get("objects") or [])
    scalars = pack.get("scalar_summary") or {}
    n_v = int(scalars.get("vacancies") or 0)
    n_i = int(scalars.get("interstitials") or 0)

    handoff = {
        "format": "aegis-mmonca-handoff-v2",
        "tier": "mmonca_compare",
        "temperature_K": temperature_K,
        "max_events": max_events,
        "objects_file": "objects.json",
        "n_objects": len(objects),
        "scalar_summary": scalars,
        "notes": [
            "Comparison-only object-KMC path — not the default post-cascade anneal.",
            "Objects include clustered vacancies/SIAs from defects.json and optional DXA loops.",
            "Aegis does not redistribute MMonCa; configure locally.",
        ],
    }
    (work / "objects.json").write_text(json.dumps(pack, indent=2), encoding="utf-8")
    (work / "handoff.json").write_text(json.dumps(handoff, indent=2), encoding="utf-8")
    launch = f"""#!/bin/sh
# Aegis MMonCa comparison launch template — edit for your MMonCa input dialect.
# objects: {len(objects)}  T={temperature_K} K  max_events={max_events}
# Usage: $AEGIS_MMONCA_BIN <your-input>   (see engines/mmonca/SETUP.md)
echo "MMonCa comparison handoff in $(pwd)"
"""
    (work / "run_mmonca.sh.aegis").write_text(launch, encoding="utf-8")

    binary_probed = False
    probe_message = ""
    if info.get("mmonca_found") and info.get("mmonca_path"):
        try:
            import subprocess

            proc = subprocess.run(
                [str(info["mmonca_path"]), "--help"],
                cwd=work,
                capture_output=True,
                text=True,
                timeout=20,
                check=False,
            )
            binary_probed = True
            probe_message = (proc.stdout or proc.stderr or "")[-500:]
        except Exception as exc:  # noqa: BLE001
            probe_message = str(exc)

    # Synthetic object evolution for UI until a real OKMC trajectory exists
    n = max(5, min(int(max_events), 40))
    events = []
    v, i = float(n_v), float(n_i)
    for step in range(1, n + 1):
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
                "n_objects": len(objects),
                "time_s": 1e-9 * step * (600.0 / max(temperature_K, 1.0)),
                "source": "aegis-mmonca-stub",
            }
        )

    status = "stubbed"
    if info["mmonca_found"]:
        status = "handoff_ready" if binary_probed else "error"
    message = info["mmonca_message"]
    if binary_probed:
        message = (
            "MMonCa binary probed; object handoff v2 written. "
            "Launch via run_mmonca.sh.aegis — comparison-only, not the primary kMC tier."
        )
    out: dict[str, Any] = {
        "format": "aegis-mmonca-summary-v3",
        "engine": "mmonca",
        "tier": "mmonca_compare",
        "temperature_K": temperature_K,
        "max_events": max_events,
        "status": status,
        "message": message,
        "mmonca_found": info["mmonca_found"],
        "binary_probed": binary_probed,
        "probe_tail": probe_message,
        "handoff": "mmonca_work/handoff.json",
        "n_objects": len(objects),
        "objects": objects[:80],
        "events": events,
        "final_objects": {
            "vacancies": events[-1]["vacancies"] if events else n_v,
            "interstitials": events[-1]["interstitials"] if events else n_i,
            "clusters": len(objects),
        },
        "provenance": merge_router_warnings(
            build_provenance(
                "mmonca_compare",
                synthetic=not binary_probed,
                prefactor_model="unknown",
                structure_class="as_cascade",
                trapping_risk="unknown",
                validation_status="handoff_ready" if binary_probed else "stub",
                target_time_s=0.0,
                warnings=[
                    "MMonCa path is comparison-only — not the primary post-cascade kMC tier.",
                    "Event curve is Aegis synthetic until a real OKMC trajectory is imported.",
                ],
            ),
            router,
        ),
    }
    (job_dir / "mmonca_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (work / "run_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
