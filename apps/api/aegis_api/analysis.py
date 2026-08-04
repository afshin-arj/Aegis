from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def _prefer_analysis_dumps(job_dir: Path) -> list[Path]:
    """Prefer cascade/implant trajectory dumps over the pre-damage initial dump."""
    candidates: list[Path] = []
    for pattern in (
        "dump.cascade.*.lammpstrj",
        "dump.implant.*.lammpstrj",
        "dump.*.lammpstrj",
    ):
        candidates.extend(job_dir.glob(pattern))
    # Unique, exclude initial reference unless it is the only file
    uniq = sorted({p.resolve(): p for p in candidates}.values(), key=lambda p: p.name)
    non_initial = [p for p in uniq if "initial" not in p.name.lower()]
    return non_initial or uniq


def analyze_job_dir(
    job_dir: Path,
    lattice_A: float = 3.165,
    *,
    cluster_cutoff_A: float | None = None,
    ws_lattice_A: float | None = None,
) -> dict[str, Any]:
    """Lightweight defect proxy analysis from the last cascade/implant dump frame.

    Uses a simple Wigner–Seitz style occupancy on an ideal BCC grid built from
    the dump box. Teaching/engineering proxy — not a replacement for OVITO.
    """
    a_ref = float(ws_lattice_A) if ws_lattice_A else float(lattice_A)
    cutoff = float(cluster_cutoff_A) if cluster_cutoff_A is not None else 0.9 * a_ref

    dumps = _prefer_analysis_dumps(job_dir)
    if not dumps:
        summary = {
            "summary": {
                "n_atoms": 0,
                "vacancies": 0,
                "interstitials": 0,
                "clusters": 0,
                "note": "no dump files found",
                "method": "aegis-ws-proxy-v1",
            },
            "clusters": [],
            "points": [],
        }
        (job_dir / "defects.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    dump_path = dumps[-1]
    atoms, box = _read_last_frame(dump_path)
    if not atoms:
        empty = {
            "summary": {
                "n_atoms": 0,
                "vacancies": 0,
                "interstitials": 0,
                "clusters": 0,
                "dump": dump_path.name,
                "method": "aegis-ws-proxy-v1",
            },
            "clusters": [],
            "points": [],
        }
        (job_dir / "defects.json").write_text(json.dumps(empty, indent=2), encoding="utf-8")
        return empty

    sites = _bcc_sites(box, a_ref)
    occupied = [False] * len(sites)
    interstitial_pts: list[dict[str, Any]] = []
    for atom in atoms:
        best_i = 0
        best_d2 = 1e99
        for i, s in enumerate(sites):
            d2 = (atom["x"] - s[0]) ** 2 + (atom["y"] - s[1]) ** 2 + (atom["z"] - s[2]) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_i = i
        if occupied[best_i]:
            interstitial_pts.append({**atom, "kind": "interstitial"})
        else:
            occupied[best_i] = True
            if best_d2 > (0.3 * a_ref) ** 2:
                interstitial_pts.append({**atom, "kind": "displaced"})

    vacancies = [
        {"id": i, "x": s[0], "y": s[1], "z": s[2], "kind": "vacancy"}
        for i, (s, occ) in enumerate(zip(sites, occupied))
        if not occ
    ]

    clusters = _cluster_points(interstitial_pts, cutoff)
    points = vacancies + interstitial_pts
    summary = {
        "summary": {
            "n_atoms": len(atoms),
            "n_sites": len(sites),
            "vacancies": len(vacancies),
            "interstitials": len(interstitial_pts),
            "clusters": len(clusters),
            "dump": dump_path.name,
            "ws_lattice_A": a_ref,
            "cluster_cutoff_A": cutoff,
            "method": "aegis-ws-proxy-v1",
            "hardening_proxy": {
                "dbh_Nd_sqrt": (len(interstitial_pts) * max(len(clusters), 1)) ** 0.5,
                "note": "Placeholder DBH/FKH-style scalar — not calibrated.",
            },
        },
        "clusters": clusters,
        "points": points[:5000],
    }
    (job_dir / "defects.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _read_last_frame(path: Path) -> tuple[list[dict[str, Any]], tuple[float, float, float]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    starts = [i for i, line in enumerate(text) if line.startswith("ITEM: TIMESTEP")]
    if not starts:
        return [], (0, 0, 0)
    i = starts[-1]
    while i < len(text) and not text[i].startswith("ITEM: NUMBER OF ATOMS"):
        i += 1
    n = int(text[i + 1])
    while i < len(text) and not text[i].startswith("ITEM: BOX BOUNDS"):
        i += 1
    xlo, xhi = map(float, text[i + 1].split()[:2])
    ylo, yhi = map(float, text[i + 2].split()[:2])
    zlo, zhi = map(float, text[i + 3].split()[:2])
    while i < len(text) and not text[i].startswith("ITEM: ATOMS"):
        i += 1
    header = text[i].split()[2:]
    idx = {name: k for k, name in enumerate(header)}
    atoms = []
    for line in text[i + 1 : i + 1 + n]:
        parts = line.split()
        atoms.append(
            {
                "id": int(parts[idx.get("id", 0)]),
                "type": int(parts[idx.get("type", 1)]),
                "x": float(parts[idx["x"]]),
                "y": float(parts[idx["y"]]),
                "z": float(parts[idx["z"]]),
            }
        )
    return atoms, (xhi - xlo, yhi - ylo, zhi - zlo)


def _bcc_sites(box: tuple[float, float, float], a: float) -> list[tuple[float, float, float]]:
    lx, ly, lz = box
    nx = max(int(round(lx / a)), 1)
    ny = max(int(round(ly / a)), 1)
    nz = max(int(round(lz / a)), 1)
    sites: list[tuple[float, float, float]] = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                sites.append((i * a, j * a, k * a))
                sites.append((i * a + a / 2, j * a + a / 2, k * a + a / 2))
    return sites


def _cluster_points(points: list[dict[str, Any]], cutoff: float) -> list[dict[str, Any]]:
    n = len(points)
    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    c2 = cutoff * cutoff
    for i in range(n):
        for j in range(i + 1, n):
            dx = points[i]["x"] - points[j]["x"]
            dy = points[i]["y"] - points[j]["y"]
            dz = points[i]["z"] - points[j]["z"]
            if dx * dx + dy * dy + dz * dz <= c2:
                union(i, j)
    groups: dict[int, list[int]] = {}
    for i in range(n):
        groups.setdefault(find(i), []).append(i)
    return [{"id": gid, "size": len(idxs), "member_indices": idxs} for gid, idxs in groups.items()]
