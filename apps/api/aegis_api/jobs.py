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

from aegis_schema import JobCreate, JobInfo, JobStatus, Material, Potential

from aegis_api.analysis import analyze_job_dir
from lammps.templates import write_cascade_input, write_implant_input, write_surface_input
from kart.adapter import run_anneal_stub_or_real
from mmonca.adapter import run_okmc_stub_or_real


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


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
            meta = d / "job.json"
            if meta.exists():
                try:
                    info = JobInfo(**json.loads(meta.read_text(encoding="utf-8")))
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
        job_dir = self.runs_root / job_id
        material = Material(**json.loads((job_dir / "material.json").read_text(encoding="utf-8")))
        potential = Potential(**json.loads((job_dir / "potential.json").read_text(encoding="utf-8")))
        params = json.loads((job_dir / "run_params.json").read_text(encoding="utf-8"))
        pot_file = self.store.resolve_potential_file(potential)
        if not pot_file:
            raise FileNotFoundError("potential file missing")
        local_pot = job_dir / pot_file.name
        shutil.copy2(pot_file, local_pot)
        in_path = job_dir / "in.aegis"
        mat_dict = material.model_dump()
        pot_dict = potential.model_dump()
        mode = str(getattr(params.get("mode"), "value", params.get("mode")) or "cascade")
        if mode == "surface":
            write_surface_input(
                in_path,
                material=mat_dict,
                potential=pot_dict,
                params=params,
                potential_file=local_pot.name,
            )
        elif mode == "implant":
            write_implant_input(
                in_path,
                material=mat_dict,
                potential=pot_dict,
                params=params,
                potential_file=local_pot.name,
            )
        else:
            write_cascade_input(
                in_path,
                material=mat_dict,
                potential=pot_dict,
                params=params,
                potential_file=local_pot.name,
            )
        self._update(job_id, message="inputs prepared for HPC export")
        return in_path

    def cancel(self, job_id: str) -> JobInfo | None:
        with self._lock:
            info = self._jobs.get(job_id)
            if not info:
                return None
            proc = self._procs.get(job_id)
            if proc and proc.poll() is None:
                proc.terminate()
            info.status = JobStatus.CANCELLED
            info.message = "cancelled by user"
            info.updated_at = _now()
            self._persist(info)
            return info

    def _update(self, job_id: str, **kwargs: Any) -> JobInfo:
        with self._lock:
            info = self._jobs[job_id]
            data = info.model_dump()
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
            self._update(job_id, status=JobStatus.RUNNING, message="preparing LAMMPS input")
            material = Material(**json.loads((job_dir / "material.json").read_text(encoding="utf-8")))
            potential = Potential(**json.loads((job_dir / "potential.json").read_text(encoding="utf-8")))
            params = json.loads((job_dir / "run_params.json").read_text(encoding="utf-8"))
            pot_file = self.store.resolve_potential_file(potential)
            if not pot_file:
                raise FileNotFoundError("potential file missing — upload a published file or place under data/potentials/curated/")

            # Copy potential into job dir for portability
            local_pot = job_dir / pot_file.name
            shutil.copy2(pot_file, local_pot)

            is_placeholder = bool(getattr(potential, "is_placeholder", False)) or "placeholder" in pot_file.name.lower()

            in_path = job_dir / "in.aegis"
            mat_dict = material.model_dump()
            pot_dict = potential.model_dump()
            mode = str(getattr(params.get("mode"), "value", params.get("mode")) or "cascade")
            if mode == "surface":
                write_surface_input(
                    in_path,
                    material=mat_dict,
                    potential=pot_dict,
                    params=params,
                    potential_file=local_pot.name,
                )
            elif mode == "implant":
                write_implant_input(
                    in_path,
                    material=mat_dict,
                    potential=pot_dict,
                    params=params,
                    potential_file=local_pot.name,
                )
            else:
                write_cascade_input(
                    in_path,
                    material=mat_dict,
                    potential=pot_dict,
                    params=params,
                    potential_file=local_pot.name,
                )

            lmp = os.environ.get("AEGIS_LAMMPS_BIN", "lmp")
            lmp_path = shutil.which(lmp) or (lmp if Path(lmp).exists() else None)

            with log_path.open("w", encoding="utf-8") as log:
                log.write(f"[Aegis] job {job_id}\n")
                log.write(f"[Aegis] material={material.id} potential={potential.id}\n")
                if material.crystal.lower() != "bcc":
                    log.write(
                        f"[Aegis] WARNING: material crystal={material.crystal}; "
                        "Phase-1 templates build BCC cells only.\n"
                    )
                if not lmp_path or is_placeholder:
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
                    if mode == "surface":
                        self._write_demo_surface_dump(job_dir, material, params)
                    else:
                        self._write_demo_dump(job_dir, material)
                    log.write("[Aegis] demo dump written for analysis.\n")
                else:
                    log.write(f"[Aegis] launching {lmp_path} -in {in_path.name}\n")
                    log.flush()
                    proc = subprocess.Popen(
                        [lmp_path, "-in", in_path.name],
                        cwd=job_dir,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        text=True,
                    )
                    with self._lock:
                        self._procs[job_id] = proc
                    code = proc.wait()
                    with self._lock:
                        self._procs.pop(job_id, None)
                    if code != 0:
                        raise RuntimeError(f"LAMMPS exited with code {code}")

            info = self.get(job_id)
            if info and info.status == JobStatus.CANCELLED:
                return

            self._update(job_id, status=JobStatus.ANALYZING, message="defect analysis")
            summary = analyze_job_dir(
                job_dir,
                lattice_A=material.lattice_constant_A,
                cluster_cutoff_A=float(params.get("cluster_cutoff_A") or 3.5),
                ws_lattice_A=params.get("ws_lattice_A") or material.lattice_constant_A,
                mode=mode,
            )
            (job_dir / "defects.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
            surface_summary = (summary.get("surface") or {}).get("summary")

            kart_summary = None
            mmonca_summary = None
            req = json.loads((job_dir / "request.json").read_text(encoding="utf-8"))
            info = self.get(job_id)
            if info and info.run_kart_anneal:
                self._update(job_id, status=JobStatus.ANNEALING, message="KART anneal")
                with log_path.open("a", encoding="utf-8") as log:
                    log.write("[Aegis] starting KART anneal path\n")
                kart_summary = run_anneal_stub_or_real(
                    job_dir,
                    temperature_K=float(req.get("kart_temperature_K", 600)),
                    max_events=int(req.get("kart_max_events", 1000)),
                    max_wall_s=float(req.get("kart_max_wall_s", 600)),
                    max_kmc_time_s=float(req.get("kart_max_kmc_time_s", 1.0)),
                    temperatures=req.get("kart_anneal_temperatures"),
                    material=material.model_dump(),
                    potential=potential.model_dump(),
                )

            info = self.get(job_id)
            if info and (info.run_mmonca_okmc or req.get("run_mmonca_okmc")):
                self._update(job_id, status=JobStatus.ANNEALING, message="MMonCa OKMC")
                with log_path.open("a", encoding="utf-8") as log:
                    log.write("[Aegis] starting optional MMonCa OKMC path\n")
                mmonca_summary = run_okmc_stub_or_real(
                    job_dir,
                    temperature_K=float(req.get("mmonca_temperature_K", 600)),
                    max_events=int(req.get("mmonca_max_events", 1000)),
                )

            self._update(
                job_id,
                status=JobStatus.COMPLETED,
                message="completed",
                defect_summary=summary.get("summary"),
                kart_summary=kart_summary,
                mmonca_summary=mmonca_summary,
                surface_summary=surface_summary,
            )
        except Exception as exc:  # noqa: BLE001
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n[Aegis] FAILED: {exc}\n")
                log.write(traceback.format_exc())
            self._update(job_id, status=JobStatus.FAILED, message=str(exc))

    def _write_demo_dump(self, job_dir: Path, material: Material) -> None:
        """Artificial multi-frame trajectory so structure viz works without LAMMPS."""
        a = material.lattice_constant_A

        def frame(timestep: int, displace: float = 0.0, extra: bool = False) -> list[str]:
            atoms: list[str] = []
            n = 0
            for i in range(2):
                for j in range(2):
                    for k in range(2):
                        n += 1
                        atoms.append(f"{n} 1 {i*a} {j*a} {k*a}")
                        n += 1
                        dx = displace if (i, j, k) == (1, 1, 1) else 0.0
                        atoms.append(f"{n} 1 {i*a+a/2+dx} {j*a+a/2} {k*a+a/2}")
            if extra:
                n += 1
                atoms.append(f"{n} 1 {a*0.25} {a*0.25} {a*0.25}")
            lines = [
                "ITEM: TIMESTEP",
                str(timestep),
                "ITEM: NUMBER OF ATOMS",
                str(n),
                "ITEM: BOX BOUNDS pp pp pp",
                f"0 {2*a}",
                f"0 {2*a}",
                f"0 {2*a}",
                "ITEM: ATOMS id type x y z",
                *atoms,
            ]
            return lines

        (job_dir / "dump.initial.lammpstrj").write_text(
            "\n".join(frame(0, 0.0, False)) + "\n", encoding="utf-8"
        )
        # Multi-timestep "after" trajectory in one file
        traj = (
            frame(0, 0.2, False)
            + frame(1000, 0.5, True)
            + frame(2000, 0.8, True)
            + frame(5000, 0.9, True)
        )
        (job_dir / "dump.cascade.000000000.lammpstrj").write_text(
            "\n".join(traj) + "\n", encoding="utf-8"
        )
        (job_dir / "final.data").write_text("# demo\n", encoding="utf-8")

    def _write_demo_surface_dump(self, job_dir: Path, material: Material, params: dict) -> None:
        """Demo free-surface trajectory with fuzz / implant proxies for dry-run."""
        a = material.lattice_constant_A
        nz = int(params.get("nz", 4))
        vacuum = int(params.get("vacuum_layers", 4))
        lz = (nz + vacuum) * a
        ly = lx = 4 * a

        def frame(timestep: int, fuzz: float = 0.0, he_depth: float = 0.0) -> list[str]:
            atoms: list[str] = []
            n = 0
            for i in range(4):
                for j in range(4):
                    for k in range(max(2, nz)):
                        n += 1
                        z = k * a
                        if k == max(2, nz) - 1:
                            z += fuzz
                        atoms.append(f"{n} 1 {i*a} {j*a} {z}")
            if he_depth > 0:
                n += 1
                atoms.append(f"{n} 2 {2*a} {2*a} {max(0.0, (nz * a) - he_depth)}")
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
        (job_dir / "final.data").write_text("# demo surface\n", encoding="utf-8")
