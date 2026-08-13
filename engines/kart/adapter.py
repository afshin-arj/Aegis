from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

from kmc.provenance import build_provenance, merge_router_warnings
from kart.handoff import (
    analyze_trapping,
    build_kart_package,
    parse_energy_dat,
    summarize_event_kinetics,
    synthetic_events,
)


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
    router: dict[str, Any] | None = None,
    prefactor_mode: str | None = None,
    work_suffix: str = "",
    omp_threads: int = 1,
) -> dict[str, Any]:
    n_vac, n_sia = _defect_counts(job_dir)
    omp_n = max(1, min(int(omp_threads or 1), 256))
    handoff = build_kart_package(
        job_dir,
        temperature_K=temperature_K,
        max_events=max_events,
        max_wall_s=max_wall_s,
        max_kmc_time_s=max_kmc_time_s,
        material=material,
        potential=potential,
        prefactor_mode=prefactor_mode,
        work_suffix=work_suffix,
        omp_threads=omp_n,
    )
    work = job_dir / handoff["work_dir"]
    mode = handoff.get("prefactor_mode") or "constant"
    trapping_hint = handoff.get("trapping_risk_hint") or "unknown"
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
        "handoff_format": handoff.get("format"),
        "prefactor_mode": mode,
        "omp_threads": omp_n,
    }

    def _attach_provenance(
        *,
        synthetic: bool,
        validation_status: str,
        events: list[dict[str, Any]],
    ) -> None:
        trap = analyze_trapping(events)
        risk = trap.get("trapping_risk") or trapping_hint
        kinetics = summarize_event_kinetics(events)
        out["kinetics"] = kinetics
        warnings = list(router.get("warnings") or []) if router else []
        if mode == "constant" and handoff.get("concentrated_alloy"):
            warnings.append(
                "Constant Γ₀ on a concentrated alloy — compare with hTST (kart_prefactor_compare) "
                "before trusting sluggish-diffusion trends (Huang 2023)."
            )
        prov = build_provenance(
            "kart",
            synthetic=synthetic,
            prefactor_model="htst" if mode == "htst" else "constant",
            structure_class="as_cascade",
            trapping_risk=risk if risk in {"low", "medium", "high"} else "unknown",
            validation_status=validation_status,
            target_time_s=float(max_kmc_time_s),
            flicker_ratio=trap.get("flicker_ratio"),
            warnings=warnings,
        )
        out["trapping"] = trap
        out["provenance"] = merge_router_warnings(prov, router)

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
        _attach_provenance(synthetic=True, validation_status="stub", events=out["events"])
        (work / "kart_run_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
        return out

    # Attempt a bounded invocation in the handoff directory.
    # Full production anneals typically use KMC.sh; Aegis probes the binary and
    # picks up Energy.dat if the user/runtime produced one.
    binary = info["kart_binary"]
    t0 = time.perf_counter()
    env = os.environ.copy()
    env["OMP_NUM_THREADS"] = str(omp_n)
    try:
        proc = subprocess.run(
            [binary, "--help"],
            cwd=work,
            capture_output=True,
            text=True,
            timeout=min(30.0, max(5.0, max_wall_s)),
            check=False,
            env=env,
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
    events = parse_energy_dat(work / "Energy.dat", temperature_K=temperature_K)
    if events:
        out["events"] = events[: max_events]
        out["status"] = "annealed"
        out["message"] = (
            f"Parsed {len(out['events'])} events from Energy.dat at T={temperature_K} K "
            f"(prefactor_mode={mode})."
        )
        _attach_provenance(synthetic=False, validation_status="energy_dat", events=out["events"])
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
            "KART binary present; aegis-kart-handoff-v3 package written under kart_work/. "
            f"Launch via KMC.sh.aegis (WSL/Linux, PREFACTOR_MODE={mode}). "
            "Events shown are Aegis stubs until Energy.dat exists."
        )
        _attach_provenance(synthetic=True, validation_status="handoff_ready", events=out["events"])

    (work / "kart_run_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def _compare_prefactor_pair(
    constant_run: dict[str, Any],
    htst_run: dict[str, Any],
) -> dict[str, Any]:
    """Side-by-side constant-ν vs hTST kinetics delta (Phase F5)."""
    kc = constant_run.get("kinetics") or summarize_event_kinetics(constant_run.get("events") or [])
    kh = htst_run.get("kinetics") or summarize_event_kinetics(htst_run.get("events") or [])
    mb_c = kc.get("mean_barrier_eV")
    mb_h = kh.get("mean_barrier_eV")
    delta_barrier = None
    if mb_c is not None and mb_h is not None:
        delta_barrier = round(float(mb_h) - float(mb_c), 6)
    return {
        "constant": kc,
        "htst": kh,
        "delta_mean_barrier_eV": delta_barrier,
        "note": (
            "Compare packages written for constant Γ₀ vs hTST. "
            "Deltas are meaningful only after real Energy.dat exists for both modes."
        ),
    }


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
    router: dict[str, Any] | None = None,
    prefactor_compare: bool = False,
    omp_threads: int = 1,
) -> dict[str, Any]:
    """Phase-2 anneal path: per-T handoff packages + optional DOE / prefactor compare."""
    info = discover_kart()
    temps = [float(t) for t in (temperatures or [temperature_K]) if float(t) > 0]
    if not temps:
        temps = [float(temperature_K)]
    omp_n = max(1, min(int(omp_threads or 1), 256))

    # Load material/potential from job dir when not provided
    if material is None and (job_dir / "material.json").exists():
        material = json.loads((job_dir / "material.json").read_text(encoding="utf-8"))
    if potential is None and (job_dir / "potential.json").exists():
        potential = json.loads((job_dir / "potential.json").read_text(encoding="utf-8"))

    runs: list[dict[str, Any]] = []
    compares: list[dict[str, Any]] = []
    if prefactor_compare:
        for T in temps:
            const_run = _run_one_temperature(
                job_dir,
                temperature_K=T,
                max_events=int(max_events),
                max_wall_s=float(max_wall_s),
                max_kmc_time_s=float(max_kmc_time_s),
                material=material,
                potential=potential,
                info=info,
                router=router,
                prefactor_mode="constant",
                work_suffix="constant",
                omp_threads=omp_n,
            )
            htst_run = _run_one_temperature(
                job_dir,
                temperature_K=T,
                max_events=int(max_events),
                max_wall_s=float(max_wall_s),
                max_kmc_time_s=float(max_kmc_time_s),
                material=material,
                potential=potential,
                info=info,
                router=router,
                prefactor_mode="htst",
                work_suffix="htst",
                omp_threads=omp_n,
            )
            pair = _compare_prefactor_pair(const_run, htst_run)
            compares.append({"temperature_K": T, **pair})
            # Prefer hTST as the primary run for UI/timeline when comparing
            htst_run = {**htst_run, "prefactor_compare_pair": pair}
            runs.append(htst_run)
            runs.append(const_run)
    else:
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
                router=router,
                omp_threads=omp_n,
            )
            for T in temps
        ]

    primary = next((r for r in runs if r.get("prefactor_mode") == "htst"), runs[0])
    primary_prov = primary.get("provenance") if isinstance(primary.get("provenance"), dict) else None
    summary: dict[str, Any] = {
        "format": "aegis-kart-summary-v4",
        "engine": "kart",
        "doe": len(temps) > 1,
        "prefactor_compare": bool(prefactor_compare),
        "prefactor_compare_results": compares or None,
        "temperatures_K": temps,
        "kart_found": bool(info.get("kart_found")),
        "kart_message": info.get("kart_message", ""),
        "router": router,
        "runs": runs,
        "provenance": primary_prov,
        # Back-compat fields for older UI consumers
        "temperature_K": primary["temperature_K"],
        "max_events": max_events,
        "status": primary["status"] if len(runs) == 1 else "doe_complete",
        "message": (
            primary["message"]
            if len(runs) == 1 and not prefactor_compare
            else (
                f"Prefactor compare complete: constant vs hTST at {len(temps)} T."
                if prefactor_compare
                else f"DOE complete: {len(temps)} anneal temperatures."
            )
        ),
        "events": primary.get("events") or [],
        "handoff": primary.get("handoff"),
        "prefactor_mode": primary.get("prefactor_mode"),
        "omp_threads": omp_n,
        "kinetics": primary.get("kinetics"),
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
