from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
import traceback
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aegis_schema import JobCreate, JobInfo, JobStatus, KmcProvenance, KmcTier, Material, Potential

from aegis_api.analysis import analyze_job_dir
from lammps.templates import (
    write_cascade_input,
    write_implant_input,
    write_interstitial_input,
    write_surface_input,
)
from kart.adapter import run_anneal_stub_or_real
from kmc.router import recommend_kmc
from kart.adapter import discover_kart as discover_kart_engine
from mmonca.adapter import run_okmc_stub_or_real


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_mode_structure(params: dict[str, Any]) -> None:
    """Refuse mode/structure combinations that would emit dishonest geometry."""
    mode = str(getattr(params.get("mode"), "value", params.get("mode")) or "cascade").lower()
    sk = str(
        getattr(params.get("structure_kind"), "value", params.get("structure_kind"))
        or "single_crystal"
    ).lower()
    if mode == "interstitial" and sk not in {"", "single_crystal"}:
        raise ValueError(
            "Interstitial insertion requires structure_kind=single_crystal "
            "(lattice-site geometries are not defined on nanostructures)."
        )
    if sk in {"polycrystal", "polycrystal_void", "bicrystal"} and mode == "surface":
        # Surface vacuum slab + grain structures is poorly defined
        raise ValueError(
            f"mode=surface is not supported with structure_kind={sk} — "
            "use cascade/implant, or import a slab with free surfaces."
        )


def _approx_mass_sym(sym: str) -> float:
    table = {
        "H": 1.008,
        "D": 2.014,
        "He": 4.003,
        "C": 12.011,
        "N": 14.007,
        "O": 15.999,
        "Al": 26.982,
        "Si": 28.085,
        "Ti": 47.867,
        "V": 50.942,
        "Cr": 51.996,
        "Fe": 55.845,
        "Ni": 58.693,
        "Cu": 63.546,
        "Mo": 95.95,
        "W": 183.84,
        "Ta": 180.95,
        "Re": 186.21,
    }
    return float(table.get(sym[:1].upper() + sym[1:], table.get(sym, 1.0)))


def _prepare_structure_file(
    job_dir: Path,
    *,
    material: Material,
    params: dict[str, Any],
    mode: str,
    log: Any | None = None,
) -> str | None:
    """Build structure.data when needed; return filename or None for single crystal."""
    from lammps.structure import build_structure, needs_structure_file
    from lammps.structure.data_patch import ensure_atom_types
    from lammps.structure.types import structure_type_symbols
    from lammps.templates import _approx_mass

    if not needs_structure_file(params):
        return None
    mat_dict = material.model_dump(mode="json")
    meta = build_structure(job_dir, material=mat_dict, params=params)
    if log is not None:
        log.write(
            f"[Aegis] structure_kind={meta.get('kind')} backend={meta.get('backend')} "
            f"atoms={meta.get('atom_count')} → structure.data\n"
        )
        if meta.get("atomsk_fallback_reason"):
            log.write(f"[Aegis] Atomsk fallback: {meta['atomsk_fallback_reason']}\n")
        if meta.get("artificial_void"):
            log.write(f"[Aegis] void removed {meta.get('void_atoms_removed')} atoms\n")

    kind = str(meta.get("kind") or params.get("structure_kind") or "").lower()
    mode_s = str(getattr(mode, "value", mode) or "cascade").strip().lower()

    def _norm(sym: str) -> str:
        s = str(sym or "").strip()
        if not s:
            return ""
        if len(s) == 1:
            return s.upper()
        return s[0].upper() + s[1:].lower()

    def _add(out: list[str], seen: set[str], sym: str) -> None:
        n = _norm(sym)
        if not n or n.lower() in seen:
            return
        seen.add(n.lower())
        out.append(n)

    # Import: prefer symbols from the file; only append ion/interstitial extras
    if kind == "import":
        n_file_types = int(meta.get("n_atom_types") or 0)
        resolved = bool(meta.get("type_symbols_resolved")) and isinstance(
            meta.get("type_symbols"), list
        ) and bool(meta.get("type_symbols"))
        elems = []
        seen: set[str] = set()
        if resolved:
            for s in meta["type_symbols"]:
                _add(elems, seen, str(s))
        else:
            hosts = [
                _norm(str(c.get("symbol") or ""))
                for c in (mat_dict.get("composition") or [])
                if float(c.get("atomic_percent") or 0) > 0
            ]
            hosts = [h for h in hosts if h]
            if n_file_types > 1 and len(hosts) != n_file_types:
                raise ValueError(
                    f"Imported structure has {n_file_types} atom types but no element symbols, "
                    f"while material composition has {len(hosts)} host species. "
                    "Provide a typed data file (ASE-readable symbols) or a composition with "
                    "exactly one species per atom type in type order."
                )
            if n_file_types > 1 and len(hosts) == n_file_types:
                for h in hosts:
                    _add(elems, seen, h)
            elif hosts:
                for h in hosts:
                    _add(elems, seen, h)
            else:
                raise ValueError("Import requires type symbols or a non-empty host composition")
        if mode_s in {"implant", "surface"}:
            _add(elems, seen, str(params.get("ion_type") or "He"))
        elif mode_s == "interstitial":
            _add(elems, seen, str(params.get("interstitial_species") or "He"))
    else:
        elems = structure_type_symbols(mat_dict, params, mode=mode)
        # Prefer builder-reported order when present (alloy / WC)
        built = meta.get("type_symbols")
        if isinstance(built, list) and built:
            elems = [_norm(str(s)) for s in built if str(s).strip()]
            extras = structure_type_symbols(mat_dict, params, mode=mode)
            seen = {e.lower() for e in elems}
            for s in extras:
                _add(elems, seen, s)

    data_path = job_dir / "structure.data"
    if elems:
        masses = {i + 1: float(_approx_mass(s)) for i, s in enumerate(elems)}
        ensure_atom_types(data_path, len(elems), masses)
        # Assert declared type count matches planned symbols
        from lammps.structure.import_backend import _count_atom_types

        declared = _count_atom_types(data_path)
        if declared and declared != len(elems):
            raise ValueError(
                f"structure.data declares {declared} atom types but type_symbols has {len(elems)} "
                f"({', '.join(elems)}) — refusing dishonest pair_coeff mapping"
            )
    # Persist type order for templates / debugging
    meta_path = job_dir / "structure_meta.json"
    try:
        meta2 = json.loads(meta_path.read_text(encoding="utf-8")) if meta_path.exists() else dict(meta)
        meta2["type_symbols"] = elems
        meta_path.write_text(json.dumps(meta2, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return "structure.data"


class JobManager:
    def __init__(self, runs_root: Path, store: Any) -> None:
        self.runs_root = runs_root
        self.store = store
        self._jobs: dict[str, JobInfo] = {}
        self._procs: dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._load_existing()

    def _load_existing(self) -> None:
        for d in self.runs_root.iterdir() if self.runs_root.exists() else []:
            if d.name == "campaigns" or not d.is_dir():
                continue
            meta = d / "job.json"
            if meta.exists():
                try:
                    info = JobInfo(**json.loads(meta.read_text(encoding="utf-8")))
                    # In-flight statuses cannot resume after process restart
                    if info.status in {
                        JobStatus.QUEUED,
                        JobStatus.RUNNING,
                        JobStatus.ANALYZING,
                        JobStatus.ANNEALING,
                    }:
                        info.status = JobStatus.FAILED
                        info.message = "interrupted by server restart"
                        info.updated_at = _now()
                        (d / "job.json").write_text(info.model_dump_json(indent=2), encoding="utf-8")
                    self._jobs[info.id] = info
                except Exception:  # noqa: BLE001
                    continue

    def _persist(self, info: JobInfo) -> None:
        job_dir = self.runs_root / info.id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "job.json").write_text(info.model_dump_json(indent=2), encoding="utf-8")

    def list_jobs(self) -> list[JobInfo]:
        return sorted(self._jobs.values(), key=lambda j: j.created_at, reverse=True)

    def get(self, job_id: str) -> JobInfo | None:
        return self._jobs.get(job_id)

    def create(self, body: JobCreate, material: Material, potential: Potential) -> JobInfo:
        job_id = uuid4().hex[:12]
        info = JobInfo(
            id=job_id,
            status=JobStatus.QUEUED,
            project_name=body.project_name,
            material_id=material.id,
            potential_id=potential.id,
            scenario_id=body.scenario_id,
            created_at=_now(),
            updated_at=_now(),
            message="queued",
            run_params=body.run_params,
            run_kart_anneal=body.run_kart_anneal,
            run_mmonca_okmc=body.run_mmonca_okmc,
            kmc_tier=body.kmc_tier,
        )
        job_dir = self.runs_root / job_id
        job_dir.mkdir(parents=True, exist_ok=True)
        (job_dir / "material.json").write_text(material.model_dump_json(indent=2), encoding="utf-8")
        (job_dir / "potential.json").write_text(potential.model_dump_json(indent=2), encoding="utf-8")
        (job_dir / "run_params.json").write_text(
            body.run_params.model_dump_json(indent=2), encoding="utf-8"
        )
        (job_dir / "request.json").write_text(
            json.dumps(
                {
                    "kart_temperature_K": body.kart_temperature_K,
                    "kart_max_events": body.kart_max_events,
                    "kart_max_wall_s": body.kart_max_wall_s,
                    "kart_max_kmc_time_s": body.kart_max_kmc_time_s,
                    "kart_anneal_temperatures": body.kart_anneal_temperatures,
                    "run_mmonca_okmc": body.run_mmonca_okmc,
                    "mmonca_temperature_K": body.mmonca_temperature_K,
                    "mmonca_max_events": body.mmonca_max_events,
                    "kmc_tier": body.kmc_tier.value if body.kmc_tier else None,
                    "kart_prefactor_compare": bool(body.kart_prefactor_compare),
                },
                indent=2,
            ),
            encoding="utf-8",
        )
        with self._lock:
            self._jobs[job_id] = info
            self._persist(info)
        return info

    def start(self, job_id: str) -> None:
        t = threading.Thread(target=self._run, args=(job_id,), daemon=True)
        t.start()

    def prepare_inputs(self, job_id: str) -> Path:
        """Write in.aegis + copy potential without launching LAMMPS (HPC export packs)."""
        from aegis_api.coverage import validate_cascade_pka, validate_potential_coverage

        job_dir = self.runs_root / job_id
        material = Material(**json.loads((job_dir / "material.json").read_text(encoding="utf-8")))
        potential = Potential(**json.loads((job_dir / "potential.json").read_text(encoding="utf-8")))
        params = json.loads((job_dir / "run_params.json").read_text(encoding="utf-8"))
        pot_file = self.store.resolve_potential_file(potential)
        if not pot_file:
            raise FileNotFoundError("potential file missing")

        from lammps import crystal as crystal_reg

        cry = crystal_reg.normalize_crystal(str(getattr(material.crystal, "value", material.crystal)))
        is_placeholder = bool(getattr(potential, "is_placeholder", False)) or "placeholder" in pot_file.name.lower()
        if not crystal_reg.is_supported(cry) and not is_placeholder:
            raise ValueError(
                f"crystal '{cry}' is not supported for real LAMMPS inputs. "
                "Use bcc/fcc/hcp/diamond/hex, or a placeholder potential for dry-run stubs."
            )
        validate_potential_coverage(material, potential, params)
        validate_cascade_pka(material, params)
        _validate_mode_structure(params)

        local_pot = job_dir / pot_file.name
        shutil.copy2(pot_file, local_pot)
        in_path = job_dir / "in.aegis"
        mat_dict = material.model_dump(mode="json")
        pot_dict = potential.model_dump(mode="json")
        mode = str(getattr(params.get("mode"), "value", params.get("mode")) or "cascade")

        if not crystal_reg.is_supported(cry) or is_placeholder:
            # Still build structure.data for honesty when nano kinds are selected
            from lammps.structure import needs_structure_file

            if needs_structure_file(params):
                try:
                    _prepare_structure_file(job_dir, material=material, params=params, mode=mode)
                except Exception as exc:  # noqa: BLE001
                    raise ValueError(
                        f"HPC pack needs a successful structure build for this kind ({exc})"
                    ) from exc
            in_path.write_text(
                f"# Aegis HPC stub (crystal={cry}, placeholder={is_placeholder})\n"
                f"# NOT ready for production MD — replace with a published potential + supported crystal.\n"
                f"# structure.data may be present for inspection; do not submit this stub as-is.\n",
                encoding="utf-8",
            )
            self._update(job_id, message="stub inputs prepared (unsupported crystal or placeholder)")
            return in_path

        structure_file = _prepare_structure_file(
            job_dir, material=material, params=params, mode=mode
        )
        write_kw = dict(
            material=mat_dict,
            potential=pot_dict,
            params=params,
            potential_file=local_pot.name,
            structure_file=structure_file,
        )
        if mode == "surface":
            write_surface_input(in_path, **write_kw)
        elif mode == "implant":
            write_implant_input(in_path, **write_kw)
        elif mode == "interstitial":
            write_interstitial_input(in_path, **write_kw)
        else:
            write_cascade_input(in_path, **write_kw)
        self._update(job_id, message="inputs prepared for HPC export")
        return in_path

    def cancel(self, job_id: str) -> JobInfo | None:
        with self._lock:
            info = self._jobs.get(job_id)
            if not info:
                return None
            if info.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                return info
            proc = self._procs.get(job_id)
            if proc and proc.poll() is None:
                try:
                    proc.terminate()
                except Exception:  # noqa: BLE001
                    pass
                try:
                    proc.kill()
                except Exception:  # noqa: BLE001
                    pass
            info.status = JobStatus.CANCELLED
            info.message = "cancelled by user"
            info.updated_at = _now()
            self._persist(info)
            return info

    def _is_cancelled(self, job_id: str) -> bool:
        info = self.get(job_id)
        return bool(info and info.status == JobStatus.CANCELLED)

    def _update(self, job_id: str, **kwargs: Any) -> JobInfo:
        with self._lock:
            info = self._jobs[job_id]
            # Cancelled jobs are frozen — do not apply later pipeline updates
            if info.status == JobStatus.CANCELLED:
                return info
            data = info.model_dump(mode="json")
            data.update(kwargs)
            data["updated_at"] = _now()
            info = JobInfo(**data)
            self._jobs[job_id] = info
            self._persist(info)
            return info

    def _run(self, job_id: str) -> None:
        job_dir = self.runs_root / job_id
        log_path = job_dir / "run.log"
        try:
            if self._is_cancelled(job_id):
                return
            self._update(job_id, status=JobStatus.RUNNING, message="preparing LAMMPS input")
            if self._is_cancelled(job_id):
                return
            material = Material(**json.loads((job_dir / "material.json").read_text(encoding="utf-8")))
            potential = Potential(**json.loads((job_dir / "potential.json").read_text(encoding="utf-8")))
            params = json.loads((job_dir / "run_params.json").read_text(encoding="utf-8"))
            pot_file = self.store.resolve_potential_file(potential)
            if not pot_file:
                raise FileNotFoundError("potential file missing — upload a published file or place under data/potentials/curated/")

            from aegis_api.coverage import validate_cascade_pka, validate_potential_coverage

            validate_potential_coverage(material, potential, params)
            validate_cascade_pka(material, params)
            _validate_mode_structure(params)

            # Copy potential into job dir for portability
            local_pot = job_dir / pot_file.name
            shutil.copy2(pot_file, local_pot)

            is_placeholder = bool(getattr(potential, "is_placeholder", False)) or "placeholder" in pot_file.name.lower()

            in_path = job_dir / "in.aegis"
            mat_dict = material.model_dump(mode="json")
            pot_dict = potential.model_dump(mode="json")
            mode = str(getattr(params.get("mode"), "value", params.get("mode")) or "cascade")

            from lammps import crystal as crystal_reg

            cry = crystal_reg.normalize_crystal(str(getattr(material.crystal, "value", material.crystal)))
            lmp = os.environ.get("AEGIS_LAMMPS_BIN", "lmp")
            lmp_path = shutil.which(lmp) or (lmp if Path(lmp).exists() else None)
            use_dry_run = (
                not lmp_path
                or is_placeholder
                or not crystal_reg.is_supported(cry)
            )

            with log_path.open("w", encoding="utf-8") as log:
                log.write(f"[Aegis] job {job_id}\n")
                log.write(f"[Aegis] material={material.id} potential={potential.id}\n")
                if not crystal_reg.is_supported(cry):
                    if not is_placeholder and lmp_path:
                        raise RuntimeError(
                            f"crystal '{cry}' is not supported for real LAMMPS runs. "
                            "Use bcc/fcc/hcp/diamond/hex, or a placeholder potential for dry-run."
                        )
                    log.write(
                        f"[Aegis] WARNING: crystal={cry} unsupported — dry-run demo only.\n"
                    )
                else:
                    log.write(f"[Aegis] crystal builder={cry}\n")

                if use_dry_run:
                    from lammps.structure import needs_structure_file

                    sk = str(
                        getattr(params.get("structure_kind"), "value", params.get("structure_kind"))
                        or "single_crystal"
                    )
                    # Stub input so job folder still has in.aegis without calling lattice_line
                    in_path.write_text(
                        f"# Aegis dry-run stub (crystal={cry}, placeholder={is_placeholder}, "
                        f"lammps={'missing' if not lmp_path else 'skipped'}, structure_kind={sk})\n"
                        f"# Real MD inputs are written only when LAMMPS + non-placeholder potential + supported crystal.\n",
                        encoding="utf-8",
                    )
                    if is_placeholder:
                        log.write(
                            "[Aegis] Placeholder potential — dry-run demo dumps only "
                            "(not valid pair coefficients). Upload a published potential for real MD.\n"
                        )
                    if not lmp_path:
                        log.write(
                            "[Aegis] LAMMPS not found on PATH. Writing dry-run artifacts only.\n"
                            "Set AEGIS_LAMMPS_BIN or install LAMMPS to execute MD.\n"
                        )
                    if needs_structure_file(params):
                        # Build real structure.data for honesty, but demo dumps remain SC proxies
                        try:
                            _prepare_structure_file(
                                job_dir,
                                material=material,
                                params=params,
                                mode=mode,
                                log=log,
                            )
                            log.write(
                                "[Aegis] WARNING: dry-run demo dumps are single-crystal proxies; "
                                f"structure.data was built for structure_kind={sk} but MD was not run. "
                                "Upload a real potential + install LAMMPS for nanostructure MD.\n"
                            )
                        except Exception as exc:  # noqa: BLE001
                            raise RuntimeError(
                                f"structure_kind={sk} cannot be honored in dry-run without a successful "
                                f"structure build ({exc}). Install ASE / fix params, or use single_crystal."
                            ) from exc
                    # Cascade timeline so UI Results wiring works without write_cascade_input
                    if mode == "cascade":
                        from lammps.templates import plan_cascade_stages

                        schedule = plan_cascade_stages(
                            energy_eV=float(params.get("pka_energy_eV") or 5000),
                            timestep_fs=float(params.get("timestep_fs") or 1.0),
                            max_steps=int(params.get("max_steps") or 1000),
                            dump_every=int(params.get("dump_every") or 100),
                            auto=bool(params.get("cascade_auto_stages", True)),
                        )
                        (job_dir / "cascade_timeline.json").write_text(
                            json.dumps(schedule, indent=2), encoding="utf-8"
                        )
                    if mode == "surface":
                        self._write_demo_surface_dump(job_dir, material, params)
                    elif mode == "implant":
                        self._write_demo_dump(job_dir, material, dump_name="dump.implant.000000000.lammpstrj")
                    elif mode == "interstitial":
                        self._write_demo_dump(
                            job_dir, material, dump_name="dump.interstitial.000000000.lammpstrj"
                        )
                    else:
                        self._write_demo_dump(job_dir, material)
                    log.write("[Aegis] demo dump written for analysis.\n")
                else:
                    if self._is_cancelled(job_id):
                        return
                    structure_file = _prepare_structure_file(
                        job_dir,
                        material=material,
                        params=params,
                        mode=mode,
                        log=log,
                    )
                    if self._is_cancelled(job_id):
                        return
                    write_kw = dict(
                        material=mat_dict,
                        potential=pot_dict,
                        params=params,
                        potential_file=local_pot.name,
                        structure_file=structure_file,
                    )
                    if mode == "surface":
                        write_surface_input(in_path, **write_kw)
                    elif mode == "implant":
                        write_implant_input(in_path, **write_kw)
                    elif mode == "interstitial":
                        write_interstitial_input(in_path, **write_kw)
                    else:
                        write_cascade_input(in_path, **write_kw)
                    if self._is_cancelled(job_id):
                        return
                    from lammps.mpi import build_lammps_command, resolve_mpi_procs

                    mpi_n = resolve_mpi_procs(params)
                    cmd = build_lammps_command(str(lmp_path), input_name=in_path.name, mpi_procs=mpi_n)
                    log.write(f"[Aegis] launching {' '.join(cmd)} (mpi_procs={mpi_n})\n")
                    if mpi_n > 1:
                        log.write(
                            "[Aegis] MPI note: LAMMPS must be an MPI-enabled build. "
                            "Serial/GUI installers often fail or spawn N independent copies.\n"
                        )
                    log.flush()
                    with self._lock:
                        info0 = self._jobs.get(job_id)
                        if info0 and info0.status == JobStatus.CANCELLED:
                            return
                    proc = subprocess.Popen(
                        cmd,
                        cwd=job_dir,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    with self._lock:
                        info1 = self._jobs.get(job_id)
                        if info1 and info1.status == JobStatus.CANCELLED:
                            try:
                                proc.terminate()
                            except Exception:  # noqa: BLE001
                                pass
                            try:
                                proc.kill()
                            except Exception:  # noqa: BLE001
                                pass
                            return
                        self._procs[job_id] = proc
                    code = proc.wait()
                    with self._lock:
                        self._procs.pop(job_id, None)
                    if self._is_cancelled(job_id):
                        return
                    if code != 0:
                        raise RuntimeError(f"LAMMPS exited with code {code}")

            if self._is_cancelled(job_id):
                return

            self._update(job_id, status=JobStatus.ANALYZING, message="defect analysis")
            if self._is_cancelled(job_id):
                return
            c_A = getattr(material, "lattice_c_A", None) or crystal_reg.resolve_c_A(mat_dict)
            summary = analyze_job_dir(
                job_dir,
                lattice_A=material.lattice_constant_A,
                cluster_cutoff_A=float(params.get("cluster_cutoff_A") or 3.5),
                ws_lattice_A=params.get("ws_lattice_A") or material.lattice_constant_A,
                mode=mode,
                crystal=cry,
                lattice_c_A=c_A,
                structure_kind=str(
                    getattr(params.get("structure_kind"), "value", params.get("structure_kind", "single_crystal"))
                ),
            )
            if self._is_cancelled(job_id):
                return
            if use_dry_run:
                summary.setdefault("summary", {})
                summary["summary"]["demo_structure_proxy"] = True
                sk = str(
                    getattr(params.get("structure_kind"), "value", params.get("structure_kind"))
                    or "single_crystal"
                )
                prev = summary["summary"].get("note") or ""
                summary["summary"]["note"] = (
                    f"{prev} Dry-run demo dumps are single-crystal proxies"
                    f" (structure_kind={sk}; structure.data may exist separately)."
                ).strip()
            (job_dir / "defects.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            surface_summary = (summary.get("surface") or {}).get("summary")

            if self._is_cancelled(job_id):
                return

            # Best-effort cascade/implant preview GIF for Results download
            try:
                from aegis_api.animation import build_trajectory_gif, cache_trajectory_gif

                gif = build_trajectory_gif(job_dir)
                cache_trajectory_gif(job_dir, gif)
                with log_path.open("a", encoding="utf-8") as log:
                    log.write("[Aegis] wrote animation.gif (2D dump preview)\n")
            except Exception as gif_exc:  # noqa: BLE001
                with log_path.open("a", encoding="utf-8") as log:
                    log.write(f"[Aegis] animation.gif skipped: {gif_exc}\n")

            if self._is_cancelled(job_id):
                return

            # Optional OVITO DXA
            if params.get("run_dxa"):
                try:
                    from aegis_api.dxa import run_dxa_on_job

                    dxa = run_dxa_on_job(job_dir, crystal=cry)
                    with log_path.open("a", encoding="utf-8") as log:
                        log.write(f"[Aegis] DXA: {dxa.get('status', 'done')}\n")
                except Exception as dxa_exc:  # noqa: BLE001
                    with log_path.open("a", encoding="utf-8") as log:
                        log.write(f"[Aegis] DXA skipped: {dxa_exc}\n")

            if self._is_cancelled(job_id):
                return

            kart_summary = None
            mmonca_summary = None
            kmc_provenance: KmcProvenance | None = None
            req = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
            info = self.get(job_id)
            sk_anneal = str(
                getattr(params.get("structure_kind"), "value", params.get("structure_kind"))
                or "single_crystal"
            ).lower()
            kart_engine = discover_kart_engine()
            router = recommend_kmc(
                material=material.model_dump(mode="json"),
                target_time_s=float(req.get("kart_max_kmc_time_s", 1.0)),
                temperature_K=float(req.get("kart_temperature_K", 600)),
                run_kart_anneal=bool(info and info.run_kart_anneal),
                run_mmonca_okmc=bool(req.get("run_mmonca_okmc")),
                kart_found=bool(kart_engine.get("kart_found")),
                structure_kind=sk_anneal,
                defect_summary=summary.get("summary"),
                requested_tier=req.get("kmc_tier"),
            )
            if info and info.run_kart_anneal:
                self._update(job_id, status=JobStatus.ANNEALING, message="KART anneal")
                with log_path.open("a", encoding="utf-8") as log:
                    log.write("[Aegis] starting KART anneal path\n")
                    if router.get("warnings"):
                        log.write(f"[Aegis] KMC router: {router.get('recommended_tier')}\n")
                try:
                    if self._is_cancelled(job_id):
                        return
                    kart_summary = run_anneal_stub_or_real(
                        job_dir,
                        temperature_K=float(req.get("kart_temperature_K", 600)),
                        max_events=int(req.get("kart_max_events", 1000)),
                        max_wall_s=float(req.get("kart_max_wall_s", 600)),
                        max_kmc_time_s=float(req.get("kart_max_kmc_time_s", 1.0)),
                        temperatures=req.get("kart_anneal_temperatures"),
                        material=material.model_dump(mode="json"),
                        potential=potential.model_dump(mode="json"),
                        router=router,
                        prefactor_compare=bool(req.get("kart_prefactor_compare")),
                        omp_threads=int(params.get("kmc_threads") or 1),
                    )
                    if isinstance(kart_summary, dict) and sk_anneal not in {"", "single_crystal"}:
                        kart_summary["ws_proxy_warning"] = (
                            f"structure_kind={sk_anneal}: KART handoff uses WS proxy defect counts "
                            "that are not transferable for nanostructures — treat anneal as "
                            "handoff_ready / engineering only."
                        )
                        prev = kart_summary.get("message") or ""
                        kart_summary["message"] = f"{prev} {kart_summary['ws_proxy_warning']}".strip()
                    if isinstance(kart_summary.get("provenance"), dict):
                        try:
                            kmc_provenance = KmcProvenance(**kart_summary["provenance"])
                        except Exception:  # noqa: BLE001
                            pass
                except Exception as anneal_exc:  # noqa: BLE001
                    # Keep cascade COMPLETED — mirror POST /kart/anneal semantics
                    with log_path.open("a", encoding="utf-8") as log:
                        log.write(f"[Aegis] KART anneal failed (cascade kept): {anneal_exc}\n")
                    kart_summary = {
                        "error": str(anneal_exc),
                        "anneal_failed": True,
                    }

            if self._is_cancelled(job_id):
                return

            info = self.get(job_id)
            if info and (info.run_mmonca_okmc or req.get("run_mmonca_okmc")):
                self._update(job_id, status=JobStatus.ANNEALING, message="MMonCa OKMC")
                with log_path.open("a", encoding="utf-8") as log:
                    log.write("[Aegis] starting optional MMonCa OKMC path\n")
                sk_anneal = str(
                    getattr(params.get("structure_kind"), "value", params.get("structure_kind"))
                    or "single_crystal"
                ).lower()
                try:
                    if self._is_cancelled(job_id):
                        return
                    mmonca_summary = run_okmc_stub_or_real(
                        job_dir,
                        temperature_K=float(req.get("mmonca_temperature_K", 600)),
                        max_events=int(req.get("mmonca_max_events", 1000)),
                        router=router,
                    )
                    if isinstance(mmonca_summary, dict):
                        mmonca_summary["synthetic"] = True
                        if sk_anneal not in {"", "single_crystal"}:
                            mmonca_summary["ws_proxy_warning"] = (
                                f"structure_kind={sk_anneal}: MMonCa path is synthetic and fed by "
                                "WS proxy counts — not a calibrated OKMC result."
                            )
                        if not kmc_provenance and isinstance(mmonca_summary.get("provenance"), dict):
                            try:
                                kmc_provenance = KmcProvenance(**mmonca_summary["provenance"])
                            except Exception:  # noqa: BLE001
                                pass
                except Exception as okmc_exc:  # noqa: BLE001
                    with log_path.open("a", encoding="utf-8") as log:
                        log.write(f"[Aegis] MMonCa failed (cascade kept): {okmc_exc}\n")
                    mmonca_summary = {"error": str(okmc_exc), "okmc_failed": True}

            if self._is_cancelled(job_id):
                return

            msg = "completed"
            if isinstance(kart_summary, dict) and kart_summary.get("anneal_failed"):
                msg = f"cascade completed; anneal failed: {kart_summary.get('error')}"
            sk = str(
                getattr(params.get("structure_kind"), "value", params.get("structure_kind"))
                or "single_crystal"
            )
            execution_mode = "synthetic_proxy" if use_dry_run else "real_md"
            struct_prov: dict[str, Any] = {"structure_kind": sk}
            meta_path = job_dir / "structure_meta.json"
            if meta_path.exists():
                try:
                    sm = json.loads(meta_path.read_text(encoding="utf-8"))
                    struct_prov.update(
                        {
                            "backend": sm.get("backend"),
                            "type_symbols": sm.get("type_symbols"),
                            "alloy": sm.get("alloy"),
                            "atom_count": sm.get("atom_count"),
                            "note": sm.get("note"),
                            "atomsk_fallback_reason": sm.get("atomsk_fallback_reason"),
                        }
                    )
                except Exception:  # noqa: BLE001
                    pass
            if kmc_provenance is None and router.get("warnings"):
                try:
                    kmc_provenance = KmcProvenance(
                        tier=KmcTier(router["recommended_tier"]),
                        synthetic=True,
                        prefactor_model=(
                            "htst" if router.get("prefactor_model_hint") == "htst" else "unknown"
                        ),
                        trapping_risk=router.get("trapping_risk_hint") or "unknown",
                        validation_status="unvalidated",
                        target_time_s=float(req.get("kart_max_kmc_time_s", 1.0)),
                        warnings=list(router.get("warnings") or []),
                    )
                except Exception:  # noqa: BLE001
                    kmc_provenance = None
            self._update(
                job_id,
                status=JobStatus.COMPLETED,
                message=msg,
                defect_summary=summary.get("summary"),
                kart_summary=kart_summary,
                mmonca_summary=mmonca_summary,
                kmc_provenance=kmc_provenance,
                surface_summary=surface_summary,
                execution_mode=execution_mode,
                structure_provenance=struct_prov,
            )
        except Exception as exc:  # noqa: BLE001
            if self._is_cancelled(job_id):
                return
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n[Aegis] FAILED: {exc}\n")
                log.write(traceback.format_exc())
            self._update(job_id, status=JobStatus.FAILED, message=str(exc))

    def _write_demo_dump(
        self, job_dir: Path, material: Material, *, dump_name: str = "dump.cascade.000000000.lammpstrj"
    ) -> None:
        """Artificial multi-frame trajectory so structure viz works without LAMMPS.

        Atom positions match ``crystal.ideal_sites`` so dry-run WS analysis stays consistent.
        """
        from lammps import crystal as crystal_reg
        import math

        a = float(material.lattice_constant_A)
        cry = crystal_reg.normalize_crystal(str(getattr(material.crystal, "value", material.crystal)))
        mat = material.model_dump(mode="json")
        c = crystal_reg.resolve_c_A(mat, cry) or a
        n_cells = 2
        if cry in {"hcp", "hex"}:
            # Match ideal_sites / lattice_line bounding box
            Lx = n_cells * a
            Ly = n_cells * (a * math.sqrt(3) / 2.0)
            Lz = n_cells * c
        else:
            Lx = Ly = Lz = n_cells * a
        sites = crystal_reg.ideal_sites((Lx, Ly, Lz), cry, a, c=c)

        def frame(timestep: int, displace: float = 0.0, extra: bool = False) -> list[str]:
            atoms: list[str] = []
            for n, (x, y, z) in enumerate(sites, start=1):
                dx = displace if n == 1 else 0.0
                atoms.append(f"{n} 1 {x + dx:.6f} {y:.6f} {z:.6f}")
            n = len(atoms)
            if extra:
                n += 1
                atoms.append(f"{n} 1 {Lx * 0.25:.6f} {Ly * 0.25:.6f} {Lz * 0.25:.6f}")
            lines = [
                "ITEM: TIMESTEP",
                str(timestep),
                "ITEM: NUMBER OF ATOMS",
                str(n),
                "ITEM: BOX BOUNDS pp pp pp",
                f"0 {Lx}",
                f"0 {Ly}",
                f"0 {Lz}",
                "ITEM: ATOMS id type x y z",
                *atoms,
            ]
            return lines

        (job_dir / "dump.initial.lammpstrj").write_text(
            "\n".join(frame(0, 0.0, False)) + "\n", encoding="utf-8"
        )
        traj = (
            frame(0, 0.2, False)
            + frame(1000, 0.5, True)
            + frame(2000, 0.8, True)
            + frame(5000, 0.9, True)
        )
        (job_dir / dump_name).write_text("\n".join(traj) + "\n", encoding="utf-8")
        (job_dir / "final.data").write_text(f"# demo crystal={cry} a={a} c={c}\n", encoding="utf-8")

    def _write_demo_surface_dump(self, job_dir: Path, material: Material, params: dict) -> None:
        """Demo free-surface trajectory with fuzz / implant proxies for dry-run."""
        from lammps import crystal as crystal_reg
        import math

        a = float(material.lattice_constant_A)
        cry = crystal_reg.normalize_crystal(str(getattr(material.crystal, "value", material.crystal)))
        mat = material.model_dump(mode="json")
        c = crystal_reg.resolve_c_A(mat, cry) or a
        nz = int(params.get("nz", 4))
        vacuum = int(params.get("vacuum_layers", 4))
        nx = ny = 4
        if cry in {"hcp", "hex"}:
            lx = nx * a
            ly = ny * (a * math.sqrt(3) / 2.0)
            z_pitch = c
        else:
            lx = nx * a
            ly = ny * a
            z_pitch = a
        lz = (nz + vacuum) * z_pitch
        sites = crystal_reg.ideal_sites((lx, ly, nz * z_pitch), cry, a, c=c, z_max=nz * z_pitch)

        def frame(timestep: int, fuzz: float = 0.0, he_depth: float = 0.0) -> list[str]:
            atoms: list[str] = []
            z_top = max((s[2] for s in sites), default=0.0)
            for n, (x, y, z) in enumerate(sites, start=1):
                if abs(z - z_top) < 1e-6:
                    z = z + fuzz
                atoms.append(f"{n} 1 {x:.6f} {y:.6f} {z:.6f}")
            n = len(atoms)
            if he_depth > 0:
                n += 1
                atoms.append(f"{n} 2 {lx * 0.5:.6f} {ly * 0.5:.6f} {max(0.0, z_top - he_depth):.6f}")
            lines = [
                "ITEM: TIMESTEP",
                str(timestep),
                "ITEM: NUMBER OF ATOMS",
                str(n),
                "ITEM: BOX BOUNDS pp pp ss",
                f"0 {lx}",
                f"0 {ly}",
                f"0 {lz}",
                "ITEM: ATOMS id type x y z",
                *atoms,
            ]
            return lines

        (job_dir / "dump.initial.lammpstrj").write_text(
            "\n".join(frame(0, 0.0, 0.0)) + "\n", encoding="utf-8"
        )
        traj = frame(0, 0.1, 0.5) + frame(1000, 0.4, 1.2) + frame(5000, 0.7, 1.8)
        (job_dir / "dump.surface.000000000.lammpstrj").write_text(
            "\n".join(traj) + "\n", encoding="utf-8"
        )
        (job_dir / "final.data").write_text(f"# demo surface crystal={cry}\n", encoding="utf-8")
