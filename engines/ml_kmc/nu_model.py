"""Attempt-frequency models (Huang 2023 ν(T, x) + constant Γ₀)."""

from __future__ import annotations

from typing import Any, Literal

# Placeholder 4th-order f(x_Fe) so the interface is real; not the paper's fitted
# coefficients (those stay user-supplied). Shape is monotonic-ish in x.
_DEFAULT_POLY = (1.0, -0.15, 0.08, -0.02, 0.005)
_H0 = 1.0e13  # Hz


def attempt_frequency(
    *,
    temperature_K: float,
    x_solute: float,
    model: Literal["constant", "composition_polynomial"] = "constant",
    poly: tuple[float, ...] = _DEFAULT_POLY,
    h0_hz: float = _H0,
) -> dict[str, Any]:
    x = min(1.0, max(0.0, float(x_solute)))
    if model == "constant":
        return {
            "nu_Hz": h0_hz,
            "model": "constant",
            "x_solute": x,
            "temperature_K": temperature_K,
            "note": "Γ₀ = 10¹³ Hz — inadequate for CSA sluggish diffusion (Huang 2023).",
        }
    # f(x) = Σ a_k x^k ; mild T softening (~linear) for HEA-style extension
    f = 0.0
    xp = 1.0
    for a in poly:
        f += a * xp
        xp *= x
    t_fac = 1.0 + 2.5e-4 * (float(temperature_K) - 300.0)
    nu = h0_hz * max(f, 0.05) * max(t_fac, 0.2)
    return {
        "nu_Hz": nu,
        "model": "composition_polynomial",
        "x_solute": x,
        "temperature_K": temperature_K,
        "poly": list(poly),
        "note": "Aegis default polynomial — replace with paper/user coefficients for publication.",
    }
