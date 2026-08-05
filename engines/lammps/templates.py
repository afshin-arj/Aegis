from __future__ import annotations

import json
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


def _snap_bcc_lattice_site(fx: float, fy: float, fz: float, nx: int, ny: int, nz: int) -> tuple[float, float, float]:
    """Snap fractional box coords to the nearest BCC lattice site (lattice units)."""
    tx = max(0.0, min(1.0, fx)) * nx
    ty = max(0.0, min(1.0, fy)) * ny
    tz = max(0.0, min(1.0, fz)) * nz
    # Candidate: corner sites (integer) and body-center (half-integer)
    candidates: list[tuple[float, float, float]] = []
    i0, j0, k0 = int(math.floor(tx)), int(math.floor(ty)), int(math.floor(tz))
    for di in range(-1, 3):
        for dj in range(-1, 3):
            for dk in range(-1, 3):
                i, j, k = i0 + di, j0 + dj, k0 + dk
                if 0 <= i < nx and 0 <= j < ny and 0 <= k < nz:
                    candidates.append((float(i), float(j), float(k)))
                    # body center of cell (i,j,k)
                    if i + 0.5 < nx and j + 0.5 < ny and k + 0.5 < nz:
                        candidates.append((i + 0.5, j + 0.5, k + 0.5))
    if not candidates:
        return nx * 0.5, ny * 0.5, nz * 0.5
    best = min(candidates, key=lambda p: (p[0] - tx) ** 2 + (p[1] - ty) ** 2 + (p[2] - tz) ** 2)
    return best


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
    site_mode = str(params.get("pka_site") or "center").strip().lower()
    auto_stages = bool(params.get("cascade_auto_stages", True))
    dump_every = int(params.get("dump_every", 1000))

    pair_style = potential["lammps_pair_style"]
    pair_coeff = render_pair_coeff(
        potential["pair_coeff_template"], potential_file, elems
    )
    mass_pka = _approx_mass(primary)
    speed = math.sqrt(2.0 * E / mass_pka) * 98.226947

    masses = "\n".join(f"mass {i+1} {_approx_mass(sym)}" for i, sym in enumerate(elems))
    create = _create_atoms_block(material, elems)
    ensemble = _ensemble_fix(params)
    restart = _restart_block(params)
    crystal_note = _crystal_comment(material)

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
        dvx, dvy, dvz = _direction_unit(str(params.get("pka_direction", "random")), s)
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

        sx, sy, sz = _snap_bcc_lattice_site(fx, fy, fz, nx, ny, nz)
        site_notes.append(f"PKA{i+1}: frac≈({fx:.3f},{fy:.3f},{fz:.3f}) → lattice ({sx:.3f},{sy:.3f},{sz:.3f})")
        # Sphere large enough to catch one BCC atom at the snapped site
        rad = 0.45
        pka_blocks.append(
            textwrap.dedent(
                f"""\
                # PKA event {i + 1}/{n_pkas} species={primary} site={site_mode}
                # Target lattice site ({sx:.6f} {sy:.6f} {sz:.6f}); pick nearest atom in a small sphere
                region pka_pick_{i} sphere {sx:.6f} {sy:.6f} {sz:.6f} {rad:.4f} units lattice
                group pka_{i} region pka_pick_{i}
                # Fallback if FP miss: expand once
                variable npka_{i} equal count(pka_{i})
                if "${{npka_{i}}} == 0" then "region pka_pick_{i} sphere {sx:.6f} {sy:.6f} {sz:.6f} 0.85 units lattice" "group pka_{i} region pka_pick_{i}"
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
        # Cascade timeline written to cascade_timeline.json (OVITO stage guide)
        # Auto stages: {schedule['auto']} total_steps={schedule['total_steps']} extended={schedule.get('extended_max_steps')}
{sites_comment}
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
        {restart}

        {pka_script}
        # Capture cascade t=0 immediately after PKA kick(s)
        {dynamics_header}

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
