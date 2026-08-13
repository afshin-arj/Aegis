"""Warren–Cowley short-range order on the first four FCC shells."""

from __future__ import annotations

from typing import Any

from ml_kmc.lac import FCC_SHELLS


def warren_cowley(
    occupancy: dict[tuple[int, int, int], int],
    *,
    nx: int,
    ny: int,
    nz: int,
    code_a: int,
    code_b: int,
) -> dict[str, Any]:
    """α_n = 1 − P_AB^{(n)} / (c_A + c_B wait: P_AB / (2 c_A c_B) for unlike pairs).

    Vacancy sites (code 0) are skipped. Random solid solution → α ≈ 0;
    clustering → α > 0; ordering → α < 0.
    """
    sites = [k for k, c in occupancy.items() if c != 0]
    if not sites:
        return {"alpha": [None, None, None, None], "c_a": 0.0, "c_b": 0.0, "n_sites": 0}
    n_a = sum(1 for k in sites if occupancy[k] == code_a)
    n_b = sum(1 for k in sites if occupancy[k] == code_b)
    n = len(sites)
    c_a = n_a / n
    c_b = n_b / n
    alphas: list[float | None] = []
    for offs in FCC_SHELLS:
        unlike = 0
        pairs = 0
        for sx, sy, sz in sites:
            for dx, dy, dz in offs:
                key = ((sx + dx) % nx, (sy + dy) % ny, (sz + dz) % nz)
                other = occupancy.get(key, 0)
                if other == 0:
                    continue
                pairs += 1
                here = occupancy[(sx, sy, sz)]
                if {here, other} == {code_a, code_b}:
                    unlike += 1
        if pairs == 0 or c_a <= 0 or c_b <= 0:
            alphas.append(None)
            continue
        p_ab = unlike / pairs
        denom = 2.0 * c_a * c_b
        alphas.append(round(1.0 - p_ab / denom, 6) if denom > 0 else None)
    return {
        "alpha": alphas,
        "c_a": round(c_a, 6),
        "c_b": round(c_b, 6),
        "n_sites": n,
        "structure_class_hint": (
            "ordered"
            if any(a is not None and a < -0.05 for a in alphas)
            else "clustered"
            if any(a is not None and a > 0.05 for a in alphas)
            else "random"
        ),
    }
