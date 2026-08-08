"""ASE-based structure builders (voids, Voronoi polycrystal)."""

from __future__ import annotations

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
    lattice_name = "bcc" if name == "hcp" else name

    proto = bulk(sym, lattice_name, a=a, cubic=True).repeat((nx, ny, nz))
    cell = proto.get_cell()
    lx, ly, lz = float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])
    seeds = [(rng.random() * lx, rng.random() * ly, rng.random() * lz) for _ in range(n_grains)]

    pieces: list[Atoms] = []
    for gi, (sx, sy, sz) in enumerate(seeds):
        g = bulk(sym, lattice_name, a=a, cubic=True).repeat((nx + 2, ny + 2, nz + 2))
        ang = rng.uniform(0, 360)
        g.rotate(ang, "x", center="COP", rotate_cell=False)
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
    return out, {"n_grains": n_grains, "seeds_A": seeds, "method": "ase-voronoi-v1"}


def _write_lammps_data(atoms, path: Path, symbol: str) -> int:
    from ase.io import write

    atoms = atoms.copy()
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

    if kind in {"polycrystal", "polycrystal_void"}:
        atoms, poly_meta = _voronoi_polycrystal(material, params)
    elif kind == "void":
        atoms = _make_bulk(material, nx, ny, nz)
    else:
        raise ValueError(f"ASE builder does not support structure_kind={kind}")

    if kind in {"void", "polycrystal_void"}:
        removed = _punch_voids(atoms, params, rng)
        artificial_void = True
        if removed < 1:
            raise ValueError(
                f"Nano-void removed 0 atoms (radius={params.get('void_radius_A')} Å). "
                "Increase void_radius_A or cell size."
            )

    n = _write_lammps_data(atoms, out_data, sym)
    cell = atoms.get_cell()
    return {
        "atom_count": n,
        "host_symbol": sym,
        "box_A": [float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])],
        "artificial_void": artificial_void,
        "void_atoms_removed": removed,
        "poly": poly_meta,
        "note": (
            "ASE Voronoi polycrystal is an engineering construction; prefer Atomsk for production GB studies."
            if poly_meta
            else "ASE structure builder"
        ),
    }
