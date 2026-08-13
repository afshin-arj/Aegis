"""Local atomic configuration (LAC) extractor — Huang et al. 2023 §2.

Four FCC neighbor shells with species codes (0 = vacancy). Default mapping
follows the paper (Ni=1, Fe=2); other hosts get sequential codes from 3.
"""

from __future__ import annotations

from typing import Any

# FCC neighbor shells in lattice units (a0)
FCC_SHELLS: tuple[tuple[tuple[int, int, int], ...], ...] = (
    (  # 1st: 12
        (1, 1, 0),
        (1, -1, 0),
        (-1, 1, 0),
        (-1, -1, 0),
        (1, 0, 1),
        (1, 0, -1),
        (-1, 0, 1),
        (-1, 0, -1),
        (0, 1, 1),
        (0, 1, -1),
        (0, -1, 1),
        (0, -1, -1),
    ),
    (  # 2nd: 6
        (2, 0, 0),
        (-2, 0, 0),
        (0, 2, 0),
        (0, -2, 0),
        (0, 0, 2),
        (0, 0, -2),
    ),
    (  # 3rd: 24
        (2, 1, 1),
        (2, 1, -1),
        (2, -1, 1),
        (2, -1, -1),
        (-2, 1, 1),
        (-2, 1, -1),
        (-2, -1, 1),
        (-2, -1, -1),
        (1, 2, 1),
        (1, 2, -1),
        (-1, 2, 1),
        (-1, 2, -1),
        (1, -2, 1),
        (1, -2, -1),
        (-1, -2, 1),
        (-1, -2, -1),
        (1, 1, 2),
        (1, -1, 2),
        (-1, 1, 2),
        (-1, -1, 2),
        (1, 1, -2),
        (1, -1, -2),
        (-1, 1, -2),
        (-1, -1, -2),
    ),
    (  # 4th: 12
        (2, 2, 0),
        (2, -2, 0),
        (-2, 2, 0),
        (-2, -2, 0),
        (2, 0, 2),
        (2, 0, -2),
        (-2, 0, 2),
        (-2, 0, -2),
        (0, 2, 2),
        (0, 2, -2),
        (0, -2, 2),
        (0, -2, -2),
    ),
)

# w1 > w2 > w3 > w4 (paper: nearer shells dominate the ANN input)
DEFAULT_SHELL_WEIGHTS = (1.0, 0.5, 0.25, 0.125)


def default_species_codes(symbols: list[str]) -> dict[str, int]:
    codes: dict[str, int] = {"V": 0, "Vac": 0}
    preferred = {"Ni": 1, "Fe": 2}
    nxt = 3
    for sym in symbols:
        if not sym or sym in codes:
            continue
        if sym in preferred:
            codes[sym] = preferred[sym]
        else:
            codes[sym] = nxt
            nxt += 1
    return codes


def extract_lac(
    occupancy: dict[tuple[int, int, int], int],
    site: tuple[int, int, int],
    *,
    nx: int,
    ny: int,
    nz: int,
    weights: tuple[float, ...] = DEFAULT_SHELL_WEIGHTS,
) -> dict[str, Any]:
    """Return per-shell neighbor codes and a weighted histogram vector."""
    shells: list[list[int]] = []
    hist: list[float] = []
    sx, sy, sz = site
    for sh, offs in enumerate(FCC_SHELLS):
        codes: list[int] = []
        for dx, dy, dz in offs:
            key = ((sx + dx) % nx, (sy + dy) % ny, (sz + dz) % nz)
            codes.append(int(occupancy.get(key, 0)))
        shells.append(codes)
        w = weights[sh] if sh < len(weights) else 0.0
        # Histogram over codes 0..4 (vacancy + up to 4 hosts)
        bins = [0.0] * 5
        for c in codes:
            if 0 <= c < 5:
                bins[c] += 1.0
        hist.extend(v * w for v in bins)
    return {
        "site": list(site),
        "shells": shells,
        "weighted_vector": hist,
        "n_neighbors": [len(s) for s in shells],
    }
