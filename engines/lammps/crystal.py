"""Crystal structure registry for Aegis LAMMPS builders and WS analysis.

Single source of truth for BCC / FCC / HCP / diamond / WC-hex lattices:
lattice lines, sites per cell, PKA snap, ideal WS grids, interstitial
geometries, and orientation presets.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Iterable


SUPPORTED_RUNNABLE = frozenset({"bcc", "fcc", "hcp", "diamond", "hex"})


@dataclass(frozen=True)
class CrystalInfo:
    id: str
    label: str
    atoms_per_cell: int
    needs_c: bool
    supported: bool
    interstitial_geometries: tuple[str, ...]
    default_interstitial_geometry: str
    default_interstitial_direction: str
    orients: tuple[tuple[str, str], ...]  # (id, label)
    notes: str = ""
    sublattices: tuple[str, ...] = ()


_CRYSTALS: dict[str, CrystalInfo] = {
    "bcc": CrystalInfo(
        id="bcc",
        label="BCC",
        atoms_per_cell=2,
        needs_c=False,
        supported=True,
        interstitial_geometries=("octahedral", "tetrahedral", "dumbbell", "crowdion"),
        default_interstitial_geometry="octahedral",
        default_interstitial_direction="111",
        orients=(
            ("100", "⟨100⟩"),
            ("110", "⟨110⟩"),
            ("111", "⟨111⟩"),
        ),
        notes="Body-centered cubic (W, Mo, Fe, Ta, Cr).",
    ),
    "fcc": CrystalInfo(
        id="fcc",
        label="FCC",
        atoms_per_cell=4,
        needs_c=False,
        supported=True,
        interstitial_geometries=("octahedral", "tetrahedral", "dumbbell"),
        default_interstitial_geometry="dumbbell",
        default_interstitial_direction="110",
        orients=(
            ("100", "⟨100⟩"),
            ("110", "⟨110⟩"),
            ("111", "⟨111⟩"),
        ),
        notes="Face-centered cubic (Cu, Al, Ni).",
    ),
    "hcp": CrystalInfo(
        id="hcp",
        label="HCP",
        atoms_per_cell=2,
        needs_c=True,
        supported=True,
        interstitial_geometries=("octahedral", "tetrahedral", "dumbbell", "basal"),
        default_interstitial_geometry="octahedral",
        default_interstitial_direction="basal",
        orients=(
            ("basal", "basal (c ‖ z)"),
            ("prism", "prism"),
            ("100", "⟨100⟩-like"),
        ),
        notes="Hexagonal close-packed metal (Be, Re, Ti).",
    ),
    "diamond": CrystalInfo(
        id="diamond",
        label="Diamond",
        atoms_per_cell=8,
        needs_c=False,
        supported=True,
        interstitial_geometries=("tetrahedral", "dumbbell", "hexagonal"),
        default_interstitial_geometry="tetrahedral",
        default_interstitial_direction="100",
        orients=(
            ("100", "⟨100⟩"),
            ("110", "⟨110⟩"),
            ("111", "⟨111⟩"),
        ),
        notes="Diamond cubic (C, Si, Ge).",
    ),
    "hex": CrystalInfo(
        id="hex",
        label="Hexagonal (WC)",
        atoms_per_cell=2,
        needs_c=True,
        supported=True,
        interstitial_geometries=("octahedral", "tetrahedral", "dumbbell"),
        default_interstitial_geometry="octahedral",
        default_interstitial_direction="c",
        orients=(
            ("basal", "basal (c ‖ z)"),
            ("prism", "prism"),
        ),
        notes="WC-like hexagonal with W+C basis (sublattice-aware WS).",
        sublattices=("W", "C"),
    ),
    "other": CrystalInfo(
        id="other",
        label="Other",
        atoms_per_cell=1,
        needs_c=False,
        supported=False,
        interstitial_geometries=("octahedral",),
        default_interstitial_geometry="octahedral",
        default_interstitial_direction="100",
        orients=(("100", "⟨100⟩"),),
        notes="Unsupported — dry-run only.",
    ),
}


def normalize_crystal(crystal: str | None) -> str:
    key = str(crystal or "bcc").strip().lower()
    aliases = {
        "wc": "hex",
        "hcp-metal": "hcp",
        "diamond_cubic": "diamond",
        "dia": "diamond",
    }
    return aliases.get(key, key)


def get_crystal(crystal: str | None) -> CrystalInfo:
    key = normalize_crystal(crystal)
    return _CRYSTALS.get(key, _CRYSTALS["other"])


def is_supported(crystal: str | None) -> bool:
    return get_crystal(crystal).supported


def list_crystals() -> list[dict[str, Any]]:
    out = []
    for c in _CRYSTALS.values():
        if c.id == "other":
            continue
        out.append(
            {
                "id": c.id,
                "label": c.label,
                "atoms_per_cell": c.atoms_per_cell,
                "needs_c": c.needs_c,
                "supported": c.supported,
                "interstitial_geometries": list(c.interstitial_geometries),
                "default_interstitial_geometry": c.default_interstitial_geometry,
                "default_interstitial_direction": c.default_interstitial_direction,
                "orients": [{"id": oid, "label": lab} for oid, lab in c.orients],
                "notes": c.notes,
                "sublattices": list(c.sublattices),
            }
        )
    return out


def resolve_c_A(material: dict[str, Any], crystal: str | None = None) -> float | None:
    info = get_crystal(crystal or material.get("crystal"))
    if not info.needs_c:
        return None
    c = material.get("lattice_c_A")
    if c is not None and float(c) > 0:
        return float(c)
    a = float(material.get("lattice_constant_A") or 1.0)
    ratio = material.get("c_over_a")
    if ratio is not None and float(ratio) > 0:
        return a * float(ratio)
    # Sensible metallic / WC defaults
    defaults = {"hcp": 1.633, "hex": 0.976}
    return a * defaults.get(info.id, 1.633)


def lattice_line(material: dict[str, Any], params: dict[str, Any] | None = None) -> str:
    """LAMMPS lattice command for the material crystal."""
    params = params or {}
    crystal = normalize_crystal(material.get("crystal"))
    info = get_crystal(crystal)
    if not info.supported:
        raise ValueError(
            f"crystal '{crystal}' is not supported for real LAMMPS builds "
            "(dry-run only). Use bcc, fcc, hcp, diamond, or hex."
        )
    a = float(material.get("lattice_constant_A", 3.165))
    orient = str(params.get("crystal_orient", "100")).strip().replace(" ", "")
    o = _orient_clause(crystal, orient)
    if crystal == "bcc":
        return f"lattice bcc {a} {o}".strip()
    if crystal == "fcc":
        return f"lattice fcc {a} {o}".strip()
    if crystal == "diamond":
        return f"lattice diamond {a} {o}".strip()
    if crystal == "hcp":
        # LAMMPS native `lattice hcp a` locks c/a = √(8/3); use custom for material c.
        c = resolve_c_A(material, crystal) or a * 1.633
        return (
            f"lattice custom {a} "
            f"a1 1.0 0.0 0.0 "
            f"a2 -0.5 {math.sqrt(3)/2:.8f} 0.0 "
            f"a3 0.0 0.0 {c/a:.8f} "
            f"basis 0.0 0.0 0.0 "
            f"basis 0.333333 0.666667 0.5 "
            f"{o}"
        ).strip()
    if crystal == "hex":
        # WC: custom lattice — two basis sites (W at 0,0,0; C at 1/3,2/3,1/2)
        c = resolve_c_A(material, crystal) or a * 0.976
        return (
            f"lattice custom {a} "
            f"a1 1.0 0.0 0.0 "
            f"a2 -0.5 {math.sqrt(3)/2:.8f} 0.0 "
            f"a3 0.0 0.0 {c/a:.8f} "
            f"basis 0.0 0.0 0.0 "
            f"basis 0.333333 0.666667 0.5 "
            f"{o}"
        ).strip()
    raise ValueError(f"unsupported crystal {crystal}")


def crystal_comment(material: dict[str, Any]) -> str:
    crystal = normalize_crystal(material.get("crystal"))
    info = get_crystal(crystal)
    a = material.get("lattice_constant_A")
    c = resolve_c_A(material, crystal)
    extra = f" a={a}"
    if c is not None:
        extra += f" c={c:.4f}"
    if not info.supported:
        return (
            f"# WARNING: crystal={crystal} unsupported — do not use for production MD. "
            "Dry-run demo only."
        )
    note = f"# Crystal: {info.label} builder{extra}"
    if info.sublattices:
        note += f" (sublattices: {', '.join(info.sublattices)})"
    return note


def _orient_clause(crystal: str, orient: str) -> str:
    cubic = {
        "100": "orient x 1 0 0 orient y 0 1 0 orient z 0 0 1",
        "110": "orient x 1 1 0 orient y -1 1 0 orient z 0 0 1",
        "111": "orient x 1 1 1 orient y 1 -1 0 orient z 1 1 -2",
    }
    if crystal in {"bcc", "fcc", "diamond"}:
        return cubic.get(orient, cubic["100"])
    # HCP / hex: basal keeps c along z; prism swaps
    if orient in {"basal", "100", ""}:
        return "orient x 1 0 0 orient y 0 1 0 orient z 0 0 1"
    if orient == "prism":
        return "orient x 0 0 1 orient y 1 0 0 orient z 0 1 0"
    return cubic.get(orient, "")


def basis_offsets(crystal: str) -> list[tuple[float, float, float]]:
    """Fractional offsets within one conventional/custom cell (lattice units)."""
    c = normalize_crystal(crystal)
    if c == "bcc":
        return [(0.0, 0.0, 0.0), (0.5, 0.5, 0.5)]
    if c == "fcc":
        return [(0.0, 0.0, 0.0), (0.5, 0.5, 0.0), (0.5, 0.0, 0.5), (0.0, 0.5, 0.5)]
    if c == "hcp":
        # LAMMPS hcp uses 2 atoms; approximate A/B stacking in orthorhombic-like cells
        return [(0.0, 0.0, 0.0), (0.333333, 0.666667, 0.5)]
    if c == "diamond":
        return [
            (0.0, 0.0, 0.0),
            (0.0, 0.5, 0.5),
            (0.5, 0.0, 0.5),
            (0.5, 0.5, 0.0),
            (0.25, 0.25, 0.25),
            (0.25, 0.75, 0.75),
            (0.75, 0.25, 0.75),
            (0.75, 0.75, 0.25),
        ]
    if c == "hex":
        return [(0.0, 0.0, 0.0), (0.333333, 0.666667, 0.5)]
    return [(0.0, 0.0, 0.0)]


def snap_lattice_site(
    crystal: str,
    fx: float,
    fy: float,
    fz: float,
    nx: int,
    ny: int,
    nz: int,
) -> tuple[float, float, float]:
    """Snap fractional box coords to nearest lattice site (lattice units)."""
    tx = max(0.0, min(1.0, fx)) * nx
    ty = max(0.0, min(1.0, fy)) * ny
    tz = max(0.0, min(1.0, fz)) * nz
    offsets = basis_offsets(crystal)
    candidates: list[tuple[float, float, float]] = []
    i0, j0, k0 = int(math.floor(tx)), int(math.floor(ty)), int(math.floor(tz))
    for di in range(-1, 3):
        for dj in range(-1, 3):
            for dk in range(-1, 3):
                i, j, k = i0 + di, j0 + dj, k0 + dk
                if not (0 <= i < nx and 0 <= j < ny and 0 <= k < nz):
                    continue
                for ox, oy, oz in offsets:
                    x, y, z = i + ox, j + oy, k + oz
                    if 0 <= x < nx and 0 <= y < ny and 0 <= z < nz:
                        candidates.append((x, y, z))
    if not candidates:
        return nx * 0.5, ny * 0.5, nz * 0.5
    return min(candidates, key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2 + (p[2] - tz) ** 2)


def ideal_sites(
    box: tuple[float, float, float],
    crystal: str,
    a: float,
    *,
    c: float | None = None,
    z_max: float | None = None,
) -> list[tuple[float, float, float]]:
    """Ideal lattice sites in Å for Wigner–Seitz proxy analysis.

    For HCP/hex, sites are built from the same lattice vectors as ``lattice_line``
    (a1, a2, a3 with fractional basis), using an orthogonal bounding-box estimate
    of nx,ny,nz from dump extents.
    """
    lx, ly, lz = box
    cry = normalize_crystal(crystal)
    a = max(float(a), 1e-6)
    if cry in {"hcp", "hex"}:
        c_len = float(c) if c and c > 0 else a * (1.633 if cry == "hcp" else 0.976)
        # Match LAMMPS custom lattice: a1=(a,0,0), a2=(-a/2, a*√3/2, 0), a3=(0,0,c)
        a1x, a1y = a, 0.0
        a2x, a2y = -0.5 * a, a * math.sqrt(3) / 2.0
        # Orthogonal span of one cell for counting
        cell_x = a
        cell_y = a * math.sqrt(3) / 2.0
        nx = max(int(round(lx / cell_x)), 1)
        ny = max(int(round(ly / cell_y)), 1)
        nz = max(int(round(lz / c_len)), 1)
        sites: list[tuple[float, float, float]] = []
        for i in range(nx):
            for j in range(ny):
                for k in range(nz):
                    for fx, fy, fz in basis_offsets(cry):
                        x = (i + fx) * a1x + (j + fy) * a2x
                        y = (i + fx) * a1y + (j + fy) * a2y
                        z = (k + fz) * c_len
                        if z_max is not None and z > z_max:
                            continue
                        if -1e-6 <= x <= lx + 1e-6 and -1e-6 <= y <= ly + 1e-6 and z <= lz + 1e-6:
                            sites.append((x, y, z))
        return sites

    nx = max(int(round(lx / a)), 1)
    ny = max(int(round(ly / a)), 1)
    nz = max(int(round(lz / a)), 1)
    sites = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                for ox, oy, oz in basis_offsets(cry):
                    x, y, z = i * a + ox * a, j * a + oy * a, k * a + oz * a
                    if z_max is not None and z > z_max:
                        continue
                    sites.append((x, y, z))
    return sites


def ideal_sites_sublattice(
    box: tuple[float, float, float],
    crystal: str,
    a: float,
    *,
    c: float | None = None,
    z_max: float | None = None,
) -> dict[str, list[tuple[float, float, float]]]:
    """For WC hex: split sites into W (basis 0) and C (basis 1)."""
    cry = normalize_crystal(crystal)
    if cry != "hex":
        return {"host": ideal_sites(box, cry, a, c=c, z_max=z_max)}
    lx, ly, lz = box
    a = max(float(a), 1e-6)
    c_len = float(c) if c and c > 0 else a * 0.976
    a1x, a1y = a, 0.0
    a2x, a2y = -0.5 * a, a * math.sqrt(3) / 2.0
    cell_x, cell_y = a, a * math.sqrt(3) / 2.0
    nx = max(int(round(lx / cell_x)), 1)
    ny = max(int(round(ly / cell_y)), 1)
    nz = max(int(round(lz / c_len)), 1)
    w_sites: list[tuple[float, float, float]] = []
    c_sites: list[tuple[float, float, float]] = []
    bases = basis_offsets(cry)
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                for label, (fx, fy, fz) in (("W", bases[0]), ("C", bases[1] if len(bases) > 1 else bases[0])):
                    x = (i + fx) * a1x + (j + fy) * a2x
                    y = (i + fx) * a1y + (j + fy) * a2y
                    z = (k + fz) * c_len
                    if z_max is not None and z > z_max:
                        continue
                    if -1e-6 <= x <= lx + 1e-6 and -1e-6 <= y <= ly + 1e-6 and z <= lz + 1e-6:
                        (w_sites if label == "W" else c_sites).append((x, y, z))
    return {"W": w_sites, "C": c_sites}


def validate_interstitial_geometry(crystal: str, geometry: str) -> str:
    info = get_crystal(crystal)
    geom = geometry.strip().lower()
    if geom in info.interstitial_geometries:
        return geom
    return info.default_interstitial_geometry


def direction_unit(crystal: str, direction: str, seed: int) -> tuple[float, float, float]:
    key = direction.strip().lower().replace("<", "").replace(">", "").replace("[", "").replace("]", "")
    presets: dict[str, tuple[float, float, float]] = {
        "100": (1.0, 0.0, 0.0),
        "010": (0.0, 1.0, 0.0),
        "001": (0.0, 0.0, 1.0),
        "110": (1.0, 1.0, 0.0),
        "111": (1.0, 1.0, 1.0),
        "basal": (1.0, 0.0, 0.0),
        "c": (0.0, 0.0, 1.0),
        "prism": (0.0, 1.0, 0.0),
    }
    cry = normalize_crystal(crystal)
    if cry == "fcc" and key in {"", "default"}:
        key = "110"
    if cry == "bcc" and key in {"", "default"}:
        key = "111"
    if key == "random":
        x = math.sin(seed * 12.9898) * 43758.5453
        y = math.sin(seed * 78.233) * 43758.5453
        z = math.sin(seed * 39.425) * 43758.5453
        vx = (x - math.floor(x)) * 2 - 1
        vy = (y - math.floor(y)) * 2 - 1
        vz = (z - math.floor(z)) * 2 - 1
    elif key in presets:
        vx, vy, vz = presets[key]
    else:
        parts = [float(x) for x in direction.replace(",", " ").split() if x.strip()]
        while len(parts) < 3:
            parts.append(0.0)
        vx, vy, vz = parts[0], parts[1], parts[2]
    norm = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
    return vx / norm, vy / norm, vz / norm


def interstitial_sites_lattice(
    *,
    crystal: str,
    geometry: str,
    count: int,
    nx: int,
    ny: int,
    nz: int,
    direction: tuple[float, float, float],
    a: float,
    offset_A: float,
) -> list[tuple[float, float, float, str]]:
    """Lattice-unit interstitial insert positions (crystal-aware offsets)."""
    geom = validate_interstitial_geometry(crystal, geometry)
    ux, uy, uz = direction
    cx, cy, cz = nx * 0.5, ny * 0.5, nz * 0.5
    if abs(ux) < 0.9:
        px, py, pz = 0.0, -uz, uy
    else:
        px, py, pz = -uy, ux, 0.0
    pn = math.sqrt(px * px + py * py + pz * pz) or 1.0
    px, py, pz = px / pn, py / pn, pz / pn
    qx, qy, qz = uy * pz - uz * py, uz * px - ux * pz, ux * py - uy * px
    half = (offset_A / a) if a > 0 else 0.25
    cry = normalize_crystal(crystal)
    sites: list[tuple[float, float, float, str]] = []

    for i in range(count):
        sx = ((i % 3) - 1) * 0.35
        sy = (((i // 3) % 3) - 1) * 0.35
        sz = ((i // 9) % 3) * 0.2
        base_x = min(max(cx + sx * px + sy * qx + sz * ux, 0.25), nx - 0.25)
        base_y = min(max(cy + sx * py + sy * qy + sz * uy, 0.25), ny - 0.25)
        base_z = min(max(cz + sx * pz + sy * qz + sz * uz, 0.25), nz - 0.25)

        if geom in {"dumbbell", "crowdion"}:
            sep = half if geom == "dumbbell" else half * 1.6
            sites.append((base_x + sep * ux, base_y + sep * uy, base_z + sep * uz, "pair"))
            sites.append((base_x - sep * ux, base_y - sep * uy, base_z - sep * uz, "pair"))
        elif geom == "tetrahedral":
            if cry == "diamond":
                sites.append((base_x + 0.5, base_y + 0.5, base_z + 0.5, "single"))
            elif cry == "fcc":
                sites.append((base_x + 0.25, base_y + 0.25, base_z + 0.25, "single"))
            else:
                ox = 0.5 * ux + 0.25 * px
                oy = 0.5 * uy + 0.25 * py
                oz = 0.5 * uz + 0.25 * pz
                sites.append((base_x + ox * 0.5, base_y + oy * 0.5, base_z + oz * 0.5, "single"))
        elif geom in {"basal", "hexagonal"}:
            sites.append((base_x + 0.5 * px, base_y + 0.5 * py, base_z, "single"))
        else:
            # octahedral default
            if cry == "fcc":
                sites.append((base_x + 0.5, base_y, base_z, "single"))
            else:
                sites.append((base_x + 0.5 * ux, base_y + 0.5 * uy, base_z + 0.5 * uz, "single"))
    return sites


def atoms_per_cell(crystal: str | None) -> int:
    return get_crystal(crystal).atoms_per_cell
