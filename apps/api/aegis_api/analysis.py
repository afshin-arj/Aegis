from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any


def _prefer_analysis_dumps(job_dir: Path) -> list[Path]:
    """Prefer damage trajectory dumps over the pre-damage initial dump.

    Excludes ``dump.stage.*`` bookmarks (written at stage *start*) so analysis
    uses the last cascade/implant/surface frame, not a mid-run marker.
    """
    candidates: list[Path] = []
    for pattern in (
        "dump.surface.*.lammpstrj",
        "dump.interstitial.*.lammpstrj",
        "dump.cascade.*.lammpstrj",
        "dump.implant.*.lammpstrj",
        "dump.*.lammpstrj",
    ):
        candidates.extend(job_dir.glob(pattern))
    uniq = {p.resolve(): p for p in candidates}.values()
    non_initial = [
        p
        for p in uniq
        if "initial" not in p.name.lower() and not p.name.startswith("dump.stage")
    ]

    def _sort_key(p: Path) -> tuple[int, str]:
        m = re.search(r"(\d+)\.lammpstrj$", p.name)
        if m:
            return (int(m.group(1)), p.name)
        return (10**12, p.name)

    ordered = sorted(non_initial, key=_sort_key)
    return ordered or sorted(uniq, key=lambda p: p.name)


def analyze_job_dir(
    job_dir: Path,
    lattice_A: float = 3.165,
    *,
    cluster_cutoff_A: float | None = None,
    ws_lattice_A: float | None = None,
    mode: str | None = None,
) -> dict[str, Any]:
    """Lightweight defect proxy analysis from the last dump frame.

    Uses a simple Wigner–Seitz style occupancy on an ideal BCC grid built from
    the dump box. Teaching/engineering proxy — not a replacement for OVITO.
    For surface mode, also computes fuzz / erosion proxies.
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

    sites = _bcc_sites(box, a_ref, z_max=None)
    run_mode = (mode or "").lower()
    if run_mode == "surface":
        # Vacuum slab must not be counted as vacancies — limit WS grid to substrate height.
        # Heuristic: host atoms cluster below vacuum; use 75th percentile of z as slab top fallback
        # via box fraction when params unknown. Prefer occupied z span of densest lower region.
        zs = sorted(a["z"] for a in atoms)
        if zs:
            # Assume vacuum is the empty upper portion; use max occupied z + small pad as site limit
            z_max = max(zs) + 0.25 * a_ref
            sites = _bcc_sites(box, a_ref, z_max=z_max)

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
    summary: dict[str, Any] = {
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
            "mode": run_mode or "cascade",
            "hardening_proxy": {
                "dbh_Nd_sqrt": (len(interstitial_pts) * max(len(clusters), 1)) ** 0.5,
                "note": "Placeholder DBH/FKH-style scalar — not calibrated.",
            },
        },
        "clusters": clusters,
        "points": points[:5000],
    }

    if run_mode == "surface":
        surface = analyze_surface_metrics(job_dir, lattice_A=a_ref, ion_type_hint=None)
        if surface:
            summary["surface"] = surface
            summary["summary"]["surface"] = surface.get("summary")
            (job_dir / "surface_metrics.json").write_text(json.dumps(surface, indent=2), encoding="utf-8")

    (job_dir / "defects.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def analyze_surface_metrics(
    job_dir: Path,
    *,
    lattice_A: float = 3.165,
    ion_type_hint: int | None = None,
) -> dict[str, Any] | None:
    """Compare dump.initial vs last surface/implant dump for fuzz / erosion proxies.

    Metrics are engineering proxies for UI — not calibrated tokamak erosion yields.
    """
    initial_path = job_dir / "dump.initial.lammpstrj"
    if not initial_path.exists():
        return None
    finals = _prefer_analysis_dumps(job_dir)
    if not finals:
        return None
    # Need a non-initial dump for after
    after_path = finals[-1]
    if after_path.resolve() == initial_path.resolve() and len(finals) == 1:
        # Only initial exists
        return None

    before, _ = _read_last_frame(initial_path)
    after, box = _read_last_frame(after_path)
    if not before or not after:
        return None

    # Host atoms: lowest type id present in initial (typically 1)
    host_type = min(a["type"] for a in before)
    before_host = [a for a in before if a["type"] == host_type]
    after_host = [a for a in after if a["type"] == host_type]
    if not before_host or not after_host:
        return None

    z0 = max(a["z"] for a in before_host)
    z1 = max(a["z"] for a in after_host)
    mean_z0 = sum(a["z"] for a in before_host) / len(before_host)
    mean_z1 = sum(a["z"] for a in after_host) / len(after_host)
    fuzz_tol = 0.4 * lattice_A
    fuzz_atoms = [a for a in after_host if a["z"] > z0 + fuzz_tol]
    # Inward recession of the mean host surface (positive => net erosion/recession)
    recession_A = mean_z0 - mean_z1
    # Implanted species: types not in initial host set
    before_types = {a["type"] for a in before}
    ions = [a for a in after if a["type"] not in before_types or (ion_type_hint and a["type"] == ion_type_hint)]
    if not ions:
        # Fallback: highest type id
        max_type = max(a["type"] for a in after)
        if max_type != host_type:
            ions = [a for a in after if a["type"] == max_type]
    depths = [max(0.0, z0 - a["z"]) for a in ions]
    mean_depth = sum(depths) / len(depths) if depths else 0.0
    max_depth = max(depths) if depths else 0.0

    # Roughness proxy: stddev of top-layer host z (top 20%)
    after_sorted = sorted(after_host, key=lambda a: a["z"], reverse=True)
    top_n = max(1, len(after_sorted) // 5)
    top = after_sorted[:top_n]
    top_mean = sum(a["z"] for a in top) / len(top)
    roughness = (sum((a["z"] - top_mean) ** 2 for a in top) / len(top)) ** 0.5

    out = {
        "format": "aegis-surface-metrics-v1",
        "method": "aegis-surface-proxy-v1",
        "note": "Engineering proxy for fuzz/erosion — not calibrated sputtering yields.",
        "dumps": {"before": initial_path.name, "after": after_path.name},
        "box_A": {"lx": box[0], "ly": box[1], "lz": box[2]},
        "summary": {
            "z_surface_before_A": round(z0, 4),
            "z_surface_after_A": round(z1, 4),
            "mean_host_recession_A": round(recession_A, 4),
            "fuzz_atom_count": len(fuzz_atoms),
            "fuzz_height_max_A": round(max((a["z"] - z0 for a in fuzz_atoms), default=0.0), 4),
            "surface_roughness_proxy_A": round(roughness, 4),
            "implanted_count": len(ions),
            "mean_implant_depth_A": round(mean_depth, 4),
            "max_implant_depth_A": round(max_depth, 4),
            "n_host_before": len(before_host),
            "n_host_after": len(after_host),
        },
        "fuzz_points": [{**a, "kind": "fuzz"} for a in fuzz_atoms[:2000]],
    }
    return out


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
    # Prefer unwrapped/cartesian; fall back to scaled xs/ys/zs
    x_key = "x" if "x" in idx else "xu" if "xu" in idx else "xs" if "xs" in idx else None
    y_key = "y" if "y" in idx else "yu" if "yu" in idx else "ys" if "ys" in idx else None
    z_key = "z" if "z" in idx else "zu" if "zu" in idx else "zs" if "zs" in idx else None
    if x_key is None or y_key is None or z_key is None:
        return [], (xhi - xlo, yhi - ylo, zhi - zlo)
    lx, ly, lz = xhi - xlo, yhi - ylo, zhi - zlo
    scaled = x_key == "xs"
    atoms = []
    for line in text[i + 1 : i + 1 + n]:
        parts = line.split()
        x = float(parts[idx[x_key]])
        y = float(parts[idx[y_key]])
        z = float(parts[idx[z_key]])
        if scaled:
            x = xlo + x * lx
            y = ylo + y * ly
            z = zlo + z * lz
        atoms.append(
            {
                "id": int(parts[idx.get("id", 0)]),
                "type": int(parts[idx.get("type", 1)]),
                "x": x,
                "y": y,
                "z": z,
            }
        )
    return atoms, (lx, ly, lz)


def _bcc_sites(
    box: tuple[float, float, float], a: float, *, z_max: float | None = None
) -> list[tuple[float, float, float]]:
    lx, ly, lz = box
    nx = max(int(round(lx / a)), 1)
    ny = max(int(round(ly / a)), 1)
    nz = max(int(round(lz / a)), 1)
    sites: list[tuple[float, float, float]] = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                for sx, sy, sz in ((0.0, 0.0, 0.0), (a / 2, a / 2, a / 2)):
                    x, y, z = i * a + sx, j * a + sy, k * a + sz
                    if z_max is not None and z > z_max:
                        continue
                    sites.append((x, y, z))
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
