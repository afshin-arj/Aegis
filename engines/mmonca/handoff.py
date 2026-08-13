"""Build MMonCa comparison objects from cascade defects + optional DXA."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _cluster_points(points: list[dict[str, Any]], cutoff: float) -> list[list[dict[str, Any]]]:
    remaining = list(points)
    clusters: list[list[dict[str, Any]]] = []
    while remaining:
        seed = remaining.pop(0)
        group = [seed]
        changed = True
        while changed:
            changed = False
            nxt: list[dict[str, Any]] = []
            for p in remaining:
                if any(
                    (p["x"] - q["x"]) ** 2 + (p["y"] - q["y"]) ** 2 + (p["z"] - q["z"]) ** 2
                    <= cutoff * cutoff
                    for q in group
                ):
                    group.append(p)
                    changed = True
                else:
                    nxt.append(p)
            remaining = nxt
        clusters.append(group)
    return clusters


def collect_okmc_objects(job_dir: Path, *, cluster_cutoff_A: float = 3.5) -> dict[str, Any]:
    defects: dict[str, Any] = {}
    if (job_dir / "defects.json").exists():
        try:
            defects = json.loads((job_dir / "defects.json").read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            defects = {}
    points = list(defects.get("points") or [])
    vac = [p for p in points if p.get("kind") == "vacancy"]
    sia = [p for p in points if p.get("kind") in ("interstitial", "displaced")]
    vac_cl = _cluster_points(vac, cluster_cutoff_A)
    sia_cl = _cluster_points(sia, cluster_cutoff_A)

    def _obj(kind: str, group: list[dict[str, Any]], idx: int) -> dict[str, Any]:
        n = len(group)
        cx = sum(float(p["x"]) for p in group) / n
        cy = sum(float(p["y"]) for p in group) / n
        cz = sum(float(p["z"]) for p in group) / n
        return {
            "id": f"{kind[0]}{idx}",
            "kind": kind,
            "size": n,
            "x": round(cx, 4),
            "y": round(cy, 4),
            "z": round(cz, 4),
        }

    objects = [_obj("vacancy_cluster", g, i) for i, g in enumerate(vac_cl, start=1)]
    objects += [_obj("sia_cluster", g, i) for i, g in enumerate(sia_cl, start=1)]

    dxa = {}
    dxa_path = job_dir / "dxa_summary.json"
    if dxa_path.exists():
        try:
            dxa = json.loads(dxa_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            dxa = {}
    loops = []
    for i, loop in enumerate(dxa.get("dislocation_loops") or dxa.get("loops") or [], start=1):
        if not isinstance(loop, dict):
            continue
        loops.append(
            {
                "id": f"dxa{i}",
                "kind": "dislocation_loop",
                "size": loop.get("n_segments") or loop.get("size") or 1,
                "burgers": loop.get("burgers"),
            }
        )
    objects.extend(loops)
    summary = defects.get("summary") or {}
    return {
        "format": "aegis-mmonca-objects-v2",
        "cluster_cutoff_A": cluster_cutoff_A,
        "n_vacancy_points": len(vac),
        "n_sia_points": len(sia),
        "n_objects": len(objects),
        "objects": objects,
        "scalar_summary": {
            "vacancies": int(summary.get("vacancies") or len(vac)),
            "interstitials": int(summary.get("interstitials") or len(sia)),
            "clusters": int(summary.get("clusters") or (len(vac_cl) + len(sia_cl))),
        },
        "dxa_attached": bool(dxa),
    }
