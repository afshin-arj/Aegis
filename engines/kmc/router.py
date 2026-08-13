"""Rule-based KMC tier recommendation (Adjanor 2025 + Huang 2023 ladder)."""

from __future__ import annotations

from typing import Any, Literal

KmcTier = Literal[
    "kart",
    "ml_kmc",
    "stochastic_cd",
    "first_passage",
    "mmonca_compare",
]

LONG_TERM_TIME_S = 1e6
TRAP_TIME_S = 1e-3  # very short simulated KMC window + low T → trapping likely


def _composition_hosts(material: dict[str, Any] | None) -> list[str]:
    if not material:
        return []
    out: list[str] = []
    for row in material.get("composition") or []:
        sym = str(row.get("symbol") or "").strip()
        pct = float(row.get("atomic_percent") or 0)
        if sym and pct > 0:
            out.append(sym)
    return out


def is_concentrated_alloy(material: dict[str, Any] | None) -> bool:
    """Two or more species each >5 at% — CSA sluggish-diffusion regime."""
    if not material:
        return False
    active = [
        float(c.get("atomic_percent") or 0)
        for c in material.get("composition") or []
        if float(c.get("atomic_percent") or 0) > 5.0
    ]
    return len(active) >= 2


def recommend_kmc(
    *,
    material: dict[str, Any] | None = None,
    target_time_s: float = 1.0,
    temperature_K: float = 600.0,
    run_kart_anneal: bool = False,
    run_mmonca_okmc: bool = False,
    kart_found: bool = False,
    structure_kind: str = "single_crystal",
    defect_summary: dict[str, Any] | None = None,
    requested_tier: str | None = None,
) -> dict[str, Any]:
    """Return recommended tier, warnings, and router notes for UI + job provenance."""
    warnings: list[str] = []
    notes: list[str] = []
    concentrated = is_concentrated_alloy(material)
    sk = (structure_kind or "single_crystal").lower()
    n_vac = int((defect_summary or {}).get("vacancies") or 0)
    n_sia = int((defect_summary or {}).get("interstitials") or 0)
    defect_load = n_vac + n_sia

    tier: KmcTier = "kart"
    if run_mmonca_okmc and not run_kart_anneal:
        tier = "mmonca_compare"
    elif target_time_s >= LONG_TERM_TIME_S:
        tier = "stochastic_cd"
        warnings.append(
            f"Target simulated time {target_time_s:g} s exceeds short kMC — "
            "stochastic cluster dynamics (not yet in Aegis) is the literature path for reactor lifetimes."
        )
    elif concentrated and not kart_found and not run_kart_anneal:
        tier = "ml_kmc"
        warnings.append(
            "Concentrated alloy without k-ART: ML rigid-lattice KMC (Phase E) is the fast CSA path — not yet wired."
        )
    elif run_kart_anneal or kart_found:
        tier = "kart"
    elif run_mmonca_okmc:
        tier = "mmonca_compare"

    if requested_tier:
        req = requested_tier.strip().lower()
        valid = {"kart", "ml_kmc", "stochastic_cd", "first_passage", "mmonca_compare"}
        if req in valid:
            if req != tier:
                notes.append(f"User requested tier '{req}' (router suggested '{tier}').")
            tier = req  # type: ignore[assignment]

    if concentrated and tier == "kart":
        warnings.append(
            "Concentrated alloy: prefer hTST / composition-dependent attempt frequencies — "
            "constant Γ₀=10¹³ s⁻¹ can mis-predict sluggish diffusion (Huang et al. 2023)."
        )
    if tier == "kart" and target_time_s < TRAP_TIME_S and temperature_K < 500:
        warnings.append(
            "Low T + short max KMC time: classical kMC may kinetic-trap (flickers) — "
            "first-passage kPS (Phase H) or longer anneal may be needed."
        )
    if defect_load > 50 and tier == "kart":
        warnings.append(
            "High defect load: verify trapping diagnostics on Energy.dat after anneal."
        )
    if sk not in {"", "single_crystal"}:
        warnings.append(
            f"structure_kind={sk}: post-cascade kMC handoffs use cascade geometry — "
            "treat as engineering handoff, not calibrated nanostructure anneal."
        )
    if tier == "stochastic_cd":
        notes.append("Phase G stochastic cluster dynamics is planned; only kart/mmonca run today.")
    if tier == "ml_kmc":
        notes.append("Phase E ML-KMC (ANN-LAC) is planned; use k-ART when binary is available.")

    prefactor_model: str = "htst" if concentrated and tier == "kart" else "constant"
    if concentrated and tier == "kart":
        notes.append("Handoff defaults prefactor_mode=htst for concentrated alloys.")

    trapping_risk: str = "unknown"
    if temperature_K < 500 and target_time_s < 10:
        trapping_risk = "medium"
    if temperature_K < 400 and defect_load > 20:
        trapping_risk = "high"

    return {
        "recommended_tier": tier,
        "warnings": warnings,
        "notes": notes,
        "concentrated_alloy": concentrated,
        "prefactor_model_hint": prefactor_model,
        "trapping_risk_hint": trapping_risk,
        "target_time_s": float(target_time_s),
        "temperature_K": float(temperature_K),
    }

