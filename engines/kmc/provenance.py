"""Shared KMC provenance blocks for summaries and JobInfo."""

from __future__ import annotations

from typing import Any, Literal

KmcTierLiteral = Literal[
    "kart",
    "ml_kmc",
    "stochastic_cd",
    "first_passage",
    "mmonca_compare",
]
PrefactorModel = Literal["constant", "htst", "composition_polynomial", "unknown"]
ValidationStatus = Literal["energy_dat", "reference_curve", "stub", "handoff_ready", "unvalidated"]
TrappingRisk = Literal["low", "medium", "high", "unknown"]
StructureClass = Literal["random", "mmc", "as_cascade", "unknown"]


def build_provenance(
    tier: KmcTierLiteral,
    *,
    synthetic: bool,
    prefactor_model: PrefactorModel = "unknown",
    structure_class: StructureClass = "as_cascade",
    trapping_risk: TrappingRisk = "unknown",
    validation_status: ValidationStatus = "unvalidated",
    target_time_s: float = 0.0,
    simulated_volume_cm3: float | None = None,
    flicker_ratio: float | None = None,
    warnings: list[str] | None = None,
    sro_parameters: dict[str, float] | None = None,
) -> dict[str, Any]:
    w = list(warnings or [])
    if synthetic and validation_status not in {"stub", "handoff_ready", "unvalidated"}:
        validation_status = "stub"
    return {
        "format": "aegis-kmc-provenance-v1",
        "tier": tier,
        "synthetic": bool(synthetic),
        "prefactor_model": prefactor_model,
        "structure_class": structure_class,
        "sro_parameters": sro_parameters,
        "trapping_risk": trapping_risk,
        "validation_status": validation_status,
        "target_time_s": float(target_time_s),
        "simulated_volume_cm3": simulated_volume_cm3,
        "flicker_ratio": flicker_ratio,
        "warnings": w,
    }


def merge_router_warnings(provenance: dict[str, Any], router: dict[str, Any] | None) -> dict[str, Any]:
    if not router:
        return provenance
    extra = list(router.get("warnings") or [])
    seen = set(provenance.get("warnings") or [])
    for w in extra:
        if w not in seen:
            provenance.setdefault("warnings", []).append(w)
    return provenance
