"""Lightweight polycrystal grain assignment for Aegis LAMMPS inputs.

Builds a Voronoi-like grain map over an nx×ny×nz lattice cell and emits
helper files. Full Atomsk pipelines are optional when Atomsk is installed.
"""

from __future__ import annotations

import json
import math
import random
from pathlib import Path
from typing import Any


def build_polycrystal_meta(
    job_dir: Path,
    *,
    nx: int,
    ny: int,
    nz: int,
    n_grains: int,
    seed: int,
    texture: str = "random",
    crystal: str = "bcc",
    a: float = 3.165,
) -> dict[str, Any]:
    """Write polycrystal_meta.json with grain seeds and orientations."""
    rng = random.Random(int(seed))
    n_grains = max(2, min(int(n_grains), 64))
    seeds = [
        (rng.random() * nx, rng.random() * ny, rng.random() * nz) for _ in range(n_grains)
    ]
    grains = []
    for i, (sx, sy, sz) in enumerate(seeds):
        if texture == "fiber":
            # Fiber: rotate about z
            angle = rng.random() * 2 * math.pi
            orient = {
                "euler_zxz_deg": [0.0, 0.0, math.degrees(angle)],
                "note": "fiber texture about z",
            }
        else:
            orient = {
                "euler_zxz_deg": [
                    rng.random() * 360.0,
                    rng.random() * 180.0,
                    rng.random() * 360.0,
                ],
                "note": "random orientation",
            }
        grains.append({"id": i, "seed_lattice": [sx, sy, sz], "orientation": orient})

    meta = {
        "method": "aegis-voronoi-seeds-v1",
        "crystal": crystal,
        "lattice_constant_A": a,
        "box_lattice": [nx, ny, nz],
        "n_grains": n_grains,
        "texture": texture,
        "seed": seed,
        "grains": grains,
        "note": (
            "Grain seeds for OVITO / Atomsk. Aegis single-crystal lattice fill is used "
            "unless Atomsk rebuilds the cell; WS analysis on polycrystals is approximate."
        ),
    }
    path = job_dir / "polycrystal_meta.json"
    path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def polycrystal_lammps_comment(meta: dict[str, Any]) -> str:
    n = meta.get("n_grains", 0)
    return (
        f"# Polycrystal: {n} Voronoi grain seeds (see polycrystal_meta.json). "
        "Production GB structures: rebuild with Atomsk when available."
    )


def assign_grain(x: float, y: float, z: float, seeds: list[tuple[float, float, float]]) -> int:
    best_i, best_d = 0, float("inf")
    for i, (sx, sy, sz) in enumerate(seeds):
        d = (x - sx) ** 2 + (y - sy) ** 2 + (z - sz) ** 2
        if d < best_d:
            best_d, best_i = d, i
    return best_i
