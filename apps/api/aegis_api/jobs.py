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
from lammps.templates import write_cascade_input, write_implant_input
from kart.adapter import run_anneal_stub_or_real


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
                raise FileNotFoundError("potential file missing")

            # Copy potential into job dir for portability
            local_pot = job_dir / pot_file.name
            shutil.copy2(pot_file, local_pot)

            in_path = job_dir / "in.aegis"
            mat_dict = material.model_dump()
            pot_dict = potential.model_dump()
            if params.get("mode") == "implant":
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
                if not lmp_path:
                    log.write(
                        "[Aegis] LAMMPS not found on PATH. Writing dry-run artifacts only.\n"
                        "Set AEGIS_LAMMPS_BIN or install LAMMPS to execute MD.\n"
                    )
                    # Dry-run: synthesize a small dump for analysis pipeline testing
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
            summary = analyze_job_dir(job_dir, lattice_A=material.lattice_constant_A)
            (job_dir / "defects.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

            kart_summary = None
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
                )

            self._update(
                job_id,
                status=JobStatus.COMPLETED,
                message="completed",
                defect_summary=summary.get("summary"),
                kart_summary=kart_summary,
            )
        except Exception as exc:  # noqa: BLE001
            with log_path.open("a", encoding="utf-8") as log:
                log.write(f"\n[Aegis] FAILED: {exc}\n")
                log.write(traceback.format_exc())
            self._update(job_id, status=JobStatus.FAILED, message=str(exc))

    def _write_demo_dump(self, job_dir: Path, material: Material) -> None:
        """Minimal artificial trajectory so analysis/UI work without LAMMPS installed."""
        a = material.lattice_constant_A
        lines = [
            "ITEM: TIMESTEP",
            "0",
            "ITEM: NUMBER OF ATOMS",
            "16",
            "ITEM: BOX BOUNDS pp pp pp",
            f"0 {2*a}",
            f"0 {2*a}",
            f"0 {2*a}",
            "ITEM: ATOMS id type x y z",
        ]
        # Perfect BCC-like points + two displaced "interstitials"
        n = 0
        for i in range(2):
            for j in range(2):
                for k in range(2):
                    n += 1
                    lines.append(f"{n} 1 {i*a} {j*a} {k*a}")
                    n += 1
                    lines.append(f"{n} 1 {i*a+a/2} {j*a+a/2} {k*a+a/2}")
        # displace last atom
        parts = lines[-1].split()
        parts[2] = str(float(parts[2]) + 0.8)
        lines[-1] = " ".join(parts)
        # add interstitial
        lines[3] = "17"
        lines.append(f"17 1 {a*0.25} {a*0.25} {a*0.25}")
        (job_dir / "dump.cascade.000000000.lammpstrj").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )
        (job_dir / "final.data").write_text("# demo\n", encoding="utf-8")
