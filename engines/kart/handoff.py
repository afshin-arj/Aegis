from __future__ import annotations

import json
import math
import shutil
from pathlib import Path
from typing import Any


def _read_last_dump_atoms(
    job_dir: Path,
) -> tuple[list[dict[str, Any]], tuple[float, float, float], tuple[float, float, float]]:
    """Prefer cascade/implant dumps over dump.initial and dump.stage bookmarks.

    Returns ``(atoms, (Lx, Ly, Lz), (xlo, ylo, zlo))``.
    """
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
    non_initial = [
        p
        for p in uniq
        if "initial" not in p.name.lower() and not p.name.startswith("dump.stage")
    ]
    dumps = non_initial or [p for p in uniq if not p.name.startswith("dump.stage")] or uniq
    if not dumps:
        return [], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    path = dumps[-1]
    text = path.read_text(encoding="utf-8", errors="replace").strip().splitlines()
    starts = [i for i, line in enumerate(text) if line.startswith("ITEM: TIMESTEP")]
    if not starts:
        return [], (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
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
    return atoms, (xhi - xlo, yhi - ylo, zhi - zlo), (xlo, ylo, zlo)


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
    prefactor_mode: str | None = None,
    work_suffix: str = "",
    omp_threads: int = 1,
) -> dict[str, Any]:
    """Write a KART-oriented handoff directory from cascade artifacts.

    Produces LAMMPS data + kART ``.conf`` + ``KMC.sh.aegis`` following upstream
    docs conventions (see kart-doc tutorial). Full auto-launch still requires a
    built binary and validated forcefield wiring.

    ``prefactor_mode`` overrides the concentrated-alloy default (``htst`` vs ``constant``).
    ``work_suffix`` appends to the work dir name (e.g. ``_htst`` for compare mode).
    ``omp_threads`` sets OMP_NUM_THREADS in the launch template (k-ART host threading).
    """
    material = material or {}
    potential = potential or {}
    omp_n = max(1, min(int(omp_threads or 1), 256))
    suffix = f"_{work_suffix}" if work_suffix else ""
    work = job_dir / "kart_work" / f"T{int(round(temperature_K))}{suffix}"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True, exist_ok=True)

    atoms, box, origin = _read_last_dump_atoms(job_dir)
    lx, ly, lz = box
    ox, oy, oz = origin
    shift = (0.0, 0.0, 0.0)
    if not atoms:
        # Minimal fallback cell so the package is still inspectable
        a = float(material.get("lattice_constant_A") or 3.165)
        lx = ly = lz = 2 * a
        ox = oy = oz = 0.0
        atoms = [
            {"id": 1, "type": 1, "x": 0.0, "y": 0.0, "z": 0.0},
            {"id": 2, "type": 1, "x": a / 2, "y": a / 2, "z": a / 2},
        ]
    else:
        # Remap absolute dump coords into a [0, L] cell for k-ART / LAMMPS data
        if abs(ox) > 1e-9 or abs(oy) > 1e-9 or abs(oz) > 1e-9:
            shift = (ox, oy, oz)
            for a in atoms:
                a["x"] = float(a["x"]) - ox
                a["y"] = float(a["y"]) - oy
                a["z"] = float(a["z"]) - oz
            ox = oy = oz = 0.0

    def _norm(sym: str) -> str:
        s = str(sym or "").strip()
        if not s:
            return ""
        if len(s) == 1:
            return s.upper()
        return s[0].upper() + s[1:].lower()

    elems = [
        _norm(c["symbol"])
        for c in material.get("composition", [{"symbol": "W", "atomic_percent": 100}])
        if c.get("atomic_percent", 0) > 0 and _norm(c.get("symbol", ""))
    ] or ["W"]

    # Prefer persisted structure type order (import / alloy / WC)
    meta_path = job_dir / "structure_meta.json"
    if meta_path.exists():
        try:
            ts = json.loads(meta_path.read_text(encoding="utf-8")).get("type_symbols")
            if isinstance(ts, list) and ts:
                elems = [_norm(str(s)) for s in ts if _norm(str(s))]
        except Exception:  # noqa: BLE001
            pass

    # Extend type map from run_params / potential so implant ions are not padded as Xn
    run_params: dict[str, Any] = {}
    rp_path = job_dir / "run_params.json"
    if rp_path.exists():
        try:
            run_params = json.loads(rp_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            run_params = {}
    for key in ("ion_type", "interstitial_species", "pka_species", "precipitate_species"):
        extra = _norm(str(run_params.get(key) or ""))
        if extra and extra.lower() not in {e.lower() for e in elems}:
            elems.append(extra)
    for pe in potential.get("elements") or []:
        extra = _norm(str(pe))
        if extra and extra.lower() not in {e.lower() for e in elems}:
            elems.append(extra)

    ntypes = max((int(a["type"]) for a in atoms), default=len(elems))
    if len(elems) < ntypes:
        raise ValueError(
            f"KART handoff: dump has {ntypes} atom types but only mapped {len(elems)} "
            f"({', '.join(elems)}). Set ion_type/interstitial_species or potential.elements."
        )

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
        sx, sy, sz = shift
        lines = [str(len(rows)), label]
        for p in rows:
            lines.append(
                f"X {float(p['x']) - sx:.6f} {float(p['y']) - sy:.6f} {float(p['z']) - sz:.6f}"
            )
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
    concentrated = _is_concentrated_alloy(material)
    if prefactor_mode in {"htst", "constant"}:
        mode = prefactor_mode
    else:
        mode = "htst" if concentrated else "constant"
    prefactor_mode = mode
    min_event_searches = 25
    trapping_risk = "low"
    if temperature_K < 500 and max_kmc_time_s < 10:
        trapping_risk = "medium"
    if temperature_K < 400:
        trapping_risk = "high"
    use_htst_line = (
        "setenv USE_HTST_PREFACTOR .true.\n" if prefactor_mode == "htst" else "# setenv USE_HTST_PREFACTOR .true.\n"
    )
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
setenv MIN_EVENT_SEARCHES {min_event_searches}
setenv PREFACTOR_MODE {prefactor_mode}
setenv OMP_NUM_THREADS {omp_n}
{use_htst_line}# For concentrated alloys Aegis defaults PREFACTOR_MODE=htst (Adjanor 2025 / Huang 2023).
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
        "format": "aegis-kart-handoff-v3",
        "work_dir": str(work.relative_to(job_dir)).replace("\\", "/"),
        "temperature_K": temperature_K,
        "max_events": max_events,
        "max_wall_s": max_wall_s,
        "max_kmc_time_s": max_kmc_time_s,
        "n_atoms": len(atoms),
        "box_A": {"lx": lx, "ly": ly, "lz": lz},
        "elements": elems[:ntypes],
        "prefactor_mode": prefactor_mode,
        "min_event_searches": min_event_searches,
        "omp_threads": omp_n,
        "trapping_risk_hint": trapping_risk,
        "concentrated_alloy": concentrated,
        "structure_class": "as_cascade",
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
            "prefactor_mode=htst recommended for concentrated alloys (Adjanor 2025 / Huang 2023).",
            "Aegis may stub events when the binary cannot complete a full KMC.sh launch.",
        ],
    }
    (work / "handoff.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    (job_dir / "kart_handoff.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return meta


def _is_concentrated_alloy(material: dict[str, Any]) -> bool:
    active = [
        float(c.get("atomic_percent") or 0)
        for c in material.get("composition") or []
        if float(c.get("atomic_percent") or 0) > 5.0
    ]
    return len(active) >= 2


def parse_energy_dat(
    path: Path,
    *,
    temperature_K: float | None = None,
) -> list[dict[str, Any]]:
    """Parse KART Energy.dat into event records when present.

    Column layout varies by KART build. Aegis accepts:
    - Minimal: step … barrier(at col 4) … dt(col 6) sim_t(col 7)
    - Richer: optional prefactor / rate columns when ≥9 numeric fields present
    """
    if not path.exists():
        return []
    kB = 8.617333262145e-5
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
        prefactor: float | None = None
        rate: float | None = None
        # Heuristic: trailing numeric fields beyond the classic 8-column layout
        extras: list[float] = []
        for p in parts[8:]:
            try:
                extras.append(float(p))
            except ValueError:
                break
        if extras:
            # Prefer values that look like attempt frequencies (1e9–1e16) as prefactor
            for v in extras:
                if 1e9 <= abs(v) <= 1e16:
                    prefactor = v
                    break
            # Prefer values that look like rates (1e-20–1e20, not matching prefactor)
            for v in extras:
                if v != prefactor and 1e-30 < abs(v) < 1e20:
                    # If barrier-consistent Arrhenius rate is closer, keep as rate
                    rate = v
                    break
        if prefactor is None and temperature_K and temperature_K > 0:
            # Default harmonic attempt when only barrier is known (honest provenance note)
            prefactor = 1e13
        if rate is None and prefactor is not None and temperature_K and temperature_K > 0:
            kT = max(temperature_K, 1.0) * kB
            rate = float(prefactor) * math.exp(-min(barrier / kT, 80.0))
        rec: dict[str, Any] = {
            "event": step,
            "barrier_eV": barrier,
            "time_s": sim_t,
            "dt_s": dt,
            "source": "Energy.dat",
        }
        if prefactor is not None:
            rec["prefactor_Hz"] = prefactor
        if rate is not None:
            rec["rate_Hz"] = rate
        events.append(rec)
    return events


def summarize_event_kinetics(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Aggregate barrier / prefactor / rate stats for compare mode and Results chips."""
    if not events:
        return {
            "n_events": 0,
            "mean_barrier_eV": None,
            "median_barrier_eV": None,
            "mean_prefactor_Hz": None,
            "mean_rate_Hz": None,
            "has_prefactors": False,
        }
    barriers = sorted(float(e["barrier_eV"]) for e in events if e.get("barrier_eV") is not None)
    prefs = [float(e["prefactor_Hz"]) for e in events if e.get("prefactor_Hz") is not None]
    rates = [float(e["rate_Hz"]) for e in events if e.get("rate_Hz") is not None]
    mid = barriers[len(barriers) // 2] if barriers else None
    return {
        "n_events": len(events),
        "mean_barrier_eV": round(sum(barriers) / len(barriers), 6) if barriers else None,
        "median_barrier_eV": round(mid, 6) if mid is not None else None,
        "mean_prefactor_Hz": round(sum(prefs) / len(prefs), 3) if prefs else None,
        "mean_rate_Hz": (sum(rates) / len(rates)) if rates else None,
        "has_prefactors": bool(prefs),
    }


def analyze_trapping(events: list[dict[str, Any]], *, flicker_barrier_eV: float = 0.15) -> dict[str, Any]:
    """Heuristic flicker / trapping diagnostic from parsed KART events."""
    if not events:
        return {
            "flicker_ratio": None,
            "trapping_risk": "unknown",
            "low_barrier_count": 0,
            "total_events": 0,
        }
    barriers = [float(e.get("barrier_eV") or 0) for e in events]
    low = sum(1 for b in barriers if b < flicker_barrier_eV)
    total = len(barriers)
    ratio = low / total if total else 0.0
    risk = "low"
    if ratio >= 0.5:
        risk = "high"
    elif ratio >= 0.25:
        risk = "medium"
    return {
        "flicker_ratio": round(ratio, 4),
        "trapping_risk": risk,
        "low_barrier_count": low,
        "total_events": total,
        "flicker_threshold_eV": flicker_barrier_eV,
    }


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
