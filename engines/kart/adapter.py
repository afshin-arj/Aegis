from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any


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
        msg.append("KART binary discovered.")

    return {
        "kart_root": str(root_path) if root_path else None,
        "kart_found": binary is not None,
        "kart_binary": binary,
        "kart_commit_expected": EXPECTED_COMMIT,
        "kart_message": " ".join(msg),
    }


def _write_cascade_handoff(job_dir: Path, temperature_K: float, max_events: int) -> Path:
    """Write Phase-1 cascade→KART handoff package (defects + request).

    Full k-ART catalog coupling is Phase-2; this artifact documents the contract.
    """
    defects_path = job_dir / "defects.json"
    defects: dict[str, Any] = {}
    if defects_path.exists():
        try:
            defects = json.loads(defects_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            defects = {}
    summary = defects.get("summary") or {}
    handoff = {
        "format": "aegis-kart-handoff-v1",
        "temperature_K": temperature_K,
        "max_events": max_events,
        "source_defects": str(defects_path.name),
        "n_vacancies": summary.get("vacancies"),
        "n_interstitials": summary.get("interstitials"),
        "n_clusters": summary.get("clusters"),
        "dump": summary.get("dump"),
        "notes": [
            "Phase-1 adapter writes this handoff for reproducibility.",
            "Phase-2 will convert defect geometry into a KART restart/event catalog.",
        ],
    }
    out = job_dir / "kart_handoff.json"
    out.write_text(json.dumps(handoff, indent=2), encoding="utf-8")
    return out


def run_anneal_stub_or_real(
    job_dir: Path,
    *,
    temperature_K: float,
    max_events: int,
) -> dict[str, Any]:
    """If KART binary exists, probe it and record handoff; else write stub results."""
    info = discover_kart()
    handoff = _write_cascade_handoff(job_dir, temperature_K, max_events)
    out: dict[str, Any] = {
        "engine": "kart",
        "temperature_K": temperature_K,
        "max_events": max_events,
        "status": "stub",
        "message": "",
        "events": [],
        "handoff": handoff.name,
    }
    summary_path = job_dir / "kart_summary.json"

    if not info["kart_found"]:
        out["message"] = (
            "KART binary not available — anneal stubbed. " + info["kart_message"]
        )
        out["events"] = [
            {"event": i, "barrier_eV": 0.4 + 0.01 * (i % 7), "time_s": 1e-9 * i}
            for i in range(min(20, max_events))
        ]
        out["status"] = "stubbed"
        summary_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    # Binary present: Phase-1 probes the executable and persists handoff for Phase-2 coupling.
    cmd = [info["kart_binary"], "--help"]
    try:
        proc = subprocess.run(
            cmd,
            cwd=job_dir,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        out["status"] = "binary_present"
        out["message"] = (
            "KART binary responded; cascade handoff written. "
            "Full cascade→k-ART catalog anneal is Phase-2; "
            f"exit={proc.returncode}."
        )
        out["stdout_tail"] = (proc.stdout or proc.stderr or "")[-2000:]
        out["events"] = [
            {"event": i, "barrier_eV": 0.5, "time_s": 1e-12 * i}
            for i in range(min(5, max_events))
        ]
    except Exception as exc:  # noqa: BLE001
        out["status"] = "error"
        out["message"] = f"KART invocation failed: {exc}"
    summary_path.write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
