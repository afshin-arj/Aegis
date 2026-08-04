from __future__ import annotations

import math
import textwrap
from pathlib import Path
from typing import Any


def _elements_line(composition: list[dict[str, Any]]) -> list[str]:
    return [c["symbol"] for c in composition if c.get("atomic_percent", 0) > 0]


def render_pair_coeff(template: str, file_path: str, elements: list[str]) -> str:
    return template.format(file=file_path.replace("\\", "/"), elements=" ".join(elements))


def _direction_unit(direction: str, seed: int) -> tuple[float, float, float]:
    if direction.strip().lower() == "random":
        # Deterministic pseudo-random unit vector from seed (reproducible templates)
        x = math.sin(seed * 12.9898) * 43758.5453
        y = math.sin(seed * 78.233) * 43758.5453
        z = math.sin(seed * 39.425) * 43758.5453
        vx, vy, vz = (x - math.floor(x)) * 2 - 1, (y - math.floor(y)) * 2 - 1, (z - math.floor(z)) * 2 - 1
    else:
        parts = [float(x) for x in direction.replace(",", " ").split()]
        while len(parts) < 3:
            parts.append(0.0)
        vx, vy, vz = parts[0], parts[1], parts[2]
    norm = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
    return vx / norm, vy / norm, vz / norm


def _dump_command(params: dict[str, Any], pattern: str) -> tuple[str, str]:
    every = int(params.get("dump_every", 1000))
    style = str(params.get("dump_style", "custom")).strip().lower() or "custom"
    if style == "atom":
        return (
            f"dump 1 all atom {every} {pattern}",
            "dump_modify 1 pad 9",
        )
    return (
        f"dump 1 all custom {every} {pattern} id type x y z",
        "dump_modify 1 sort id pad 9",
    )


def _ensemble_fix(params: dict[str, Any]) -> str:
    raw = params.get("ensemble", "nve")
    ensemble = str(getattr(raw, "value", raw)).lower()
    T = float(params.get("temperature_K", 300))
    damp = float(params.get("damp_ps", 0.1))
    if ensemble == "nvt":
        return f"fix 1 all nvt temp {T} {T} {damp}"
    return "fix 1 all nve"


def _restart_block(params: dict[str, Any]) -> str:
    every = int(params.get("restart_every", 0) or 0)
    if every <= 0:
        return ""
    return f"restart {every} restart.*.aegis"


def _lattice_line(a: float, params: dict[str, Any]) -> str:
    orient = str(params.get("crystal_orient", "100")).strip().replace(" ", "")
    # LAMMPS lattice orient: x / y / z Miller vectors
    presets = {
        "100": "orient x 1 0 0 orient y 0 1 0 orient z 0 0 1",
        "110": "orient x 1 1 0 orient y -1 1 0 orient z 0 0 1",
        "111": "orient x 1 1 1 orient y 1 -1 0 orient z 1 1 -2",
    }
    o = presets.get(orient, presets["100"])
    return f"lattice bcc {a} {o}"


def _crystal_comment(material: dict[str, Any]) -> str:
    crystal = str(material.get("crystal", "bcc")).lower()
    if crystal != "bcc":
        return (
            f"# WARNING: material crystal={crystal}; Aegis Phase-1 templates always build BCC. "
            "Results are not representative for non-BCC lattices."
        )
    return "# Crystal: BCC lattice builder"


def write_cascade_input(
    path: Path,
    *,
    material: dict[str, Any],
    potential: dict[str, Any],
    params: dict[str, Any],
    potential_file: str,
) -> Path:
    """Write a LAMMPS cascade input from UI run parameters."""
    elems = _elements_line(material["composition"])
    primary = str(params.get("pka_species") or (elems[0] if elems else "W"))
    a = float(material.get("lattice_constant_A", 3.165))
    nx, ny, nz = int(params["nx"]), int(params["ny"]), int(params["nz"])
    seed = int(params["seed"])
    dt = float(params["timestep_fs"])
    steps = int(params["max_steps"])
    T = float(params["temperature_K"])
    E = float(params["pka_energy_eV"])
    n_pkas = max(1, int(params.get("n_pkas", 1)))
    delay = max(0, int(params.get("pka_delay_steps", 0)))
    pair_style = potential["lammps_pair_style"]
    pair_coeff = render_pair_coeff(
        potential["pair_coeff_template"], potential_file, elems
    )
    mass_pka = _approx_mass(primary)
    speed = math.sqrt(2.0 * E / mass_pka) * 98.226947

    masses = "\n".join(f"mass {i+1} {_approx_mass(sym)}" for i, sym in enumerate(elems))
    create = _create_atoms_block(material, elems)
    ensemble = _ensemble_fix(params)
    dump, dump_mod = _dump_command(params, "dump.cascade.*.lammpstrj")
    restart = _restart_block(params)
    crystal_note = _crystal_comment(material)

    # Multi-PKA: kick distinct near-center atoms (mid-ID proxy for cubic BCC fill)
    pka_blocks: list[str] = []
    for i in range(n_pkas):
        s = seed + i * 9973
        dvx, dvy, dvz = _direction_unit(str(params.get("pka_direction", "random")), s)
        sp = speed
        # Atom id 1 is a corner site; mid-box IDs are closer to the geometric center
        # for sequential create_atoms on a cubic lattice. Offset for multi-PKA.
        pka_blocks.append(
            textwrap.dedent(
                f"""\
                # PKA event {i + 1}/{n_pkas} species={primary}
                variable cx equal lx/2
                variable cy equal ly/2
                variable cz equal lz/2
                variable pkaid equal min(atoms,max(1,(({i}+1)*floor(atoms/({n_pkas}+1)))+1))
                group pka_{i} id ${{pkaid}}
                velocity pka_{i} set {dvx * sp:.6f} {dvy * sp:.6f} {dvz * sp:.6f} units box
                """
            )
        )
        if i < n_pkas - 1 and delay > 0:
            pka_blocks.append(f"run {delay}")

    pka_script = "\n".join(pka_blocks)

    script = textwrap.dedent(
        f"""\
        # Aegis-generated cascade input — review before production use
        {crystal_note}
        units metal
        dimension 3
        boundary {params.get("boundary", "p p p")}
        atom_style atomic

        lattice bcc {a}
        region box block 0 {nx} 0 {ny} 0 {nz} units lattice
        create_box {len(elems)} box
        {create}
        {masses}

        pair_style {pair_style}
        {pair_coeff}

        neighbor {params.get("neighbor_skin", 2.0)} bin
        neigh_modify delay 0 every 1 check yes

        velocity all create {T} {seed} mom yes rot yes
        {ensemble}

        # Thermalize briefly
        run 1000

        # Reference structure BEFORE cascade (OVITO-like "before")
        write_dump all custom dump.initial.lammpstrj id type x y z modify sort id

        reset_timestep 0
        thermo {int(params.get("thermo_every", 100))}
        thermo_style custom step temp pe ke etotal press
        {dump}
        {dump_mod}
        {restart}

        {pka_script}
        # Capture cascade t=0 immediately after PKA kick(s)
        run 0

        timestep {dt}
        run {steps}

        write_data final.data
        print "Aegis cascade finished"
        """
    )
    # Inject oriented lattice command
    script = script.replace(
        f"lattice bcc {a}\n",
        f"{_lattice_line(a, params)}\n",
        1,
    )
    path.write_text(script, encoding="utf-8")
    return path


def write_implant_input(
    path: Path,
    *,
    material: dict[str, Any],
    potential: dict[str, Any],
    params: dict[str, Any],
    potential_file: str,
) -> Path:
    elems = _elements_line(material["composition"])
    ion = str(params.get("ion_type", "He"))
    if ion not in elems:
        elems = elems + [ion]
    a = float(material.get("lattice_constant_A", 3.165))
    nx, ny, nz = int(params["nx"]), int(params["ny"]), int(params["nz"])
    pair_style = potential["lammps_pair_style"]
    pair_coeff = render_pair_coeff(
        potential.get("pair_coeff_template", "pair_coeff * * {file} {elements}"),
        potential_file,
        elems,
    )
    E = float(params.get("ion_energy_eV", 500))
    T = float(params["temperature_K"])
    seed = int(params["seed"])
    dt = float(params["timestep_fs"])
    steps = int(params["max_steps"])
    ion_count = max(1, int(params.get("ion_count", 1)))
    angle_deg = float(params.get("ion_angle_deg", 0.0))
    angle = math.radians(angle_deg)
    mass_ion = _approx_mass(ion)
    speed = math.sqrt(2.0 * E / mass_ion) * 98.226947
    # Incidence: 0° = normal to top surface (−z); angle tilts in xz plane
    vx = speed * math.sin(angle)
    vy = 0.0
    vz = -speed * math.cos(angle)

    masses = "\n".join(f"mass {i+1} {_approx_mass(sym)}" for i, sym in enumerate(elems))
    ion_type = elems.index(ion) + 1
    create = _create_atoms_block(material, [e for e in elems if e != ion])
    ensemble = _ensemble_fix(params)
    dump, dump_mod = _dump_command(params, "dump.implant.*.lammpstrj")
    restart = _restart_block(params)
    crystal_note = _crystal_comment(material)

    insert_lines = []
    for i in range(ion_count):
        # Spread ions slightly in xy for multi-ion proxy
        fx = 0.5 + 0.05 * ((i % 3) - 1)
        fy = 0.5 + 0.05 * (((i // 3) % 3) - 1)
        insert_lines.append(
            f"create_atoms {ion_type} single {fx:.3f} {fy:.3f} {nz - 0.5} units lattice"
        )
    insert_block = "\n".join(insert_lines)

    script = textwrap.dedent(
        f"""\
        # Aegis-generated ion implant input
        {crystal_note}
        units metal
        dimension 3
        boundary {params.get("boundary", "p p p")}
        atom_style atomic

        lattice bcc {a}
        region box block 0 {nx} 0 {ny} 0 {nz} units lattice
        create_box {len(elems)} box
        {create}
        {masses}

        pair_style {pair_style}
        {pair_coeff}

        neighbor {params.get("neighbor_skin", 2.0)} bin
        neigh_modify delay 0 every 1 check yes

        velocity all create {T} {seed} mom yes rot yes
        {ensemble}
        run 500

        # Reference lattice BEFORE ion insertion
        write_dump all custom dump.initial.lammpstrj id type x y z modify sort id

        # Insert {ion_count} × {ion} near top surface (angle={angle_deg} deg from normal)
        {insert_block}
        group implant type {ion_type}
        velocity implant set {vx:.6f} {vy:.6f} {vz:.6f} units box

        reset_timestep 0
        thermo {int(params.get("thermo_every", 100))}
        thermo_style custom step temp pe ke etotal press
        {dump}
        {dump_mod}
        {restart}
        run 0
        timestep {dt}
        run {steps}
        write_data final.data
        print "Aegis implant finished"
        """
    )
    script = script.replace(
        f"lattice bcc {a}\n",
        f"{_lattice_line(a, params)}\n",
        1,
    )
    path.write_text(script, encoding="utf-8")
    return path


def write_surface_input(
    path: Path,
    *,
    material: dict[str, Any],
    potential: dict[str, Any],
    params: dict[str, Any],
    potential_file: str,
) -> Path:
    """Low-E He/D free-surface MD with vacuum slab (Phase-3 fuzz/erosion proxy)."""
    elems = _elements_line(material["composition"])
    ion = str(params.get("ion_type", "He"))
    if ion not in elems:
        elems = elems + [ion]
    a = float(material.get("lattice_constant_A", 3.165))
    nx, ny, nz = int(params["nx"]), int(params["ny"]), int(params["nz"])
    vacuum = max(1, int(params.get("vacuum_layers", 4)))
    nz_box = nz + vacuum
    pair_style = potential["lammps_pair_style"]
    pair_coeff = render_pair_coeff(
        potential.get("pair_coeff_template", "pair_coeff * * {file} {elements}"),
        potential_file,
        elems,
    )
    E = float(params.get("ion_energy_eV", 50))
    T = float(params["temperature_K"])
    seed = int(params["seed"])
    dt = float(params["timestep_fs"])
    steps = int(params["max_steps"])
    n_impacts = max(1, int(params.get("surface_fluence_ions") or params.get("ion_count", 1)))
    angle_deg = float(params.get("ion_angle_deg", 0.0))
    angle = math.radians(angle_deg)
    mass_ion = _approx_mass(ion)
    speed = math.sqrt(2.0 * E / mass_ion) * 98.226947
    vx = speed * math.sin(angle)
    vy = 0.0
    vz = -speed * math.cos(angle)

    masses = "\n".join(f"mass {i+1} {_approx_mass(sym)}" for i, sym in enumerate(elems))
    ion_type = elems.index(ion) + 1
    host_elems = [e for e in elems if e != ion]
    create_host = (
        f"region substrate block 0 {nx} 0 {ny} 0 {nz} units lattice\n"
        f"create_atoms 1 region substrate"
    )
    if len(host_elems) > 1:
        create_host = (
            f"region substrate block 0 {nx} 0 {ny} 0 {nz} units lattice\n"
            f"create_atoms 1 region substrate\n"
            f"group all_atoms type 1\n"
        )
        remaining = 1.0
        comp = {c["symbol"]: c["atomic_percent"] / 100.0 for c in material["composition"]}
        for i, sym in enumerate(host_elems):
            if i == 0:
                continue
            frac = comp.get(sym, 0.0)
            if remaining <= 0:
                break
            f = min(frac / remaining, 1.0) if remaining else 0
            create_host += f"set group all_atoms type/fraction {i+1} {f:.6f} {2000 + i}\n"
            remaining -= frac

    boundary = str(params.get("boundary") or "p p s")
    if boundary.strip() == "p p p":
        boundary = "p p s"
    ensemble = _ensemble_fix(params)
    dump, dump_mod = _dump_command(params, "dump.surface.*.lammpstrj")
    restart = _restart_block(params)
    crystal_note = _crystal_comment(material)

    insert_lines = []
    for i in range(n_impacts):
        fx = 0.3 + 0.4 * ((i * 0.37) % 1.0)
        fy = 0.3 + 0.4 * ((i * 0.61) % 1.0)
        insert_lines.append(
            f"create_atoms {ion_type} single {fx:.4f} {fy:.4f} {nz + 0.8} units lattice"
        )
    insert_block = "\n".join(insert_lines)

    script = textwrap.dedent(
        f"""\
        # Aegis-generated low-E surface MD (Phase-3 fuzz / erosion proxy)
        # Note: {n_impacts} ions are inserted together (simultaneous), not sequential fluence.
        # Fluence proxy: {n_impacts} × {ion} at {E} eV onto free surface (vacuum={vacuum} layers)
        {crystal_note}
        units metal
        dimension 3
        boundary {boundary}
        atom_style atomic

        lattice bcc {a}
        region box block 0 {nx} 0 {ny} 0 {nz_box} units lattice
        create_box {len(elems)} box
        {create_host}
        {masses}

        pair_style {pair_style}
        {pair_coeff}

        neighbor {params.get("neighbor_skin", 2.0)} bin
        neigh_modify delay 0 every 1 check yes

        velocity all create {T} {seed} mom yes rot yes
        {ensemble}
        run 500

        # Reference free surface BEFORE irradiation
        write_dump all custom dump.initial.lammpstrj id type x y z modify sort id

        # Insert low-E beam above the free surface
        {insert_block}
        group beam type {ion_type}
        velocity beam set {vx:.6f} {vy:.6f} {vz:.6f} units box

        reset_timestep 0
        thermo {int(params.get("thermo_every", 100))}
        thermo_style custom step temp pe ke etotal
        {dump}
        {dump_mod}
        {restart}
        run 0
        timestep {dt}
        run {steps}

        write_data final.data
        print "Aegis surface MD finished"
        """
    )
    script = script.replace(
        f"lattice bcc {a}\n",
        f"{_lattice_line(a, params)}\n",
        1,
    )
    path.write_text(script, encoding="utf-8")
    return path


def _lattice_direction_unit(direction: str, seed: int) -> tuple[float, float, float]:
    """Unit vector for pre-defined BCC lattice directions."""
    key = direction.strip().lower().replace(",", " ")
    presets = {
        "100": (1.0, 0.0, 0.0),
        "010": (0.0, 1.0, 0.0),
        "001": (0.0, 0.0, 1.0),
        "110": (1.0, 1.0, 0.0),
        "101": (1.0, 0.0, 1.0),
        "011": (0.0, 1.0, 1.0),
        "111": (1.0, 1.0, 1.0),
        "<100>": (1.0, 0.0, 0.0),
        "<110>": (1.0, 1.0, 0.0),
        "<111>": (1.0, 1.0, 1.0),
        "[100]": (1.0, 0.0, 0.0),
        "[110]": (1.0, 1.0, 0.0),
        "[111]": (1.0, 1.0, 1.0),
    }
    if key in presets:
        vx, vy, vz = presets[key]
    elif key == "random":
        return _direction_unit("random", seed)
    else:
        return _direction_unit(direction, seed)
    norm = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
    return vx / norm, vy / norm, vz / norm


def _interstitial_sites_lattice(
    *,
    geometry: str,
    count: int,
    nx: int,
    ny: int,
    nz: int,
    direction: tuple[float, float, float],
    a: float,
    offset_A: float,
) -> list[tuple[float, float, float, str]]:
    """Return list of (x,y,z in lattice units, kind) for interstitial inserts.

    kind is 'single' (one atom) or 'pair' markers handled by caller via paired sites.
    For dumbbell/crowdion we return pairs of positions as consecutive singles with kind 'sia'.
    """
    geom = geometry.strip().lower()
    ux, uy, uz = direction
    # Anchor near geometric center of the box (lattice units)
    cx, cy, cz = nx * 0.5, ny * 0.5, nz * 0.5
    # Perpendicular spread basis
    if abs(ux) < 0.9:
        px, py, pz = 0.0, -uz, uy
    else:
        px, py, pz = -uy, ux, 0.0
    pn = math.sqrt(px * px + py * py + pz * pz) or 1.0
    px, py, pz = px / pn, py / pn, pz / pn
    qx, qy, qz = uy * pz - uz * py, uz * px - ux * pz, ux * py - uy * px

    half = (offset_A / a) if a > 0 else 0.25
    sites: list[tuple[float, float, float, str]] = []

    for i in range(count):
        # Spread along a small grid in the plane ⊥ direction
        sx = ((i % 3) - 1) * 0.35
        sy = (((i // 3) % 3) - 1) * 0.35
        sz = ((i // 9) % 3) * 0.2
        base_x = cx + sx * px + sy * qx + sz * ux
        base_y = cy + sx * py + sy * qy + sz * uy
        base_z = cz + sx * pz + sy * qz + sz * uz
        # Clamp into box with small margin
        base_x = min(max(base_x, 0.25), nx - 0.25)
        base_y = min(max(base_y, 0.25), ny - 0.25)
        base_z = min(max(base_z, 0.25), nz - 0.25)

        if geom in {"dumbbell", "crowdion"}:
            # Pair of atoms along the lattice direction (SIA dumbbell / crowdion seed)
            sep = half if geom == "dumbbell" else half * 1.6
            sites.append((base_x + sep * ux, base_y + sep * uy, base_z + sep * uz, "pair"))
            sites.append((base_x - sep * ux, base_y - sep * uy, base_z - sep * uz, "pair"))
        elif geom == "tetrahedral":
            # BCC tetrahedral offset ~ (0.5, 0.25, 0) in a unit cell, oriented with direction
            ox, oy, oz = 0.5 * ux + 0.25 * px, 0.5 * uy + 0.25 * py, 0.5 * uz + 0.25 * pz
            sites.append((base_x + ox * 0.5, base_y + oy * 0.5, base_z + oz * 0.5, "single"))
        else:
            # Default octahedral: midway along the chosen lattice direction from a lattice point
            sites.append(
                (
                    base_x + 0.5 * ux,
                    base_y + 0.5 * uy,
                    base_z + 0.5 * uz,
                    "single",
                )
            )
    return sites


def write_interstitial_input(
    path: Path,
    *,
    material: dict[str, Any],
    potential: dict[str, Any],
    params: dict[str, Any],
    potential_file: str,
) -> Path:
    """Insert interstitial impurities / SIA seeds along pre-defined BCC lattice directions.

    Material composition remains substitutional on the host lattice. Interstitials are
    extra atoms (octahedral / tetrahedral / dumbbell / crowdion) oriented along
    <100>, <110>, <111>, or a custom Miller vector.
    """
    host_elems = _elements_line(material["composition"])
    if not host_elems:
        host_elems = ["W"]
    species = str(params.get("interstitial_species") or "He")
    elems = list(host_elems)
    if species not in elems:
        elems.append(species)

    a = float(material.get("lattice_constant_A", 3.165))
    nx, ny, nz = int(params["nx"]), int(params["ny"]), int(params["nz"])
    seed = int(params["seed"])
    dt = float(params["timestep_fs"])
    steps = int(params["max_steps"])
    T = float(params["temperature_K"])
    count = max(1, int(params.get("interstitial_count", 1)))
    direction_s = str(params.get("interstitial_direction", "111"))
    geometry = str(params.get("interstitial_geometry", "octahedral"))
    offset = params.get("interstitial_offset_A")
    offset_A = float(offset) if offset not in (None, "") else 0.25 * a
    E_kick = float(params.get("interstitial_energy_eV", 0.0) or 0.0)

    pair_style = potential["lammps_pair_style"]
    pair_coeff = render_pair_coeff(
        potential.get("pair_coeff_template", "pair_coeff * * {file} {elements}"),
        potential_file,
        elems,
    )
    masses = "\n".join(f"mass {i+1} {_approx_mass(sym)}" for i, sym in enumerate(elems))
    create = _create_atoms_block(material, host_elems)
    ensemble = _ensemble_fix(params)
    dump, dump_mod = _dump_command(params, "dump.interstitial.*.lammpstrj")
    restart = _restart_block(params)
    crystal_note = _crystal_comment(material)

    ux, uy, uz = _lattice_direction_unit(direction_s, seed)
    sites = _interstitial_sites_lattice(
        geometry=geometry,
        count=count,
        nx=nx,
        ny=ny,
        nz=nz,
        direction=(ux, uy, uz),
        a=a,
        offset_A=offset_A,
    )
    ityp = elems.index(species) + 1
    insert_lines = [
        f"create_atoms {ityp} single {x:.6f} {y:.6f} {z:.6f} units lattice"
        for x, y, z, _kind in sites
    ]
    insert_block = "\n".join(insert_lines)

    kick_block = ""
    if E_kick > 0:
        mass_i = _approx_mass(species)
        speed = math.sqrt(2.0 * E_kick / mass_i) * 98.226947
        kick_block = textwrap.dedent(
            f"""\
            group interstitial_atoms type {ityp}
            velocity interstitial_atoms set {ux * speed:.6f} {uy * speed:.6f} {uz * speed:.6f} units box
            """
        )

    n_atoms_inserted = len(sites)
    script = textwrap.dedent(
        f"""\
        # Aegis-generated interstitial insertion along lattice direction
        # species={species} count≈{count} geometry={geometry} direction={direction_s}
        # atoms_created={n_atoms_inserted} (dumbbell/crowdion create a pair per count)
        # Host composition is SUBSTITUTIONAL; these inserts are EXTRA interstitial atoms.
        {crystal_note}
        units metal
        dimension 3
        boundary {params.get("boundary", "p p p")}
        atom_style atomic

        lattice bcc {a}
        region box block 0 {nx} 0 {ny} 0 {nz} units lattice
        create_box {len(elems)} box
        {create}
        {masses}

        pair_style {pair_style}
        {pair_coeff}

        neighbor {params.get("neighbor_skin", 2.0)} bin
        neigh_modify delay 0 every 1 check yes

        velocity all create {T} {seed} mom yes rot yes
        {ensemble}
        run 500

        # Reference BEFORE interstitial insertion
        write_dump all custom dump.initial.lammpstrj id type x y z modify sort id

        # Insert interstitials oriented along the chosen lattice direction
        {insert_block}
        {kick_block}

        reset_timestep 0
        thermo {int(params.get("thermo_every", 100))}
        thermo_style custom step temp pe ke etotal
        {dump}
        {dump_mod}
        {restart}
        run 0
        timestep {dt}
        run {steps}

        write_data final.data
        print "Aegis interstitial insertion finished"
        """
    )
    script = script.replace(
        f"lattice bcc {a}\n",
        f"{_lattice_line(a, params)}\n",
        1,
    )
    path.write_text(script, encoding="utf-8")
    return path


def _create_atoms_block(material: dict[str, Any], elems: list[str]) -> str:
    """Random substitutional alloy on BCC lattice for multi-element materials."""
    if len(elems) == 1:
        return "create_atoms 1 box"
    comp = {c["symbol"]: c["atomic_percent"] / 100.0 for c in material["composition"]}
    lines = ["create_atoms 1 box", "group all_atoms type 1"]
    remaining = 1.0
    for i, sym in enumerate(elems):
        typ = i + 1
        frac = comp.get(sym, 0.0)
        if i == 0:
            continue
        if remaining <= 0:
            break
        f = min(frac / remaining, 1.0) if remaining else 0
        lines.append(f"set group all_atoms type/fraction {typ} {f:.6f} {1000 + i}")
        remaining -= frac
    return "\n".join(lines)


def _approx_mass(symbol: str) -> float:
    table = {
        "H": 1.008,
        "D": 2.014,
        "T": 3.016,
        "He": 4.0026,
        "C": 12.011,
        "V": 50.942,
        "Cr": 51.996,
        "Fe": 55.845,
        "Mo": 95.95,
        "Ta": 180.95,
        "W": 183.84,
        "Re": 186.21,
    }
    return table.get(symbol, 1.0)
