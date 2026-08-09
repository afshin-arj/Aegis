"""ASE-based structure builders (voids, Voronoi polycrystal, bicrystal GB)."""

from __future__ import annotations

import math
import random
from pathlib import Path
from typing import Any

import numpy as np


def _host_symbol(material: dict[str, Any]) -> str:
    for c in material.get("composition") or []:
        if float(c.get("atomic_percent") or 0) > 0:
            return str(c.get("symbol") or "W")
    return "W"


def _crystal_name(material: dict[str, Any]) -> str:
    from lammps import crystal as crystal_reg

    return crystal_reg.normalize_crystal(str(material.get("crystal") or "bcc"))


def _ase_crystal(cry: str) -> str:
    return {"bcc": "bcc", "fcc": "fcc", "hcp": "hcp", "diamond": "diamond", "hex": "hcp"}.get(cry, "bcc")


def _make_bulk(material: dict[str, Any], nx: int, ny: int, nz: int):
    from ase.build import bulk

    sym = _host_symbol(material)
    cry = _crystal_name(material)
    a = float(material.get("lattice_constant_A") or 3.165)
    c = material.get("lattice_c_A")
    name = _ase_crystal(cry)
    if name == "hcp":
        atoms = bulk(sym, "hcp", a=a, c=float(c) if c else None)
    elif name == "diamond":
        atoms = bulk(sym, "diamond", a=a)
    else:
        atoms = bulk(sym, name, a=a, cubic=True)
    atoms = atoms.repeat((max(1, nx), max(1, ny), max(1, nz)))
    atoms.set_pbc(True)
    atoms.wrap()
    return atoms


def _punch_voids(atoms, params: dict[str, Any], rng: random.Random) -> int:
    cell = atoms.get_cell()
    lx, ly, lz = float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])
    r = float(params.get("void_radius_A") or 5.0)
    nvoid = max(1, int(params.get("void_count") or 1))
    cx0 = float(params.get("void_center_frac_x") or 0.5) * lx
    cy0 = float(params.get("void_center_frac_y") or 0.5) * ly
    cz0 = float(params.get("void_center_frac_z") or 0.5) * lz
    pos = atoms.get_positions()
    keep = np.ones(len(atoms), dtype=bool)
    removed = 0
    for i in range(nvoid):
        if i == 0:
            cx, cy, cz = cx0, cy0, cz0
        else:
            cx, cy, cz = rng.random() * lx, rng.random() * ly, rng.random() * lz
        d2 = (pos[:, 0] - cx) ** 2 + (pos[:, 1] - cy) ** 2 + (pos[:, 2] - cz) ** 2
        hit = d2 < r * r
        removed += int(np.sum(hit & keep))
        keep &= ~hit
    del_idx = np.where(~keep)[0]
    if len(del_idx):
        del atoms[del_idx.tolist()]
    return removed


def _void_lattice_centers(params: dict[str, Any], lx: float, ly: float, lz: float) -> list[tuple[float, float, float]]:
    nxv = max(1, min(16, int(params.get("void_lattice_nx") or 2)))
    nyv = max(1, min(16, int(params.get("void_lattice_ny") or 2)))
    nzv = max(1, min(16, int(params.get("void_lattice_nz") or 2)))
    centers: list[tuple[float, float, float]] = []
    for i in range(nxv):
        for j in range(nyv):
            for k in range(nzv):
                centers.append(
                    (
                        (i + 0.5) / nxv * lx,
                        (j + 0.5) / nyv * ly,
                        (k + 0.5) / nzv * lz,
                    )
                )
    return centers


def _punch_void_lattice(atoms, params: dict[str, Any]) -> tuple[int, dict[str, Any]]:
    """Punch a simple-cubic lattice of spherical voids (engineering bubble-lattice proxy)."""
    cell = atoms.get_cell()
    lx, ly, lz = float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])
    r = float(params.get("void_radius_A") or 5.0)
    centers = _void_lattice_centers(params, lx, ly, lz)
    nxv = max(1, min(16, int(params.get("void_lattice_nx") or 2)))
    nyv = max(1, min(16, int(params.get("void_lattice_ny") or 2)))
    nzv = max(1, min(16, int(params.get("void_lattice_nz") or 2)))
    spacing = (lx / nxv, ly / nyv, lz / nzv)
    if min(spacing) < 2.0 * r * 0.95:
        raise ValueError(
            f"Void lattice overlaps heavily: radius={r} Å but spacing~"
            f"({spacing[0]:.2f},{spacing[1]:.2f},{spacing[2]:.2f}) Å. "
            "Reduce void_radius_A, reduce void_lattice_n*, or enlarge the cell."
        )
    pos = atoms.get_positions()
    keep = np.ones(len(atoms), dtype=bool)
    removed = 0
    for cx, cy, cz in centers:
        d2 = (pos[:, 0] - cx) ** 2 + (pos[:, 1] - cy) ** 2 + (pos[:, 2] - cz) ** 2
        hit = d2 < r * r
        removed += int(np.sum(hit & keep))
        keep &= ~hit
    del_idx = np.where(~keep)[0]
    if len(del_idx):
        del atoms[del_idx.tolist()]
    meta = {
        "method": "ase-void-lattice-sc-v1",
        "n_voids": len(centers),
        "void_lattice_n": [nxv, nyv, nzv],
        "spacing_A": [float(spacing[0]), float(spacing[1]), float(spacing[2])],
        "radius_A": r,
        "centers_A": centers,
        "note": "Simple-cubic void lattice punched from bulk (bubble-lattice / swelling proxy).",
    }
    return removed, meta


def _voronoi_polycrystal(material: dict[str, Any], params: dict[str, Any]):
    """Voronoi polycrystal: clip randomly oriented grains into the simulation box."""
    from ase import Atoms
    from ase.build import bulk

    nx = int(params.get("nx") or 8)
    ny = int(params.get("ny") or 8)
    nz = int(params.get("nz") or 8)
    n_grains = max(2, min(int(params.get("poly_n_grains") or 4), 64))
    seed = int(params.get("poly_seed") or 42)
    rng = random.Random(seed)
    sym = _host_symbol(material)
    cry = _crystal_name(material)
    a = float(material.get("lattice_constant_A") or 3.165)
    name = _ase_crystal(cry)
    lattice_name = name
    # Prefer cubic prototypes for Voronoi clipping; HCP/hex keep hcp basis
    if name == "diamond":
        lattice_name = "diamond"
    elif name == "hcp":
        lattice_name = "hcp"

    if lattice_name == "hcp":
        c = material.get("lattice_c_A")
        proto = bulk(sym, "hcp", a=a, c=float(c) if c else None).repeat((nx, ny, nz))
    elif lattice_name == "diamond":
        proto = bulk(sym, "diamond", a=a).repeat((nx, ny, nz))
    else:
        proto = bulk(sym, lattice_name, a=a, cubic=True).repeat((nx, ny, nz))
    cell = proto.get_cell()
    lx, ly, lz = float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])
    seeds = [(rng.random() * lx, rng.random() * ly, rng.random() * lz) for _ in range(n_grains)]
    texture = str(params.get("poly_texture") or "random").strip().lower()

    pieces: list[Atoms] = []
    for gi, (sx, sy, sz) in enumerate(seeds):
        if lattice_name == "hcp":
            c = material.get("lattice_c_A")
            g = bulk(sym, "hcp", a=a, c=float(c) if c else None).repeat((nx + 2, ny + 2, nz + 2))
        elif lattice_name == "diamond":
            g = bulk(sym, "diamond", a=a).repeat((nx + 2, ny + 2, nz + 2))
        else:
            g = bulk(sym, lattice_name, a=a, cubic=True).repeat((nx + 2, ny + 2, nz + 2))
        if texture == "fiber":
            # Fiber: random rotation about z only
            g.rotate(rng.uniform(0, 360), "z", center="COP", rotate_cell=False)
        else:
            g.rotate(rng.uniform(0, 360), "x", center="COP", rotate_cell=False)
            g.rotate(rng.uniform(0, 360), "y", center="COP", rotate_cell=False)
            g.rotate(rng.uniform(0, 360), "z", center="COP", rotate_cell=False)
        g.translate(np.array([sx, sy, sz]) - g.get_center_of_mass())
        pos = g.get_positions()
        inside = (
            (pos[:, 0] >= 0)
            & (pos[:, 0] < lx)
            & (pos[:, 1] >= 0)
            & (pos[:, 1] < ly)
            & (pos[:, 2] >= 0)
            & (pos[:, 2] < lz)
        )
        best = np.full(len(g), np.inf)
        nearest = np.zeros(len(g), dtype=int)
        for j, (ox, oy, oz) in enumerate(seeds):
            dj = (pos[:, 0] - ox) ** 2 + (pos[:, 1] - oy) ** 2 + (pos[:, 2] - oz) ** 2
            better = dj < best
            nearest[better] = j
            best[better] = dj[better]
        sel = np.where(inside & (nearest == gi))[0]
        if len(sel):
            pieces.append(g[sel.tolist()])

    if not pieces:
        raise ValueError("ASE polycrystal builder produced no atoms — try fewer grains or a larger cell")
    out = pieces[0].copy()
    for p in pieces[1:]:
        out += p
    out.set_cell([lx, ly, lz], scale_atoms=False)
    out.set_pbc(True)
    out.wrap()
    try:
        from ase.geometry import get_duplicate_atoms

        get_duplicate_atoms(out, cutoff=0.35, delete=True)
    except Exception:
        pass
    return out, {
        "n_grains": n_grains,
        "seeds_A": seeds,
        "texture": texture,
        "method": "ase-voronoi-v1",
    }


def _parse_miller(s: str) -> tuple[int, int, int]:
    raw = (s or "001").strip().replace(",", " ").replace("[", "").replace("]", "")
    parts = [p for p in raw.split() if p]
    if len(parts) == 1:
        tok = parts[0]
        if tok.startswith("-"):
            raise ValueError(f"unsupported Miller index '{s}' — use 001, 011, 111, or '1 0 0'")
        if len(tok) == 3 and all(ch.isdigit() or ch == "-" for ch in tok.replace("-", "0")):
            # compact 001 / 110; reject leading signs in compact form for simplicity
            if "-" in tok:
                raise ValueError(f"use spaced Miller indices for negatives, got '{s}'")
            return int(tok[0]), int(tok[1]), int(tok[2])
        raise ValueError(f"could not parse Miller index '{s}'")
    if len(parts) == 3:
        return int(parts[0]), int(parts[1]), int(parts[2])
    raise ValueError(f"could not parse Miller index '{s}'")


def _axis_index(miller: tuple[int, int, int]) -> int:
    arr = np.abs(np.array(miller, dtype=float))
    if float(arr.sum()) < 1e-9:
        return 2
    return int(np.argmax(arr))


def _rotate_atoms(atoms, angle_deg: float, axis: np.ndarray, origin: np.ndarray) -> None:
    """Rotate atom positions in-place about an axis through origin (degrees)."""
    axis = np.asarray(axis, dtype=float)
    n = float(np.linalg.norm(axis))
    if n < 1e-12 or abs(angle_deg) < 1e-12:
        return
    axis = axis / n
    th = np.deg2rad(angle_deg)
    c, s = math.cos(th), math.sin(th)
    # Rodrigues
    K = np.array(
        [
            [0.0, -axis[2], axis[1]],
            [axis[2], 0.0, -axis[0]],
            [-axis[1], axis[0], 0.0],
        ]
    )
    R = np.eye(3) + s * K + (1.0 - c) * (K @ K)
    pos = atoms.get_positions()
    atoms.set_positions((pos - origin) @ R.T + origin)


def _bicrystal_tilt(material: dict[str, Any], params: dict[str, Any]):
    """Symmetric tilt bicrystal: two half-crystals joined along gb_normal."""
    nx = max(2, int(params.get("nx") or 8))
    ny = max(2, int(params.get("ny") or 8))
    nz = max(4, int(params.get("nz") or 8))
    theta = float(params.get("gb_misorientation_deg") or 15.0)
    tilt = _parse_miller(str(params.get("gb_tilt_axis") or "001"))
    normal = _parse_miller(str(params.get("gb_normal") or "001"))
    merge_axis = _axis_index(normal)

    reps = [nx, ny, nz]
    half = max(2, reps[merge_axis] // 2)
    reps_half = list(reps)
    reps_half[merge_axis] = half

    g1 = _make_bulk(material, reps_half[0], reps_half[1], reps_half[2])
    g2 = _make_bulk(material, reps_half[0], reps_half[1], reps_half[2])
    cell = np.array(g1.get_cell(), dtype=float)

    tilt_vec = np.array(tilt, dtype=float)
    _rotate_atoms(g1, -0.5 * theta, tilt_vec, g1.get_center_of_mass())
    _rotate_atoms(g2, 0.5 * theta, tilt_vec, g2.get_center_of_mass())

    shift = np.zeros(3)
    shift[merge_axis] = float(cell[merge_axis, merge_axis])
    g2.translate(shift)

    out = g1.copy()
    out += g2
    box = [float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])]
    box[merge_axis] = 2.0 * box[merge_axis]
    out.set_cell(box, scale_atoms=False)
    out.set_pbc(True)

    a = float(material.get("lattice_constant_A") or 3.165)
    try:
        from ase.geometry import get_duplicate_atoms

        get_duplicate_atoms(out, cutoff=max(0.25, 0.12 * a), delete=True)
    except Exception:
        pass

    pos = out.get_positions()
    keep = (
        (pos[:, 0] >= -0.05)
        & (pos[:, 0] < box[0] + 0.05)
        & (pos[:, 1] >= -0.05)
        & (pos[:, 1] < box[1] + 0.05)
        & (pos[:, 2] >= -0.05)
        & (pos[:, 2] < box[2] + 0.05)
    )
    if int(np.sum(keep)) < 8:
        raise ValueError(
            "ASE bicrystal produced too few atoms — try a larger cell or smaller misorientation"
        )
    if int(np.sum(~keep)):
        del out[np.where(~keep)[0].tolist()]
    out.wrap()
    if len(out) < 8:
        raise ValueError("ASE bicrystal builder failed — increase nx/ny/nz")

    meta = {
        "method": "ase-symmetric-tilt-v1",
        "misorientation_deg": theta,
        "tilt_axis": list(tilt),
        "gb_normal": list(normal),
        "merge_axis": ["x", "y", "z"][merge_axis],
        "n_grains": 2,
        "note": (
            "ASE symmetric-tilt bicrystal is an engineering construction; "
            "prefer Atomsk for production GB studies."
        ),
    }
    return out, meta


def _nanowire(material: dict[str, Any], params: dict[str, Any]):
    """Cylindrical nanowire carved from bulk with transverse vacuum padding."""
    nx = max(2, int(params.get("nx") or 8))
    ny = max(2, int(params.get("ny") or 8))
    nz = max(2, int(params.get("nz") or 8))
    r = float(params.get("nanowire_radius_A") or 8.0)
    vac = float(params.get("nanowire_vacuum_A") or 10.0)
    axis = str(params.get("nanowire_axis") or "z").strip().lower()
    if axis not in {"x", "y", "z"}:
        axis = "z"
    axis_i = {"x": 0, "y": 1, "z": 2}[axis]

    atoms = _make_bulk(material, nx, ny, nz)
    cell = np.array(atoms.get_cell(), dtype=float)
    box0 = [float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])]
    pos = atoms.get_positions()
    com = atoms.get_center_of_mass()
    # Radial distance in the plane perpendicular to the wire axis
    d2 = np.zeros(len(atoms))
    for i in range(3):
        if i == axis_i:
            continue
        d2 += (pos[:, i] - com[i]) ** 2
    keep = d2 <= r * r
    if int(np.sum(keep)) < 8:
        raise ValueError(
            f"Nanowire kept <8 atoms (radius={r} Å). Increase nanowire_radius_A or cell size."
        )
    del atoms[np.where(~keep)[0].tolist()]

    # Expand transverse box with vacuum; keep wire length
    new_box = list(box0)
    for i in range(3):
        if i != axis_i:
            new_box[i] = max(new_box[i], 2.0 * r + 2.0 * vac)
    # Center wire in the new box
    pos = atoms.get_positions()
    com = atoms.get_center_of_mass()
    shift = np.zeros(3)
    for i in range(3):
        shift[i] = 0.5 * new_box[i] - com[i]
    atoms.translate(shift)
    atoms.set_cell(new_box, scale_atoms=False)
    # Free surfaces transversely; periodic along wire
    pbc = [False, False, False]
    pbc[axis_i] = True
    atoms.set_pbc(pbc)
    atoms.wrap()
    meta = {
        "method": "ase-nanowire-cylinder-v1",
        "radius_A": r,
        "axis": axis,
        "vacuum_A": vac,
        "box_A": new_box,
        "note": "Cylindrical nanowire carved from bulk with transverse vacuum (engineering proxy).",
    }
    return atoms, meta


def _second_symbol(material: dict[str, Any], fallback: str = "Re") -> str:
    comps = material.get("composition") or []
    host = _host_symbol(material)
    for c in comps:
        sym = str(c.get("symbol") or "")
        if sym and sym.lower() != host.lower() and float(c.get("atomic_percent") or 0) > 0:
            return sym
    return fallback


def _precipitates(material: dict[str, Any], params: dict[str, Any], rng: random.Random):
    """Spherical precipitates of a second species embedded in the host matrix."""
    nx = max(2, int(params.get("nx") or 8))
    ny = max(2, int(params.get("ny") or 8))
    nz = max(2, int(params.get("nz") or 8))
    r = float(params.get("precipitate_radius_A") or 5.0)
    n = max(1, int(params.get("precipitate_count") or 1))
    host = _host_symbol(material)
    ppt = str(params.get("precipitate_species") or _second_symbol(material)).strip() or "Re"
    ppt = ppt[:1].upper() + ppt[1:]

    atoms = _make_bulk(material, nx, ny, nz)
    cell = atoms.get_cell()
    lx, ly, lz = float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])
    cx0 = float(params.get("precipitate_center_frac_x") or 0.5) * lx
    cy0 = float(params.get("precipitate_center_frac_y") or 0.5) * ly
    cz0 = float(params.get("precipitate_center_frac_z") or 0.5) * lz
    centers: list[tuple[float, float, float]] = []
    for i in range(n):
        if i == 0:
            centers.append((cx0, cy0, cz0))
        else:
            centers.append((rng.random() * lx, rng.random() * ly, rng.random() * lz))

    pos = atoms.get_positions()
    symbols = [host] * len(atoms)
    changed = 0
    for cx, cy, cz in centers:
        d2 = (pos[:, 0] - cx) ** 2 + (pos[:, 1] - cy) ** 2 + (pos[:, 2] - cz) ** 2
        hit = d2 < r * r
        for idx in np.where(hit)[0].tolist():
            if symbols[idx] != ppt:
                symbols[idx] = ppt
                changed += 1
    if changed < 1:
        raise ValueError(
            f"Precipitate changed 0 atoms (radius={r} Å, species={ppt}). "
            "Increase precipitate_radius_A or cell size."
        )
    atoms.set_chemical_symbols(symbols)
    meta = {
        "method": "ase-precipitate-sphere-v1",
        "host_symbol": host,
        "precipitate_species": ppt,
        "radius_A": r,
        "n_precipitates": n,
        "atoms_converted": changed,
        "centers_A": centers,
        "note": (
            f"Spherical {ppt} precipitates in {host} matrix (same crystal lattice; "
            "substitutional proxy - not a second crystal structure)."
        ),
    }
    return atoms, meta


def _write_lammps_data(atoms, path: Path, symbol: str | None = None) -> int:
    from ase.io import write

    atoms = atoms.copy()
    if symbol is not None:
        atoms.set_chemical_symbols([symbol] * len(atoms))
    path.parent.mkdir(parents=True, exist_ok=True)
    write(str(path), atoms, format="lammps-data", atom_style="atomic", masses=True)
    return len(atoms)


def build_with_ase(out_data: Path, *, material: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    kind = str(getattr(params.get("structure_kind"), "value", params.get("structure_kind")) or "void").lower()
    seed = int(params.get("poly_seed") or params.get("seed") or 42)
    rng = random.Random(seed)
    sym = _host_symbol(material)
    nx = int(params.get("nx") or 8)
    ny = int(params.get("ny") or 8)
    nz = int(params.get("nz") or 8)

    artificial_void = False
    removed = 0
    poly_meta: dict[str, Any] = {}
    gb_meta: dict[str, Any] = {}
    void_meta: dict[str, Any] = {}
    wire_meta: dict[str, Any] = {}
    ppt_meta: dict[str, Any] = {}
    force_mono = True

    if kind in {"polycrystal", "polycrystal_void"}:
        atoms, poly_meta = _voronoi_polycrystal(material, params)
    elif kind == "bicrystal":
        atoms, gb_meta = _bicrystal_tilt(material, params)
        poly_meta = {"n_grains": 2, **gb_meta}
    elif kind == "nanowire":
        atoms, wire_meta = _nanowire(material, params)
    elif kind == "precipitate":
        atoms, ppt_meta = _precipitates(material, params, rng)
        force_mono = False
    elif kind in {"void", "void_lattice"}:
        atoms = _make_bulk(material, nx, ny, nz)
    else:
        raise ValueError(f"ASE builder does not support structure_kind={kind}")

    if kind == "void_lattice":
        removed, void_meta = _punch_void_lattice(atoms, params)
        artificial_void = True
        if removed < 1:
            raise ValueError(
                f"Void lattice removed 0 atoms (radius={params.get('void_radius_A')} Å). "
                "Increase void_radius_A or cell size."
            )
    elif kind in {"void", "polycrystal_void"}:
        removed = _punch_voids(atoms, params, rng)
        artificial_void = True
        if removed < 1:
            raise ValueError(
                f"Nano-void removed 0 atoms (radius={params.get('void_radius_A')} Å). "
                "Increase void_radius_A or cell size."
            )

    n = _write_lammps_data(atoms, out_data, sym if force_mono else None)
    cell = atoms.get_cell()
    box_A = [float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])]
    note = "ASE structure builder"
    if kind == "bicrystal":
        note = gb_meta.get("note") or note
    elif kind == "void_lattice":
        note = void_meta.get("note") or note
    elif kind == "nanowire":
        note = wire_meta.get("note") or note
        box_A = wire_meta.get("box_A") or box_A
    elif kind == "precipitate":
        note = ppt_meta.get("note") or note
    elif poly_meta:
        note = (
            "ASE Voronoi polycrystal is an engineering construction; "
            "prefer Atomsk for production GB studies."
        )
    return {
        "atom_count": n,
        "host_symbol": sym,
        "box_A": box_A,
        "artificial_void": artificial_void,
        "void_atoms_removed": removed,
        "poly": poly_meta,
        "gb": gb_meta,
        "void_lattice": void_meta,
        "nanowire": wire_meta,
        "precipitate": ppt_meta,
        "note": note,
    }
