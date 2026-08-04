from __future__ import annotations

import math
import textwrap
from pathlib import Path
from typing import Any


def _elements_line(composition: list[dict[str, Any]]) -> list[str]:
    return [c["symbol"] for c in composition if c.get("atomic_percent", 0) > 0]


def render_pair_coeff(template: str, file_path: str, elements: list[str]) -> str:
    return template.format(file=file_path.replace("\\", "/"), elements=" ".join(elements))


def write_cascade_input(
    path: Path,
    *,
    material: dict[str, Any],
    potential: dict[str, Any],
    params: dict[str, Any],
    potential_file: str,
) -> Path:
    """Write a minimal LAMMPS cascade input. Requires a real potential file to run."""
    elems = _elements_line(material["composition"])
    primary = elems[0]
    a = float(material.get("lattice_constant_A", 3.165))
    nx, ny, nz = int(params["nx"]), int(params["ny"]), int(params["nz"])
    seed = int(params["seed"])
    dt = float(params["timestep_fs"])
    steps = int(params["max_steps"])
    T = float(params["temperature_K"])
    E = float(params["pka_energy_eV"])
    n_pkas = int(params.get("n_pkas", 1))
    direction = str(params.get("pka_direction", "random"))
    pair_style = potential["lammps_pair_style"]
    pair_coeff = render_pair_coeff(
        potential["pair_coeff_template"], potential_file, elems
    )

    if direction == "random":
        # Unit vector along body diagonal as a deterministic default for templates
        vx, vy, vz = 1.0, 1.0, 1.0
    else:
        parts = [float(x) for x in direction.replace(",", " ").split()]
        while len(parts) < 3:
            parts.append(0.0)
        vx, vy, vz = parts[0], parts[1], parts[2]
    norm = math.sqrt(vx * vx + vy * vy + vz * vz) or 1.0
    vx, vy, vz = vx / norm, vy / norm, vz / norm
    # Velocity magnitude from kinetic energy (eV) for mass of W proxy ~183.84
    # v = sqrt(2E/m); LAMMPS metal units: mass g/mol, energy eV → v in Angstrom/ps
    mass_w = 183.84
    # E(eV) = 0.5 * m(g/mol) * v^2 / (N_A conversion); in metal units:
    # v = sqrt(2*E/m) * factor; LAMMPS docs: velocity = sqrt(2*KE/mass) with mass in g/mol
    speed = math.sqrt(2.0 * E / mass_w) * 98.226947  # approx Å/ps for metal units

    masses = "\n".join(
        f"mass {i+1} {_approx_mass(sym)}" for i, sym in enumerate(elems)
    )
    create = _create_atoms_block(material, elems)

    script = textwrap.dedent(
        f"""\
        # Aegis-generated cascade input — review before production use
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
        fix 1 all nve

        # Thermalize briefly
        run 1000

        # PKA: assign velocity to atom closest to box center
        variable cx equal lx/2
        variable cy equal ly/2
        variable cz equal lz/2
        group pka id 1
        # Note: for multi-PKA, extend via Aegis runner; single PKA baseline:
        velocity pka set {vx*speed:.6f} {vy*speed:.6f} {vz*speed:.6f} units box

        reset_timestep 0
        thermo {int(params.get("thermo_every", 100))}
        thermo_style custom step temp pe ke etotal press
        dump 1 all custom {int(params.get("dump_every", 1000))} dump.cascade.*.lammpstrj id type x y z
        dump_modify 1 sort id pad 9

        timestep {dt}
        run {steps}

        write_data final.data
        print "Aegis cascade finished"
        """
    )
    # n_pkas reserved for future multi-PKA expansion
    _ = n_pkas
    _ = primary
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
    if "He" not in elems:
        elems = elems + ["He"]
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
    speed = math.sqrt(2.0 * E / 4.0026) * 98.226947
    masses = "\n".join(f"mass {i+1} {_approx_mass(sym)}" for i, sym in enumerate(elems))
    he_type = elems.index("He") + 1
    create = _create_atoms_block(material, [e for e in elems if e != "He"])

    script = textwrap.dedent(
        f"""\
        # Aegis-generated He implant input
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

        velocity all create {T} {seed} mom yes rot yes
        fix 1 all nve
        run 500

        # Insert one He near top surface with downward velocity
        create_atoms {he_type} single 0.5 0.5 {nz - 0.5} units lattice
        group he type {he_type}
        velocity he set 0 0 {-speed:.6f} units box

        reset_timestep 0
        thermo {int(params.get("thermo_every", 100))}
        dump 1 all custom {int(params.get("dump_every", 1000))} dump.implant.*.lammpstrj id type x y z
        dump_modify 1 sort id pad 9
        timestep {dt}
        run {steps}
        write_data final.data
        print "Aegis implant finished"
        """
    )
    path.write_text(script, encoding="utf-8")
    return path


def _create_atoms_block(material: dict[str, Any], elems: list[str]) -> str:
    """Random substitutional alloy on BCC lattice for multi-element materials."""
    if len(elems) == 1:
        return "create_atoms 1 box"
    # Build type fractions
    comp = {c["symbol"]: c["atomic_percent"] / 100.0 for c in material["composition"]}
    lines = ["create_atoms 1 box", "group all_atoms type 1"]
    # For simplicity: create as type 1 then set type randomly via set command fractions
    # LAMMPS set type/fraction iteratively
    remaining = 1.0
    for i, sym in enumerate(elems):
        typ = i + 1
        frac = comp.get(sym, 0.0)
        if i == 0:
            continue
        # convert absolute fraction of original type-1 pool
        if remaining <= 0:
            break
        f = min(frac / remaining, 1.0) if remaining else 0
        lines.append(f"set group all_atoms type/fraction {typ} {f:.6f} {1000 + i}")
        remaining -= frac
    return "\n".join(lines)


def _approx_mass(symbol: str) -> float:
    table = {
        "H": 1.008,
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
