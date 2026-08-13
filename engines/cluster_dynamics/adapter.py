"""Cascade → cluster-dynamics initializer + job adapter."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from cluster_dynamics.rates import load_catalog
from cluster_dynamics.ssa_heap import run_ssa
from kmc.provenance import build_provenance, merge_router_warnings

VOLUME_WARN_CM3 = 5e-10


def init_from_defects(job_dir: Path, *, volume_cm3: float) -> dict[str, float]:
    defects: dict[str, Any] = {}
    if (job_dir / "defects.json").exists():
        try:
            defects = json.loads((job_dir / "defects.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            defects = {}
    s = defects.get("summary") or {}
    return {
        "n_vac": float(s.get("vacancies") or 0),
        "n_int": float(s.get("interstitials") or 0),
        "n_he": 0.0,
        "n_clusters": float(s.get("clusters") or 0),
        "volume_cm3": float(volume_cm3),
    }


def run_cluster_dynamics(
    job_dir: Path,
    *,
    temperature_K: float = 600.0,
    target_time_s: float = 1e6,
    volume_cm3: float = 1e-9,
    max_events: int = 5000,
    catalog_path: str | None = None,
    seed: int = 1,
    router: dict[str, Any] | None = None,
) -> dict[str, Any]:
    catalog = load_catalog(catalog_path)
    initial = init_from_defects(job_dir, volume_cm3=volume_cm3)
    warnings: list[str] = list((router or {}).get("warnings") or [])
    if volume_cm3 < VOLUME_WARN_CM3:
        warnings.append(
            f"Simulated volume {volume_cm3:g} cm³ is below 5e-10 cm³ — "
            "Adjanor 2025 notes finite-size side effects; treat populations as engineering only."
        )
    if catalog.get("is_example"):
        warnings.append(
            "Using example rate catalog — replace with a literature/user table before any lifetime claim."
        )
    result = run_ssa(
        initial,
        catalog,
        volume_cm3=volume_cm3,
        temperature_K=temperature_K,
        target_time_s=target_time_s,
        max_events=max_events,
        seed=seed,
    )
    prov = build_provenance(
        "stochastic_cd",
        synthetic=bool(catalog.get("is_example")),
        prefactor_model="unknown",
        structure_class="as_cascade",
        trapping_risk="unknown",
        validation_status="unvalidated" if catalog.get("is_example") else "reference_curve",
        target_time_s=float(result.get("simulated_time_s") or 0),
        simulated_volume_cm3=volume_cm3,
        warnings=warnings,
    )
    out: dict[str, Any] = {
        "format": "aegis-cd-summary-v1",
        "engine": "stochastic_cd",
        "status": "annealed" if result.get("n_events") else "stubbed",
        "message": (
            "SSA cluster dynamics from cascade defect counts. "
            + ("Example catalog — unvalidated." if catalog.get("is_example") else "User catalog loaded.")
        ),
        "temperature_K": temperature_K,
        "volume_cm3": volume_cm3,
        "volume_warn": volume_cm3 < VOLUME_WARN_CM3,
        "catalog_path": catalog.get("catalog_path"),
        "initial": initial,
        "provenance": merge_router_warnings(prov, router),
        **result,
    }
    work = job_dir / "cd_work"
    work.mkdir(parents=True, exist_ok=True)
    (work / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (job_dir / "cd_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
