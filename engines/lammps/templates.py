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

    # Multi-PKA: repeat center-ish kick with optional delay between events
    pka_blocks: list[str] = []
    for i in range(n_pkas):
        s = seed + i * 9973
        dvx, dvy, dvz = _direction_unit(str(params.get("pka_direction", "random")), s)
        sp = speed
        pka_blocks.append(
            textwrap.dedent(
                f"""\
                # PKA event {i + 1}/{n_pkas} species={primary}
                variable cx equal lx/2
                variable cy equal ly/2
                variable cz equal lz/2
                # Closest atom to geometric center (proxy for stated PKA site)
                variable pkaid equal 1
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
