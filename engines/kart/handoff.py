from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any


def _read_last_dump_atoms(
    job_dir: Path,
) -> tuple[list[dict[str, Any]], tuple[float, float, float]]:
    """Prefer cascade/implant dumps over dump.initial."""
    patterns = (
        "dump.cascade.*.lammpstrj",
        "dump.implant.*.lammpstrj",
        "dump.interstitial.*.lammpstrj",
        "dump.surface.*.lammpstrj",
        "dump.*.lammpstrj",
    )
    files: list[Path] = []
    for pat in patterns:
        files.extend(job_dir.glob(pat))
    uniq = sorted({p.resolve(): p for p in files}.values(), key=lambda p: p.name)
    non_initial = [p for p in uniq if "initial" not in p.name.lower()]
    dumps = non_initial or uniq
    if not dumps:
        return [], (0.0, 0.0, 0.0)
    path = dumps[-1]
    text = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    starts = [i for i, line in enumerate(text) if line.startswith("ITEM: TIMESTEP")]
    if not starts:
        return [], (0.0, 0.0, 0.0)
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
    atoms = []
    for line in text[i + 1 : i + 1 + n]:
        parts = line.split()
        atoms.append(
            {
                "id": int(parts[idx.get("id", 0)]),
                "type": int(parts[idx.get("type", 1)]),
                "x": float(parts[idx["x"]]),
                "y": float(parts[idx["y"]]),
                "z": float(parts[idx["z"]]),
            }
        )
    return atoms, (xhi - xlo, yhi - ylo, zhi - zlo)


def _mass(symbol: str) -> float:
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
        raise ValueError(f"unknown atomic mass for species '{symbol}'")
    return mass


def build_kart_package(
    job_dir: Path,
    *,
    temperature_K: float,
    max_events: int,
    max_wall_s: float,
    max_kmc_time_s: float,
    material: dict[str, Any] | None = None,
    potential: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Write a KART-oriented handoff directory from cascade artifacts.

    Produces LAMMPS data + kART ``.conf`` + ``KMC.sh.aegis`` following upstream
    docs conventions (see kart-doc tutorial). Full auto-launch still requires a
    built binary and validated forcefield wiring.
    """
    material = material or {}
    potential = potential or {}
    work = job_dir / "kart_work" / f"T{int(round(temperature_K))}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    atoms, box = _read_last_dump_atoms(job_dir)
    lx, ly, lz = box
    if not atoms:
        # Minimal fallback cell so the package is still inspectable
        a = float(material.get("lattice_constant_A") or 3.165)
        lx = ly = lz = 2 * a
        atoms = [
            {"id": 1, "type": 1, "x": 0.0, "y": 0.0, "z": 0.0},
            {"id": 2, "type": 1, "x": a / 2, "y": a / 2, "z": a / 2},
        ]

    elems = [
        c["symbol"]
        for c in material.get("composition", [{"symbol": "W", "atomic_percent": 100}])
        if c.get("atomic_percent", 0) > 0
    ] or ["W"]
    ntypes = max((int(a["type"]) for a in atoms), default=len(elems))
    while len(elems) < ntypes:
        elems.append(f"X{len(elems) + 1}")

    # LAMMPS data file (conf.lammps) for ENERGY_CALC=LAM path
    data_lines = [
        "Aegis cascade → KART handoff",
        "",
        f"{len(atoms)} atoms",
        f"{ntypes} atom types",
        "",
        f"0.0 {lx:.8f} xlo xhi",
        f"0.0 {ly:.8f} ylo yhi",
        f"0.0 {lz:.8f} zlo zhi",
        "",
        "Masses",
        "",
    ]
    for i, sym in enumerate(elems[:ntypes], start=1):
        data_lines.append(f"{i} {_mass(sym)}")
    data_lines.extend(["", "Atoms", ""])
    for a in atoms:
        data_lines.append(f"{a['id']} {a['type']} {a['x']:.8f} {a['y']:.8f} {a['z']:.8f}")
    (work / "conf.lammps").write_text("\n".join(data_lines) + "\n", encoding="utf-8")

    # kART INI conf (run id, energy placeholder, box, then type x y z)
    conf_lines = [
        "run_id: 0",
        "total energy : 0.0000",
        f"{lx:.8f} {ly:.8f} {lz:.8f}",
    ]
    for a in atoms:
        conf_lines.append(f" {a['type']} {a['x']:.8f} {a['y']:.8f} {a['z']:.8f}")
    ini_name = "initial.conf"
    (work / ini_name).write_text("\n".join(conf_lines) + "\n", encoding="utf-8")

    # Defect overlay XYZ for OVITO / inspection
    defects: dict[str, Any] = {}
    defects_path = job_dir / "defects.json"
    if defects_path.exists():
        try:
            defects = json.loads(defects_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            defects = {}
    points = defects.get("points") or []
    vac = [p for p in points if p.get("kind") == "vacancy"]
    sia = [p for p in points if p.get("kind") in ("interstitial", "displaced")]

    def _xyz(path: Path, rows: list[dict[str, Any]], label: str) -> None:
        lines = [str(len(rows)), label]
        for p in rows:
            lines.append(f"X {p['x']:.6f} {p['y']:.6f} {p['z']:.6f}")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    _xyz(work / "defects_vacancies.xyz", vac, "Aegis vacancies")
    _xyz(work / "defects_sia.xyz", sia, "Aegis SIA / displaced")

    # Copy potential into package when available
    pot_note = "no potential file copied"
    if potential.get("file_path"):
        # potential.json stores path relative to data root; job dir may have local copy
        for cand in job_dir.glob("*"):
            if cand.is_file() and cand.suffix.lower() in {
                ".eam",
                ".alloy",
                ".fs",
                ".meam",
                ".placeholder",
                ".dat",
            }:
                shutil.copy2(cand, work / cand.name)
                pot_note = cand.name
                break

    pair_style = potential.get("lammps_pair_style", "eam/alloy")
    pair_coeff = potential.get("pair_coeff_template", "pair_coeff * * {file} {elements}")
    pot_file = pot_note if pot_note != "no potential file copied" else "POTENTIAL.file"
    try:
        pair_coeff_line = pair_coeff.format(file=pot_file, elements=" ".join(elems[:ntypes]))
    except Exception:  # noqa: BLE001
        pair_coeff_line = f"pair_coeff * * {pot_file} {' '.join(elems[:ntypes])}"

    in_lammps = f"""# Aegis-generated LAMMPS force helper for KART (ENERGY_CALC=LAM)
# Review pair_style / coefficients before production anneals.
units metal
atom_style atomic
atom_modify map array
read_data conf.lammps
{chr(10).join(f"mass {i} {_mass(sym)}" for i, sym in enumerate(elems[:ntypes], start=1))}
pair_style {pair_style}
{pair_coeff_line}
neighbor 0.0 bin
neigh_modify delay 0 every 1 check no
"""
    (work / "in.lammps").write_text(in_lammps, encoding="utf-8")

    # KMC.sh-compatible env script (csh setenv style per kart-doc)
    box_edge = max(lx, ly, lz)
    topo_r = max(4.0, 2.2 * float(material.get("lattice_constant_A") or 3.165))
    kmc = f"""#!/bin/csh
# Aegis-generated KART launch template — edit TOPO_* / CRYST_* for your material.
# Docs: https://kart-doc.readthedocs.io/
setenv NUMBER_ATOMS {len(atoms)}
setenv SIMULATION_BOX {box_edge:.6f}
setenv NSPECIES {ntypes}
setenv ATOMIC_SYMBOLS "{' '.join(elems[:ntypes])}"
setenv INI_FILE_NAME '{ini_name}'
setenv ENERGY_CALC LAM
setenv INPUT_LAMMPS_FILE 'in.lammps'
setenv UNITS_CONVERSION metal
setenv TEMPERATURE {temperature_K:.3f}
setenv NBRE_KMC_STEPS {int(max_events)}
setenv TOTAL_TIME {float(max_kmc_time_s):.6g}
setenv USE_TXT_EVENTFILE .true.
setenv TOPO_RADIUS {topo_r:.3f}
setenv MAX_TOPO_CUTOFF {0.85 * float(material.get('lattice_constant_A') or 3.165):.3f}
setenv MIN_TOPO_CUTOFF {0.55 * float(material.get('lattice_constant_A') or 3.165):.3f}
setenv OSCILL_TREAT NONE
setenv MIN_SIG_BARRIER 0.1
# setenv CRYST_TOPOID <identify on first run>
# Launch: convert setenv→export then run kart binary (see engines/kart/SETUP.md)
"""
    (work / "KMC.sh.aegis").write_text(kmc, encoding="utf-8")

    # Optional restart pointer
    restart_src = None
    for name in ("final.data", "restart.aegis"):
        if (job_dir / name).exists():
            shutil.copy2(job_dir / name, work / name)
            restart_src = name
            break

    meta = {
        "format": "aegis-kart-handoff-v2",
        "work_dir": str(work.relative_to(job_dir)).replace("\\", "/"),
        "temperature_K": temperature_K,
        "max_events": max_events,
        "max_wall_s": max_wall_s,
        "max_kmc_time_s": max_kmc_time_s,
        "n_atoms": len(atoms),
        "box_A": {"lx": lx, "ly": ly, "lz": lz},
        "elements": elems[:ntypes],
        "files": {
            "lammps_data": "conf.lammps",
            "kart_conf": ini_name,
            "lammps_input": "in.lammps",
            "kmc_script": "KMC.sh.aegis",
            "vacancies_xyz": "defects_vacancies.xyz",
            "sia_xyz": "defects_sia.xyz",
            "restart": restart_src,
            "potential_copy": pot_note,
        },
        "defect_summary": defects.get("summary"),
        "notes": [
            "Handoff follows kart-doc LAM+initial.conf conventions.",
            "Identify CRYST_TOPOID on a short scout run before production anneals.",
            "Aegis may stub events when the binary cannot complete a full KMC.sh launch.",
        ],
    }
    (work / "handoff.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (job_dir / "kart_handoff.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def parse_energy_dat(path: Path) -> list[dict[str, Any]]:
    """Parse KART Energy.dat into event records when present."""
    if not path.exists():
        return []
    events: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        s = line.strip()
        if not s or s.startswith("#"):
            continue
        parts = s.split()
        if len(parts) < 8:
            continue
        try:
            step = int(float(parts[0]))
            barrier = float(parts[4])
            dt = float(parts[6])
            sim_t = float(parts[7])
        except ValueError:
            continue
        events.append(
            {
                "event": step,
                "barrier_eV": barrier,
                "time_s": sim_t,
                "dt_s": dt,
                "source": "Energy.dat",
            }
        )
    return events


def synthetic_events(
    *,
    temperature_K: float,
    max_events: int,
    max_kmc_time_s: float,
    n_vac: int = 0,
    n_sia: int = 0,
) -> list[dict[str, Any]]:
    """Physically flavoured stub timeline for UI when KART cannot run."""
    n = max(1, min(int(max_events), 40))
    # Rough Arrhenius-inspired barriers; not calibrated.
    base = 0.35 + 0.15 * math.tanh((n_vac + n_sia) / 20.0)
    t = 0.0
    events = []
    for i in range(n):
        barrier = base + 0.08 * math.sin(i * 0.7) + 0.02 * (i % 5)
        # dt ~ exp(E/kT); k_B in eV/K
        kT = max(temperature_K, 1.0) * 8.617333262145e-5
        dt = min(max_kmc_time_s / max(n, 1), 1e-8 * math.exp(min(barrier / kT, 40.0)))
        t += dt
        if t > max_kmc_time_s > 0:
            break
        events.append(
            {
                "event": i + 1,
                "barrier_eV": round(barrier, 4),
                "time_s": t,
                "dt_s": dt,
                "source": "aegis-stub",
            }
        )
    return events
