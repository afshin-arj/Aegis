from __future__ import annotations

import json
import math
import textwrap
from pathlib import Path
from typing import Any

from lammps import crystal as crystal_reg
from lammps.polycrystal import build_polycrystal_meta, polycrystal_lammps_comment


def _norm_sym(symbol: str) -> str:
    s = str(symbol or "").strip()
    if not s:
        return ""
    if len(s) == 1:
        return s.upper()
    return s[0].upper() + s[1:].lower()


def _elements_line(composition: list[dict[str, Any]]) -> list[str]:
    out: list[str] = []
    for c in composition:
        if float(c.get("atomic_percent", 0) or 0) <= 0:
            continue
        sym = _norm_sym(str(c.get("symbol") or ""))
        if sym:
            out.append(sym)
    return out


def _elem_index(elems: list[str], symbol: str) -> int:
    """1-based type index; case-insensitive match."""
    want = _norm_sym(symbol).lower()
    for i, e in enumerate(elems):
        if e.lower() == want:
            return i + 1
    raise ValueError(f"species '{symbol}' not in type list ({', '.join(elems)})")


def _has_elem(elems: list[str], symbol: str) -> bool:
    want = _norm_sym(symbol).lower()
    return any(e.lower() == want for e in elems)


def render_pair_coeff(template: str, file_path: str, elements: list[str]) -> str:
    """Format pair_coeff, always mapping types to the live element list order."""
    import re

    file_norm = file_path.replace("\\", "/")
    elems_str = " ".join(elements)
    if "{elements}" in template:
        return template.format(file=file_norm, elements=elems_str)
    # Catalog entries often bake tokens like ``... {file} W He`` — replace trailing
    # element names with the live type order so implant/surface ions stay consistent.
    formatted = template.format(file=file_norm)
    m = re.match(r"^(pair_coeff\s+\S+\s+\S+\s+\S+)\s*(.*)$", formatted.strip())
    if m:
        return f"{m.group(1)} {elems_str}".rstrip() if elems_str else m.group(1)
    return f"{formatted} {elems_str}".strip() if elems_str else formatted


def _direction_unit(direction: str, seed: int, crystal: str = "bcc") -> tuple[float, float, float]:
    return crystal_reg.direction_unit(crystal, direction, seed)


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


def _lattice_line(material: dict[str, Any], params: dict[str, Any]) -> str:
    return crystal_reg.lattice_line(material, params)


def _crystal_comment(material: dict[str, Any]) -> str:
    return crystal_reg.crystal_comment(material)


def _snap_lattice_site(
    material: dict[str, Any],
    fx: float,
    fy: float,
    fz: float,
    nx: int,
    ny: int,
    nz: int,
) -> tuple[float, float, float]:
    return crystal_reg.snap_lattice_site(
        str(material.get("crystal", "bcc")),
        fx,
        fy,
        fz,
        nx,
        ny,
        nz,
    )


def _poly_preamble(path: Path, material: dict[str, Any], params: dict[str, Any]) -> str:
    """Comment block for nanostructures. Real atoms come from structure.data when built."""
    kind = str(
        getattr(params.get("structure_kind"), "value", params.get("structure_kind", "single_crystal"))
    ).lower()
    if kind in {"", "single_crystal"}:
        return ""
    meta_path = path.parent / "structure_meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            backend = meta.get("backend", "?")
            natoms = meta.get("natoms", meta.get("n_atoms", "?"))
            return (
                f"# structure_kind={kind} via {backend} → read_data structure.data "
                f"(natoms≈{natoms}; see structure_meta.json)\n"
            )
        except Exception:  # noqa: BLE001
            pass
    if kind == "polycrystal":
        # Legacy seed metadata only — not a substitute for structure.data
        meta = build_polycrystal_meta(
            path.parent,
            nx=int(params["nx"]),
            ny=int(params["ny"]),
            nz=int(params["nz"]),
            n_grains=int(params.get("poly_n_grains", 4)),
            seed=int(params.get("poly_seed", params.get("seed", 42))),
            texture=str(params.get("poly_texture", "random")),
            crystal=str(material.get("crystal", "bcc")),
            a=float(material.get("lattice_constant_A", 3.165)),
        )
        return polycrystal_lammps_comment(meta)
    return f"# structure_kind={kind} — expect structure.data from Aegis builder\n"


def plan_cascade_stages(
    *,
    energy_eV: float,
    timestep_fs: float,
    max_steps: int,
    dump_every: int,
    auto: bool,
) -> dict[str, Any]:
    """Heuristic cascade timeline so growth/peak/quench/residual are all sampled.

    Uses energy-scaled *fractions* of a bounded step budget so tiny timesteps cannot
    explode into multi-million-step local DEMO runs. Not a peak detector — a schedule
    that makes OVITO scrubbing cover each physical regime.
    """
    dump_every = max(1, int(dump_every))
    max_steps = max(1, int(max_steps))
    if not auto:
        return {
            "auto": False,
            "total_steps": max_steps,
            "extended_max_steps": False,
            "note": "Single continuous run; stage names are not applied.",
            "stages": [
                {
                    "id": "full",
                    "label": "Full cascade window",
                    "steps": max_steps,
                    "dump_every": dump_every,
                    "timestep_start": 0,
                    "timestep_end": max_steps,
                }
            ],
        }

    dt_ps = max(float(timestep_fs), 1e-9) * 1e-3  # fs → ps
    scale = max(1.0, (max(energy_eV, 1.0) / 5000.0) ** 0.35)
    # ~14 ps metallic cascade window at 5 keV, weakly energy-scaled
    target_ps = 14.0 * scale
    suggested = max(max_steps, int(round(target_ps / dt_ps)))
    # Bound extension for local workbench (avoid millions of steps if dt is tiny)
    hard_cap = max(max_steps, min(200_000, max_steps * 5))
    total = min(suggested, hard_cap)
    extended = total > max_steps

    # Fractions: brief growth, peak spike, long quench, residual settle
    fracs = [("growth", "PKA / cascade growth", 0.08), ("peak", "Cascade peak (thermal spike)", 0.17), ("quench", "Quench / recombination", 0.40), ("residual", "Residual defects", 0.35)]
    raw = [max(10, int(round(total * f))) for _, _, f in fracs]
    # Fix rounding so sum == total
    raw[-1] = max(10, total - sum(raw[:-1]))

    def denser(base: int, stage_steps: int, target_frames: int) -> int:
        return max(1, min(base, max(1, stage_steps // max(target_frames, 1))))

    densify = [
        denser(dump_every, raw[0], 25),
        denser(max(1, dump_every // 5), raw[1], 40),
        denser(dump_every, raw[2], 30),
        denser(max(dump_every, dump_every * 2), raw[3], 20),
    ]

    stages = []
    t0 = 0
    for (sid, label, _), nrun, every in zip(fracs, raw, densify):
        stages.append(
            {
                "id": sid,
                "label": label,
                "steps": nrun,
                "dump_every": every,
                "timestep_start": t0,
                "timestep_end": t0 + nrun,
            }
        )
        t0 += nrun

    return {
        "auto": True,
        "total_steps": t0,
        "extended_max_steps": extended,
        "energy_eV": energy_eV,
        "timestep_fs": timestep_fs,
        "target_ps": target_ps,
        "scale": scale,
        "note": (
            "Heuristic stage schedule for metallic cascades (bounded step budget). "
            "Dense dumps during growth/peak so OVITO can scrub PKA → peak → recombination → residual."
        ),
        "stages": stages,
    }


def _geometry_block(
    *,
    material: dict[str, Any],
    params: dict[str, Any],
    elems: list[str],
    structure_file: str | None,
) -> str:
    """Lattice+create_atoms, or read_data for prebuilt nanostructures."""
    nx, ny, nz = int(params["nx"]), int(params["ny"]), int(params["nz"])
    masses = "\n".join(f"mass {i+1} {_approx_mass(sym)}" for i, sym in enumerate(elems))
    if structure_file:
        return textwrap.dedent(
            f"""\
            # Prebuilt nanostructure (ASE/Atomsk/import)
            read_data {structure_file}
            {masses}
            """
        )
    lattice_cmd = _lattice_line(material, params)
    create = _create_atoms_block(material, elems)
    return textwrap.dedent(
        f"""\
        {lattice_cmd}
        region box block 0 {nx} 0 {ny} 0 {nz} units lattice
        create_box {len(elems)} box
        {create}
        {masses}
        """
    )


def write_cascade_input(
    path: Path,
    *,
    material: dict[str, Any],
    potential: dict[str, Any],
    params: dict[str, Any],
    potential_file: str,
    structure_file: str | None = None,
) -> Path:
    """Write a LAMMPS cascade input from UI run parameters."""
    elems = _elements_line(material["composition"])
    primary = _norm_sym(str(params.get("pka_species") or (elems[0] if elems else "W")))
    if not elems:
        raise ValueError("Material composition is empty — cannot write cascade input")
    if not _has_elem(elems, primary):
        raise ValueError(
            f"Cascade pka_species '{primary}' is not in host composition ({', '.join(elems)})"
        )
    a = float(material.get("lattice_constant_A", 3.165))
    nx, ny, nz = int(params["nx"]), int(params["ny"]), int(params["nz"])
    seed = int(params["seed"])
    dt = float(params["timestep_fs"])
    steps = int(params["max_steps"])
    T = float(params["temperature_K"])
    E = float(params["pka_energy_eV"])
    n_pkas = max(1, int(params.get("n_pkas", 1)))
    delay = max(0, int(params.get("pka_delay_steps", 0)))
    site_mode = str(params.get("pka_site") or "center").strip().lower()
    auto_stages = bool(params.get("cascade_auto_stages", True))
    dump_every = int(params.get("dump_every", 1000))
    use_box_units = bool(structure_file)

    pair_style = potential["lammps_pair_style"]
    pair_coeff = render_pair_coeff(
        potential["pair_coeff_template"], potential_file, elems
    )
    mass_pka = _approx_mass(primary)
    speed = math.sqrt(2.0 * E / mass_pka) * 98.226947

    ensemble = _ensemble_fix(params)
    restart = _restart_block(params)
    crystal_note = _crystal_comment(material)
    poly_note = _poly_preamble(path, material, params)
    geometry = _geometry_block(
        material=material, params=params, elems=elems, structure_file=structure_file
    )

    schedule = plan_cascade_stages(
        energy_eV=E,
        timestep_fs=dt,
        max_steps=steps,
        dump_every=dump_every,
        auto=auto_stages,
    )
    # Persist timeline next to input for OVITO / UI
    timeline_path = path.parent / "cascade_timeline.json"
    timeline_path.write_text(json.dumps(schedule, indent=2), encoding="utf-8")

    # PKA site targets in lattice units
    pka_blocks: list[str] = []
    site_notes: list[str] = []
    for i in range(n_pkas):
        s = seed + i * 9973
        dvx, dvy, dvz = _direction_unit(
            str(params.get("pka_direction", "random")),
            s,
            str(material.get("crystal", "bcc")),
        )
        if site_mode == "random":
            # Deterministic pseudo-random fractional position from seed
            rx = (math.sin(s * 12.9898) * 43758.5453) % 1.0
            ry = (math.sin(s * 78.233) * 43758.5453) % 1.0
            rz = (math.sin(s * 39.425) * 43758.5453) % 1.0
            # Keep away from boundaries a bit
            fx, fy, fz = 0.15 + 0.7 * abs(rx), 0.15 + 0.7 * abs(ry), 0.15 + 0.7 * abs(rz)
        elif site_mode == "coords":
            fx = float(params.get("pka_frac_x", 0.5))
            fy = float(params.get("pka_frac_y", 0.5))
            fz = float(params.get("pka_frac_z", 0.5))
            # Slightly jitter multi-PKA so they don't all hit the same site
            if n_pkas > 1:
                fx = min(0.95, max(0.05, fx + 0.03 * ((i % 3) - 1)))
                fy = min(0.95, max(0.05, fy + 0.03 * (((i // 3) % 3) - 1)))
                fz = min(0.95, max(0.05, fz + 0.02 * (i % 2)))
        else:
            fx = fy = fz = 0.5
            if n_pkas > 1:
                fx = 0.35 + 0.3 * ((i % 3) / 2)
                fy = 0.35 + 0.3 * (((i // 3) % 3) / 2)
                fz = 0.5

        sx, sy, sz = _snap_lattice_site(material, fx, fy, fz, nx, ny, nz)
        # Prebuilt structures have no active lattice; use box Å (cubic approx a*nx).
        if use_box_units:
            cx, cy, cz = sx * a, sy * a, sz * a
            rad, rad2, rad3 = 0.45 * a, 0.85 * a, 2.5 * a
            units = "box"
            site_notes.append(
                f"PKA{i+1}: frac≈({fx:.3f},{fy:.3f},{fz:.3f}) → box Å ({cx:.3f},{cy:.3f},{cz:.3f})"
            )
        else:
            cx, cy, cz = sx, sy, sz
            rad, rad2, rad3 = 0.45, 0.85, 2.5
            units = "lattice"
            site_notes.append(
                f"PKA{i+1}: frac≈({fx:.3f},{fy:.3f},{fz:.3f}) → lattice ({sx:.3f},{sy:.3f},{sz:.3f})"
            )
        pka_type = _elem_index(elems, primary)
        pka_blocks.append(
            textwrap.dedent(
                f"""\
                # PKA event {i + 1}/{n_pkas} species={primary} type={pka_type} site={site_mode}
                # Target ({cx:.6f} {cy:.6f} {cz:.6f}) units {units}; nearest host of PKA type
                region pka_pick_{i} sphere {cx:.6f} {cy:.6f} {cz:.6f} {rad:.4f} units {units}
                group pka_reg_{i} region pka_pick_{i}
                group pka_type_{i} type {pka_type}
                group pka_{i} intersect pka_reg_{i} pka_type_{i}
                # Expand search if FP miss; abort if still empty (alloy minority PKA)
                variable npka_{i} equal count(pka_{i})
                if "${{npka_{i}}} == 0" then &
                  "region pka_pick_{i} sphere {cx:.6f} {cy:.6f} {cz:.6f} {rad2:.4f} units {units}" &
                  "group pka_reg_{i} region pka_pick_{i}" &
                  "group pka_{i} intersect pka_reg_{i} pka_type_{i}"
                variable npka_{i} equal count(pka_{i})
                if "${{npka_{i}}} == 0" then &
                  "region pka_pick_{i} sphere {cx:.6f} {cy:.6f} {cz:.6f} {rad3:.4f} units {units}" &
                  "group pka_reg_{i} region pka_pick_{i}" &
                  "group pka_{i} intersect pka_reg_{i} pka_type_{i}"
                variable npka_{i} equal count(pka_{i})
                if "${{npka_{i}}} == 0" then &
                  "print 'Aegis ERROR: no type-{pka_type} ({primary}) atom near PKA site {i+1}'" &
                  "quit 1"
                velocity pka_{i} set {dvx * speed:.6f} {dvy * speed:.6f} {dvz * speed:.6f} units box
                """
            )
        )
        if i < n_pkas - 1 and delay > 0:
            pka_blocks.append(f"run {delay}")

    pka_script = "\n".join(pka_blocks)
    sites_comment = "\n".join(f"        # {n}" for n in site_notes)

    # Staged dynamics block
    stage_lines: list[str] = []
    if schedule["auto"]:
        for idx, st in enumerate(schedule["stages"]):
            every = int(st["dump_every"])
            nrun = int(st["steps"])
            sid = st["id"]
            undump = "undump 1\n" if idx > 0 else ""
            stage_lines.append(
                textwrap.dedent(
                    f"""\
                    # --- Stage: {st['label']} ({sid}) steps={nrun} dump_every={every} ---
                    print "Aegis cascade stage start: {sid}"
                    {undump}dump 1 all custom {every} dump.cascade.*.lammpstrj id type x y z
                    dump_modify 1 sort id pad 9
                    write_dump all custom dump.stage.{sid}.lammpstrj id type x y z modify sort id
                    run {nrun}
                    print "Aegis cascade stage end: {sid}"
                    """
                )
            )
        dynamics = "\n".join(stage_lines)
    else:
        dump, dump_mod = _dump_command(params, "dump.cascade.*.lammpstrj")
        dynamics = textwrap.dedent(
            f"""\
            {dump}
            {dump_mod}
            run 0
            timestep {dt}
            run {schedule['total_steps']}
            """
        )

    if schedule["auto"]:
        dynamics_header = textwrap.dedent(
            f"""\
            run 0
            timestep {dt}
            {dynamics}
            """
        )
    else:
        dynamics_header = dynamics

    script = textwrap.dedent(
        f"""\
        # Aegis-generated cascade input — review before production use
        {crystal_note}
        {poly_note}
        # Cascade timeline written to cascade_timeline.json (OVITO stage guide)
        # Auto stages: {schedule['auto']} total_steps={schedule['total_steps']} extended={schedule.get('extended_max_steps')}
{sites_comment}
        units metal
        dimension 3
        boundary {params.get("boundary", "p p p")}
        atom_style atomic

        {geometry}

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
        {restart}

        {pka_script}
        # Capture cascade t=0 immediately after PKA kick(s)
        {dynamics_header}

        write_data final.data
        print "Aegis cascade finished"
        """
    )
    path.write_text(script, encoding="utf-8")
    # Human-readable OVITO note
    (path.parent / "cascade_stages_OVITO.txt").write_text(
        _format_ovito_guide(schedule, site_notes),
        encoding="utf-8",
    )
    return path


def _format_ovito_guide(schedule: dict[str, Any], site_notes: list[str]) -> str:
    lines = [
        "Aegis cascade stage guide (open dump.cascade.*.lammpstrj and dump.stage.*.lammpstrj in OVITO)",
        "",
        schedule.get("note", ""),
        f"Total cascade steps after PKA: {schedule.get('total_steps')}",
        f"max_steps was extended: {schedule.get('extended_max_steps')}",
        "",
        "PKA sites:",
        *[f"  - {n}" for n in site_notes],
        "",
        "Stages (timestep ranges after reset_timestep 0):",
    ]
    for st in schedule.get("stages") or []:
        lines.append(
            f"  - {st.get('id')}: {st.get('label')}  "
            f"steps {st.get('timestep_start')}–{st.get('timestep_end')}  "
            f"dump_every={st.get('dump_every')}"
        )
        if st.get("id") not in {"full"}:
            lines.append(f"    marker dump: dump.stage.{st.get('id')}.lammpstrj")
    lines.extend(
        [
            "",
            "Suggested OVITO workflow:",
            "  1. Load dump.initial.lammpstrj as the pristine lattice.",
            "  2. Load dump.cascade.*.lammpstrj as the time series (growth→peak→quench→residual).",
            "  3. Optionally overlay dump.stage.*.lammpstrj frames as bookmarks for each regime.",
            "  4. Optional: run OVITO DXA on residual frames (Aegis Results → DXA when OVITO is installed).",
            "",
        ]
    )
    return "\n".join(lines) + "\n"


def write_implant_input(
    path: Path,
    *,
    material: dict[str, Any],
    potential: dict[str, Any],
    params: dict[str, Any],
    potential_file: str,
    structure_file: str | None = None,
) -> Path:
    elems = _elements_line(material["composition"])
    ion = _norm_sym(str(params.get("ion_type", "He")))
    if not _has_elem(elems, ion):
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

    ion_type = _elem_index(elems, ion)
    host_elems = [e for e in elems if e.lower() != ion.lower()] or elems[:1]
    ensemble = _ensemble_fix(params)
    dump, dump_mod = _dump_command(params, "dump.implant.*.lammpstrj")
    restart = _restart_block(params)
    crystal_note = _crystal_comment(material)
    geometry = _geometry_block(
        material=material, params=params, elems=host_elems, structure_file=structure_file
    )
    # Extra type for ion when host-only geometry used single-crystal create_box size
    if structure_file:
        # read_data already created the box; ensure ion type mass + lattice for inserts
        lattice_cmd = _lattice_line(material, params)
        geometry = (
            geometry
            + f"mass {ion_type} {_approx_mass(ion)}\n"
            + f"{lattice_cmd}\n"
        )
    else:
        # Recreate with full type count including ion
        geometry = _geometry_block(
            material=material, params=params, elems=elems, structure_file=None
        )
        # Replace host-only create with host create inside full box
        create = _create_atoms_block(material, host_elems)
        masses = "\n".join(f"mass {i+1} {_approx_mass(sym)}" for i, sym in enumerate(elems))
        lattice_cmd = _lattice_line(material, params)
        geometry = textwrap.dedent(
            f"""\
            {lattice_cmd}
            region box block 0 {nx} 0 {ny} 0 {nz} units lattice
            create_box {len(elems)} box
            {create}
            {masses}
            """
        )

    insert_lines = []
    for i in range(ion_count):
        # Spread ions slightly in xy for multi-ion proxy
        fx = 0.5 + 0.05 * ((i % 3) - 1)
        fy = 0.5 + 0.05 * (((i // 3) % 3) - 1)
        if structure_file:
            # Box Å above estimated top of nx*a × ny*a × nz*a cell
            bx, by, bz = fx * nx * a, fy * ny * a, (nz - 0.5) * a
            insert_lines.append(
                f"create_atoms {ion_type} single {bx:.4f} {by:.4f} {bz:.4f} units box"
            )
        else:
            insert_lines.append(
                f"create_atoms {ion_type} single {fx:.3f} {fy:.3f} {nz - 0.5} units lattice"
            )
    insert_block = "\n".join(insert_lines)

    # Free Z avoids periodic wrap of injected ions (same default as surface mode).
    boundary = str(params.get("boundary") or "p p s")
    if boundary.strip() == "p p p":
        boundary = "p p s"

    script = textwrap.dedent(
        f"""\
        # Aegis-generated ion implant input
        {crystal_note}
        units metal
        dimension 3
        boundary {boundary}
        atom_style atomic

        {geometry}

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
    path.write_text(script, encoding="utf-8")
    return path


def write_surface_input(
    path: Path,
    *,
    material: dict[str, Any],
    potential: dict[str, Any],
    params: dict[str, Any],
    potential_file: str,
    structure_file: str | None = None,
) -> Path:
    """Low-E He/D free-surface MD with vacuum slab (Phase-3 fuzz/erosion proxy)."""
    elems = _elements_line(material["composition"])
    ion = _norm_sym(str(params.get("ion_type", "He")))
    if not _has_elem(elems, ion):
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
    ion_type = _elem_index(elems, ion)
    host_elems = [e for e in elems if e.lower() != ion.lower()] or elems[:1]
    lattice_cmd = _lattice_line(material, params)
    if structure_file:
        geometry = textwrap.dedent(
            f"""\
            # Prebuilt nanostructure (+ vacuum via change_box)
            read_data {structure_file}
            {masses}
            {lattice_cmd}
            change_box all z final 0 {(nz_box) * a:.6f} units box
            """
        )
    else:
        create_host = (
            f"region substrate block 0 {nx} 0 {ny} 0 {nz} units lattice\n"
            f"{_create_atoms_block(material, host_elems, region='substrate')}"
        )
        geometry = textwrap.dedent(
            f"""\
            {lattice_cmd}
            region box block 0 {nx} 0 {ny} 0 {nz_box} units lattice
            create_box {len(elems)} box
            {create_host}
            {masses}
            """
        )

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
        if structure_file:
            bx, by, bz = fx * nx * a, fy * ny * a, (nz + 0.8) * a
            insert_lines.append(
                f"create_atoms {ion_type} single {bx:.4f} {by:.4f} {bz:.4f} units box"
            )
        else:
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

        {geometry}

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
    path.write_text(script, encoding="utf-8")
    return path


def _lattice_direction_unit(direction: str, seed: int, crystal: str = "bcc") -> tuple[float, float, float]:
    """Unit vector for crystal-aware lattice directions."""
    return crystal_reg.direction_unit(crystal, direction, seed)


def _interstitial_sites_lattice(
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
    return crystal_reg.interstitial_sites_lattice(
        crystal=crystal,
        geometry=geometry,
        count=count,
        nx=nx,
        ny=ny,
        nz=nz,
        direction=direction,
        a=a,
        offset_A=offset_A,
    )


def write_interstitial_input(
    path: Path,
    *,
    material: dict[str, Any],
    potential: dict[str, Any],
    params: dict[str, Any],
    potential_file: str,
    structure_file: str | None = None,
) -> Path:
    """Insert interstitial impurities / SIA seeds along crystal-aware lattice directions.

    Material composition remains substitutional on the host lattice. Interstitials are
    extra atoms (octahedral / tetrahedral / dumbbell / crowdion / basal) oriented along
    structure-appropriate directions.
    """
    host_elems = _elements_line(material["composition"])
    if not host_elems:
        host_elems = ["W"]
    species = _norm_sym(str(params.get("interstitial_species") or "He"))
    elems = list(host_elems)
    if not _has_elem(elems, species):
        elems.append(species)

    a = float(material.get("lattice_constant_A", 3.165))
    crystal = str(material.get("crystal", "bcc"))
    nx, ny, nz = int(params["nx"]), int(params["ny"]), int(params["nz"])
    seed = int(params["seed"])
    dt = float(params["timestep_fs"])
    steps = int(params["max_steps"])
    T = float(params["temperature_K"])
    count = max(1, int(params.get("interstitial_count", 1)))
    direction_s = str(params.get("interstitial_direction", "111"))
    geometry = crystal_reg.validate_interstitial_geometry(
        crystal, str(params.get("interstitial_geometry", "octahedral"))
    )
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
    ensemble = _ensemble_fix(params)
    dump, dump_mod = _dump_command(params, "dump.interstitial.*.lammpstrj")
    restart = _restart_block(params)
    crystal_note = _crystal_comment(material)
    poly_note = _poly_preamble(path, material, params)
    lattice_cmd = _lattice_line(material, params)
    if structure_file:
        geometry_block = textwrap.dedent(
            f"""\
            read_data {structure_file}
            {masses}
            {lattice_cmd}
            """
        )
    else:
        create = _create_atoms_block(material, host_elems)
        geometry_block = textwrap.dedent(
            f"""\
            {lattice_cmd}
            region box block 0 {nx} 0 {ny} 0 {nz} units lattice
            create_box {len(elems)} box
            {create}
            {masses}
            """
        )

    ux, uy, uz = _lattice_direction_unit(direction_s, seed, crystal)
    sites = _interstitial_sites_lattice(
        crystal=crystal,
        geometry=geometry,
        count=count,
        nx=nx,
        ny=ny,
        nz=nz,
        direction=(ux, uy, uz),
        a=a,
        offset_A=offset_A,
    )
    ityp = _elem_index(elems, species)
    if structure_file:
        insert_lines = [
            f"create_atoms {ityp} single {x * a:.6f} {y * a:.6f} {z * a:.6f} units box"
            for x, y, z, _kind in sites
        ]
    else:
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
        {poly_note}
        units metal
        dimension 3
        boundary {params.get("boundary", "p p p")}
        atom_style atomic

        {geometry_block}

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
    path.write_text(script, encoding="utf-8")
    return path


def _create_atoms_block(material: dict[str, Any], elems: list[str], *, region: str | None = None) -> str:
    """Fill the lattice: ordered basis for WC-hex; substitutional random alloy otherwise.

    If ``region`` is set (e.g. ``substrate``), atoms are created in that region.
    """
    crystal = crystal_reg.normalize_crystal(material.get("crystal"))
    target = f"region {region}" if region else "box"
    if crystal == "hex" and len(elems) >= 2:
        # Ordered W+C basis (basis 1 → type 1, basis 2 → type 2)
        return f"create_atoms 1 {target} basis 1 1 basis 2 2"
    if len(elems) == 1:
        return f"create_atoms 1 {target}"
    comp = {c["symbol"]: c["atomic_percent"] / 100.0 for c in material["composition"]}
    lines = [f"create_atoms 1 {target}", "group all_atoms type 1"]
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
        "Be": 9.0122,
        "B": 10.81,
        "C": 12.011,
        "N": 14.007,
        "O": 15.999,
        "Ne": 20.180,
        "Al": 26.982,
        "Si": 28.085,
        "Ar": 39.948,
        "Ti": 47.867,
        "V": 50.942,
        "Cr": 51.996,
        "Fe": 55.845,
        "Ni": 58.693,
        "Cu": 63.546,
        "Mo": 95.95,
        "Ta": 180.95,
        "W": 183.84,
        "Re": 186.21,
        "Os": 190.23,
    }
    mass = table.get(symbol)
    if mass is None:
        raise ValueError(
            f"unknown atomic mass for species '{symbol}' — add it to the Aegis mass table or fix the symbol"
        )
    return mass
