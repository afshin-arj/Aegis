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
    crystal: str = "bcc",
    lattice_c_A: float | None = None,
    structure_kind: str = "single_crystal",
) -> dict[str, Any]:
    """Lightweight defect proxy analysis from the last dump frame.

    Uses a Wigner–Seitz style occupancy on an ideal crystal grid built from
    the dump box. Teaching/engineering proxy — not a replacement for OVITO DXA.
    For surface mode, also computes fuzz / erosion proxies.
    """
    from lammps import crystal as crystal_reg

    a_ref = float(ws_lattice_A) if ws_lattice_A else float(lattice_A)
    cutoff = float(cluster_cutoff_A) if cluster_cutoff_A is not None else 0.9 * a_ref
    cry = crystal_reg.normalize_crystal(crystal)
    c_ref = float(lattice_c_A) if lattice_c_A else None
    poly = str(structure_kind).lower() in {"polycrystal", "polycrystal_void", "bicrystal"}
    sk = str(structure_kind).lower()
    voidish = sk in {"void", "void_lattice", "polycrystal_void"}
    nano_note = ""
    if voidish:
        nano_note = (
            "Ideal-lattice WS treats cavity volume as vacancies — interpret with care; "
            "prefer OVITO DXA for void structures."
        )
    elif sk in {"nanowire", "precipitate", "import", "bicrystal"}:
        nano_note = (
            f"structure_kind={sk}: WS assumes a perfect host lattice reference — "
            "surface / second-phase / grain atoms may appear as false defects."
        )

    dumps = _prefer_analysis_dumps(job_dir)
    if not dumps:
        summary = {
            "summary": {
                "n_atoms": 0,
                "vacancies": 0,
                "interstitials": 0,
                "clusters": 0,
                "note": "no dump files found",
                "method": "aegis-ws-proxy-v2",
                "crystal": cry,
            },
            "clusters": [],
            "points": [],
        }
        (job_dir / "defects.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
        return summary

    dump_path = dumps[-1]
    atoms, box, box_meta = _read_last_frame(dump_path)
    if box_meta.get("triclinic"):
        note = (
            "Dump frame has triclinic tilt (xy/xz/yz). Aegis WS uses an orthogonal box proxy — "
            "vacancy/SIA counts for WC/hex or sheared cells are approximate; prefer OVITO."
        )
        nano_note = f"{nano_note} {note}".strip() if nano_note else note

    if not atoms:
        empty = {
            "summary": {
                "n_atoms": 0,
                "vacancies": 0,
                "interstitials": 0,
                "clusters": 0,
                "dump": dump_path.name,
                "method": "aegis-ws-proxy-v2",
                "crystal": cry,
            },
            "clusters": [],
            "points": [],
        }
        (job_dir / "defects.json").write_text(json.dumps(empty, indent=2), encoding="utf-8")
        return empty

    origin = (
        float(box_meta.get("xlo") or 0.0),
        float(box_meta.get("ylo") or 0.0),
        float(box_meta.get("zlo") or 0.0),
    )
    # Axis-aligned WS grid — non-100 / prism orients are approximate
    orient = "100"
    rp_path = job_dir / "run_params.json"
    if rp_path.exists():
        try:
            orient = str(json.loads(rp_path.read_text(encoding="utf-8")).get("crystal_orient") or "100")
        except Exception:  # noqa: BLE001
            orient = "100"
    if orient.lower() not in {"100", "basal", ""}:
        note = (
            f"crystal_orient={orient}: WS ideal sites are axis-aligned (not re-oriented) — "
            "V/SIA counts are approximate; prefer OVITO DXA."
        )
        nano_note = f"{nano_note} {note}".strip() if nano_note else note
    sites_z_max: float | None = None
    sites = crystal_reg.ideal_sites(box, cry, a_ref, c=c_ref, z_max=None, origin=origin)
    run_mode = (mode or "").lower()
    if run_mode in {"surface", "implant"}:
        # Vacuum slab must not be counted as vacancies. Clip to substrate height —
        # NOT max(final-frame z), which includes beam ions and sputtered atoms.
        sites_z_max = _substrate_z_max(
            job_dir,
            a_ref=a_ref,
            c_ref=c_ref,
            cry=cry,
            origin_z=origin[2],
        )
        if sites_z_max is not None:
            sites = crystal_reg.ideal_sites(
                box, cry, a_ref, c=c_ref, z_max=sites_z_max, origin=origin
            )

    if not sites:
        empty_sites = {
            "summary": {
                "n_atoms": len(atoms),
                "n_sites": 0,
                "vacancies": 0,
                "interstitials": len(atoms),
                "clusters": 0,
                "dump": dump_path.name,
                "ws_lattice_A": a_ref,
                "method": "aegis-ws-proxy-v2",
                "crystal": cry,
                "note": "no ideal lattice sites generated for this box/crystal — treat atoms as interstitial proxies",
            },
            "clusters": [],
            "points": [{**a, "kind": "interstitial"} for a in atoms[:5000]],
        }
        (job_dir / "defects.json").write_text(json.dumps(empty_sites, indent=2), encoding="utf-8")
        return empty_sites

    interstitial_pts: list[dict[str, Any]] = []
    # Spatial hash for nearest-site lookup (avoids O(N_atoms × N_sites))
    site_index = _build_site_index(sites, cell=max(a_ref * 0.75, 1.0))
    analysis_sampled = False
    atom_budget = 250_000
    atoms_use = atoms
    sites_use = sites
    occupied = [False] * len(sites)
    sample_bounds: tuple[float, float, float, float, float, float] | None = None
    if len(atoms) > atom_budget:
        # Spatial sub-box (not atom stride): keeps Frenkel balance (V ≈ SIA).
        # Striding atoms while keeping all sites made almost every site look vacant.
        xs = [float(a["x"]) for a in atoms]
        ys = [float(a["y"]) for a in atoms]
        zs = [float(a["z"]) for a in atoms]
        xmin, xmax = min(xs), max(xs)
        ymin, ymax = min(ys), max(ys)
        zmin, zmax = min(zs), max(zs)
        # Shrink from the low corner until ≈atom_budget atoms remain
        frac = max(0.2, min(1.0, (atom_budget / max(len(atoms), 1)) ** (1.0 / 3.0)))
        x0, y0, z0 = xmin, ymin, zmin
        x1 = xmin + (xmax - xmin) * frac
        y1 = ymin + (ymax - ymin) * frac
        z1 = zmin + (zmax - zmin) * frac
        atoms_use = [
            a
            for a in atoms
            if x0 <= float(a["x"]) <= x1
            and y0 <= float(a["y"]) <= y1
            and z0 <= float(a["z"]) <= z1
        ]
        if len(atoms_use) < max(1000, atom_budget // 10):
            # Degenerate box — fall back to first N atoms + sites near them only
            atoms_use = atoms[:atom_budget]
            pad = max(a_ref * 2.0, 1.0)
            near_sites: list[tuple[float, float, float]] = []
            for a in atoms_use:
                ax, ay, az = float(a["x"]), float(a["y"]), float(a["z"])
                for s in sites:
                    if (ax - s[0]) ** 2 + (ay - s[1]) ** 2 + (az - s[2]) ** 2 <= (pad * pad):
                        near_sites.append(s)
            # Unique by rounded coords
            seen: set[tuple[float, float, float]] = set()
            sites_use = []
            for s in near_sites:
                key = (round(s[0], 4), round(s[1], 4), round(s[2], 4))
                if key not in seen:
                    seen.add(key)
                    sites_use.append(s)
            sample_bounds = None
        else:
            sites_use = [
                s
                for s in sites
                if x0 <= s[0] <= x1 and y0 <= s[1] <= y1 and z0 <= s[2] <= z1
            ]
            sample_bounds = (x0, x1, y0, y1, z0, z1)
        if not sites_use:
            # Avoid classifying every atom as SIA when the crop missed the lattice
            sites_use = sites
            atoms_use = atoms[:atom_budget]
            sample_bounds = None
            nano_note = (
                f"{nano_note} Spatial crop found no lattice sites — fell back to first "
                f"{len(atoms_use)} atoms on the full site grid."
            ).strip()
        occupied = [False] * len(sites_use)
        site_index = _build_site_index(sites_use, cell=max(a_ref * 0.75, 1.0))
        analysis_sampled = True
        nano_note = (
            f"{nano_note} Analysis used a spatial sub-volume "
            f"({len(atoms_use)}/{len(atoms)} atoms, {len(sites_use)}/{len(sites)} sites; "
            f"budget {atom_budget}) to preserve Frenkel balance."
        ).strip()

    for atom in atoms_use:
        best_i, best_d2 = _nearest_site(atom, sites_use, site_index, cell=max(a_ref * 0.75, 1.0))
        if best_i < 0:
            interstitial_pts.append({**atom, "kind": "interstitial"})
            continue
        if occupied[best_i]:
            # True WS interstitial: nearest site already claimed by another atom
            interstitial_pts.append({**atom, "kind": "interstitial"})
        else:
            occupied[best_i] = True
            # Do NOT count thermal / mildly displaced on-site atoms as interstitials —
            # that inflated SIA counts to ~N_atoms after finite-T cascades.

    vacancies = [
        {"id": i, "x": s[0], "y": s[1], "z": s[2], "kind": "vacancy"}
        for i, (s, occ) in enumerate(zip(sites_use, occupied))
        if not occ
    ]

    clusters = _cluster_points(interstitial_pts, cutoff)
    points = vacancies + interstitial_pts
    note = ""
    if poly:
        note = "Polycrystal WS uses a single global lattice — approximate; prefer OVITO DXA per grain."
    if nano_note:
        note = f"{note} {nano_note}".strip() if note else nano_note
    n_vac = len(vacancies)
    n_sia = len(interstitial_pts)
    if len(atoms_use) > 0 and (n_vac + n_sia) > 0.25 * len(atoms_use):
        melt = (
            f"High defect fraction (V={n_vac}, SIA={n_sia} on {len(atoms_use)} atoms) — "
            "cell may be too small for this PKA energy, or the cascade still hot; enlarge cell / lower E."
        )
        note = f"{note} {melt}".strip() if note else melt
    summary: dict[str, Any] = {
        "summary": {
            "n_atoms": len(atoms),
            "n_atoms_analyzed": len(atoms_use),
            "n_sites": len(sites),
            "n_sites_analyzed": len(sites_use),
            "analysis_sampled": analysis_sampled,
            "vacancies": n_vac,
            "interstitials": n_sia,
            "clusters": len(clusters),
            "dump": dump_path.name,
            "ws_lattice_A": a_ref,
            "ws_lattice_c_A": c_ref,
            "cluster_cutoff_A": cutoff,
            "method": "aegis-ws-proxy-v2",
            "crystal": cry,
            "structure_kind": structure_kind,
            "mode": run_mode or "cascade",
            "triclinic_proxy": bool(box_meta.get("triclinic")),
            "note": note,
            "hardening_proxy": {
                "dbh_Nd_sqrt": (len(interstitial_pts) * max(len(clusters), 1)) ** 0.5,
                "note": "Placeholder DBH/FKH-style scalar — not calibrated.",
            },
        },
        "clusters": clusters,
        "points": points[:5000],
    }

    # WC hex: species-aware sublattice vacancy proxies when type_symbols available
    if cry == "hex":
        type_symbols: list[str] = []
        meta_path = job_dir / "structure_meta.json"
        if meta_path.exists():
            try:
                ts = json.loads(meta_path.read_text(encoding="utf-8")).get("type_symbols")
                if isinstance(ts, list):
                    type_symbols = [str(s) for s in ts]
            except Exception:  # noqa: BLE001
                type_symbols = []
        sub = crystal_reg.ideal_sites_sublattice(
            box, cry, a_ref, c=c_ref, z_max=sites_z_max, origin=origin
        )
        sub_stats: dict[str, Any] = {}
        species_aware = False
        for label, sub_sites in sub.items():
            if not sub_sites:
                sub_stats[label] = {"n_sites": 0, "vacancies_proxy": 0}
                continue
            if sample_bounds is not None:
                x0, x1, y0, y1, z0, z1 = sample_bounds
                sub_sites = [
                    s
                    for s in sub_sites
                    if x0 <= s[0] <= x1 and y0 <= s[1] <= y1 and z0 <= s[2] <= z1
                ]
                if not sub_sites:
                    sub_stats[label] = {"n_sites": 0, "vacancies_proxy": 0, "sampled": True}
                    continue
            allowed_types: set[int] | None = None
            if type_symbols:
                want = "c" if label.lower().startswith("c") else None
                if want == "c":
                    allowed_types = {
                        i + 1 for i, s in enumerate(type_symbols) if str(s).lower() == "c"
                    }
                else:
                    allowed_types = {
                        i + 1 for i, s in enumerate(type_symbols) if str(s).lower() != "c"
                    }
                if allowed_types:
                    species_aware = True
            sub_index = _build_site_index(sub_sites, cell=max(a_ref * 0.75, 1.0))
            sub_occ = [False] * len(sub_sites)
            for atom in atoms_use:
                if allowed_types is not None and int(atom.get("type") or 0) not in allowed_types:
                    continue
                best_i, best_d2 = _nearest_site(
                    atom, sub_sites, sub_index, cell=max(a_ref * 0.75, 1.0)
                )
                if best_i >= 0 and not sub_occ[best_i] and best_d2 <= (0.35 * a_ref) ** 2:
                    sub_occ[best_i] = True
            sub_stats[label] = {
                "n_sites": len(sub_sites),
                "vacancies_proxy": sum(1 for o in sub_occ if not o),
                "sampled": analysis_sampled,
            }
        summary["summary"]["sublattice"] = sub_stats
        summary["summary"]["sublattice_species_aware"] = species_aware
        if not species_aware:
            summary["summary"]["note"] = (
                f"{summary['summary'].get('note') or ''} WC sublattice vacancies are a "
                "species-blind geometric proxy unless type_symbols are present — not calibrated."
            ).strip()
        else:
            summary["summary"]["note"] = (
                f"{summary['summary'].get('note') or ''} WC sublattice WS uses type_symbols "
                "to match metal↔metal and C↔C sites (engineering proxy)."
            ).strip()

    if run_mode in {"surface", "implant"}:
        surface = analyze_surface_metrics(job_dir, lattice_A=a_ref, ion_type_hint=None)
        if surface:
            summary["surface"] = surface
            summary["summary"]["surface"] = surface.get("summary")
            (job_dir / "surface_metrics.json").write_text(json.dumps(surface, indent=2), encoding="utf-8")

    (job_dir / "defects.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def _substrate_z_max(
    job_dir: Path,
    *,
    a_ref: float,
    c_ref: float | None,
    cry: str,
    origin_z: float,
) -> float | None:
    """Upper z for WS sites that excludes the vacuum / beam region.

    Prefer host max-z from ``dump.initial`` (pre-beam). Fall back to
    ``nz * layer`` from run_params when the initial dump is missing.
    """
    from lammps import crystal as crystal_reg

    initial_path = job_dir / "dump.initial.lammpstrj"
    if initial_path.exists():
        before, _, _ = _read_last_frame(initial_path)
        if before:
            return max(float(a["z"]) for a in before) + 0.25 * a_ref

    layer = a_ref
    if cry in {"hcp", "hex"}:
        layer = float(c_ref) if c_ref and c_ref > 0 else a_ref * (1.633 if cry == "hcp" else 0.976)
    nz = None
    rp_path = job_dir / "run_params.json"
    if rp_path.exists():
        try:
            rp = json.loads(rp_path.read_text(encoding="utf-8"))
            nz = int(rp.get("nz") or 0) or None
        except Exception:  # noqa: BLE001
            nz = None
    if nz and nz > 0:
        return float(origin_z) + float(nz) * layer + 0.25 * a_ref
    # Last resort: densest lower slab from material.json lattice only
    mat_path = job_dir / "material.json"
    if mat_path.exists() and nz is None:
        try:
            mat = json.loads(mat_path.read_text(encoding="utf-8"))
            if cry in {"hcp", "hex"}:
                c_mat = crystal_reg.resolve_c_A(mat, cry)
                if c_mat and c_mat > 0:
                    layer = float(c_mat)
        except Exception:  # noqa: BLE001
            pass
    return None


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

    before, _, _ = _read_last_frame(initial_path)
    after, box, _ = _read_last_frame(after_path)
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
    # Implanted species: hetero types first; self-ions via ids created after dump.initial
    before_types = {a["type"] for a in before}
    hetero = [a for a in after if a["type"] not in before_types]
    max_id0 = max((int(a.get("id") or 0) for a in before), default=0)
    new_by_id = [a for a in after if int(a.get("id") or 0) > max_id0]
    ions = hetero
    if not ions and ion_type_hint:
        ions = [a for a in after if a["type"] == ion_type_hint]
    if not ions:
        ions = new_by_id
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


def _read_last_frame(
    path: Path,
) -> tuple[list[dict[str, Any]], tuple[float, float, float], dict[str, Any]]:
    text = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    starts = [i for i, line in enumerate(text) if line.startswith("ITEM: TIMESTEP")]
    if not starts:
        return [], (0, 0, 0), {}
    i = starts[-1]
    while i < len(text) and not text[i].startswith("ITEM: NUMBER OF ATOMS"):
        i += 1
    n = int(text[i + 1])
    while i < len(text) and not text[i].startswith("ITEM: BOX BOUNDS"):
        i += 1
    bounds_hdr = text[i]
    triclinic = "xy" in bounds_hdr.lower() or "xz" in bounds_hdr.lower() or "yz" in bounds_hdr.lower()
    # Always take first two tokens as lo/hi; ignore tilt factors for orthogonal proxy
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
        return [], (xhi - xlo, yhi - ylo, zhi - zlo), {"triclinic": triclinic, "xlo": xlo, "ylo": ylo, "zlo": zlo}
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
    return atoms, (lx, ly, lz), {
        "triclinic": triclinic,
        "xlo": xlo,
        "ylo": ylo,
        "zlo": zlo,
        "xhi": xhi,
        "yhi": yhi,
        "zhi": zhi,
    }


def _build_site_index(
    sites: list[tuple[float, float, float]], *, cell: float
) -> dict[tuple[int, int, int], list[int]]:
    index: dict[tuple[int, int, int], list[int]] = {}
    inv = 1.0 / max(cell, 1e-9)
    for i, (x, y, z) in enumerate(sites):
        key = (int(x * inv), int(y * inv), int(z * inv))
        index.setdefault(key, []).append(i)
    return index


def _nearest_site(
    atom: dict[str, Any],
    sites: list[tuple[float, float, float]],
    index: dict[tuple[int, int, int], list[int]],
    *,
    cell: float,
) -> tuple[int, float]:
    if not sites:
        return -1, 1e99
    inv = 1.0 / max(cell, 1e-9)
    ax, ay, az = float(atom["x"]), float(atom["y"]), float(atom["z"])
    cx, cy, cz = int(ax * inv), int(ay * inv), int(az * inv)
    best_i, best_d2 = -1, 1e99
    for dx in (-1, 0, 1):
        for dy in (-1, 0, 1):
            for dz in (-1, 0, 1):
                for i in index.get((cx + dx, cy + dy, cz + dz), ()):
                    s = sites[i]
                    d2 = (ax - s[0]) ** 2 + (ay - s[1]) ** 2 + (az - s[2]) ** 2
                    if d2 < best_d2:
                        best_d2 = d2
                        best_i = i
    if best_i < 0:
        # Fallback rare empty neighborhood
        for i, s in enumerate(sites):
            d2 = (ax - s[0]) ** 2 + (ay - s[1]) ** 2 + (az - s[2]) ** 2
            if d2 < best_d2:
                best_d2 = d2
                best_i = i
    return best_i, best_d2


def _bcc_sites(
    box: tuple[float, float, float], a: float, *, z_max: float | None = None
) -> list[tuple[float, float, float]]:
    """Backward-compatible alias — prefer crystal.ideal_sites."""
    from lammps import crystal as crystal_reg

    return crystal_reg.ideal_sites(box, "bcc", a, z_max=z_max)


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
