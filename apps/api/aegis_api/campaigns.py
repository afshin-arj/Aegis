from __future__ import annotations

import json
import shutil
import threading
import time
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from aegis_schema import (
    DoeCampaignCreate,
    DoeCampaignInfo,
    DoeCase,
    HpcExportRequest,
    JobCreate,
    JobStatus,
    LammpsRunParams,
    Material,
    Potential,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _param_field(axis: str) -> str:
    return axis


def expand_doe_matrix(body: DoeCampaignCreate) -> list[dict[str, Any]]:
    """Cartesian product of axis values, capped at max_jobs."""
    if not body.values_x:
        raise ValueError("values_x must not be empty")
    xs = list(body.values_x)
    ys = list(body.values_y) if body.axis_y and body.values_y else [None]
    if body.axis_y and not body.values_y:
        raise ValueError("values_y must not be empty when axis_y is set")
    cases: list[dict[str, Any]] = []
    for x in xs:
        for y in ys:
            overrides: dict[str, Any] = {_param_field(body.axis_x.value): float(x)}
            label = f"{body.axis_x.value}={x:g}"
            if body.axis_y and y is not None:
                overrides[_param_field(body.axis_y.value)] = float(y)
                label += f",{body.axis_y.value}={y:g}"
            cases.append({"label": label, "overrides": overrides})
            if len(cases) >= body.max_jobs:
                return cases
    return cases


class CampaignManager:
    def __init__(self, runs_root: Path, job_manager: Any, store: Any) -> None:
        self.runs_root = runs_root
        self.campaigns_root = runs_root / "campaigns"
        self.campaigns_root.mkdir(parents=True, exist_ok=True)
        self.jobs = job_manager
        self.store = store
        self._lock = threading.Lock()
        self._campaigns: dict[str, DoeCampaignInfo] = {}
        self._load_existing()

    def _load_existing(self) -> None:
        for d in self.campaigns_root.iterdir() if self.campaigns_root.exists() else []:
            meta = d / "campaign.json"
            if meta.exists():
                try:
                    info = DoeCampaignInfo(**json.loads(meta.read_text(encoding="utf-8")))
                    self._campaigns[info.id] = info
                except Exception:  # noqa: BLE001
                    continue

    def _persist(self, info: DoeCampaignInfo) -> None:
        d = self.campaigns_root / info.id
        d.mkdir(parents=True, exist_ok=True)
        (d / "campaign.json").write_text(info.model_dump_json(indent=2), encoding="utf-8")

    def list_campaigns(self) -> list[DoeCampaignInfo]:
        return sorted(self._campaigns.values(), key=lambda c: c.created_at, reverse=True)

    def get(self, campaign_id: str) -> DoeCampaignInfo | None:
        return self._campaigns.get(campaign_id)

    def create(self, body: DoeCampaignCreate, material: Material, potential: Potential) -> DoeCampaignInfo:
        matrix = expand_doe_matrix(body)
        if not matrix:
            raise ValueError("DOE matrix is empty")
        xs = list(body.values_x) or [0.0]
        ys = list(body.values_y) if body.axis_y and body.values_y else [None]
        full_count = len(xs) * len(ys)
        cid = uuid4().hex[:12]
        cases: list[DoeCase] = []
        job_ids: list[str] = []
        for spec in matrix:
            params = body.base.run_params.model_dump(mode="json")
            params.update(spec["overrides"])
            # Keep confirm_large only when the caller already set it (API enforces the gate)
            cells = int(params["nx"]) * int(params["ny"]) * int(params["nz"])
            if cells > 20 * 20 * 20 and not params.get("confirm_large"):
                raise ValueError("Large cell (>20³). Set confirm_large=true on the base recipe.")
            run_params = LammpsRunParams(**params)
            job_body = JobCreate(
                project_name=f"{body.name}/{spec['label']}",
                material_id=body.base.material_id,
                material_override=body.base.material_override or material,
                potential_id=body.base.potential_id,
                scenario_id=body.base.scenario_id,
                run_params=run_params,
                run_kart_anneal=body.base.run_kart_anneal,
                kart_temperature_K=body.base.kart_temperature_K,
                kart_max_events=body.base.kart_max_events,
                kart_max_wall_s=body.base.kart_max_wall_s,
                kart_max_kmc_time_s=body.base.kart_max_kmc_time_s,
                kart_anneal_temperatures=body.base.kart_anneal_temperatures,
                run_mmonca_okmc=body.base.run_mmonca_okmc,
                mmonca_temperature_K=body.base.mmonca_temperature_K,
                mmonca_max_events=body.base.mmonca_max_events,
            )
            info = self.jobs.create(job_body, material, potential)
            job_ids.append(info.id)
            if body.run_locally:
                cases.append(
                    DoeCase(job_id=info.id, label=spec["label"], overrides=spec["overrides"], status="queued")
                )
            else:
                # Prepare LAMMPS inputs without executing (remote HPC / DEMO export)
                self.jobs.prepare_inputs(info.id)
                cases.append(
                    DoeCase(
                        job_id=info.id, label=spec["label"], overrides=spec["overrides"], status="export_ready"
                    )
                )

        camp = DoeCampaignInfo(
            id=cid,
            name=body.name,
            created_at=_now(),
            updated_at=_now(),
            status="queued" if body.run_locally else "export_only",
            message=(
                f"{len(cases)} cases"
                + (f" (capped from {full_count})" if full_count > len(cases) else "")
            ),
            axis_x=body.axis_x.value,
            values_x=list(body.values_x),
            axis_y=body.axis_y.value if body.axis_y else None,
            values_y=list(body.values_y) if body.values_y else None,
            cases=cases,
            job_ids=job_ids,
        )
        # Store base request for reproducibility
        (self.campaigns_root / cid).mkdir(parents=True, exist_ok=True)
        (self.campaigns_root / cid / "request.json").write_text(
            body.model_dump_json(indent=2), encoding="utf-8"
        )
        with self._lock:
            self._campaigns[cid] = camp
            self._persist(camp)
        if body.run_locally and job_ids:
            threading.Thread(target=self._run_serial, args=(cid,), daemon=True).start()
        return camp

    def _update(self, campaign_id: str, **kwargs: Any) -> DoeCampaignInfo:
        with self._lock:
            info = self._campaigns[campaign_id]
            data = info.model_dump(mode="json")
            data.update(kwargs)
            data["updated_at"] = _now()
            info = DoeCampaignInfo(**data)
            self._campaigns[campaign_id] = info
            self._persist(info)
            return info

    def _run_serial(self, campaign_id: str) -> None:
        """Run DOE jobs one-at-a-time to avoid local resource stampede."""
        info = self.get(campaign_id)
        if not info:
            return
        self._update(campaign_id, status="running", message="executing DOE cases serially")
        for i, case in enumerate(info.cases):
            if not case.job_id:
                continue
            self.jobs.start(case.job_id)
            # Wait until terminal
            while True:
                job = self.jobs.get(case.job_id)
                if not job:
                    break
                if job.status in {JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED}:
                    break
                time.sleep(0.5)
            # Refresh case statuses
            camp = self.get(campaign_id)
            if not camp:
                return
            cases = []
            for c in camp.cases:
                if c.job_id == case.job_id:
                    j = self.jobs.get(c.job_id)
                    cases.append(
                        DoeCase(
                            job_id=c.job_id,
                            label=c.label,
                            overrides=c.overrides,
                            status=j.status.value if j else "missing",
                        )
                    )
                else:
                    cases.append(c)
            self._update(campaign_id, cases=cases, message=f"finished case {i + 1}/{len(camp.cases)}")
        self.refresh_summary(campaign_id)
        camp = self.get(campaign_id)
        if not camp:
            return
        failed = sum(1 for c in camp.cases if c.status == "failed")
        cancelled = sum(1 for c in camp.cases if c.status == "cancelled")
        if failed and failed == len(camp.cases):
            final_status, msg = "failed", "DOE campaign failed (all cases)"
        elif failed or cancelled:
            final_status, msg = "completed_with_errors", f"DOE campaign finished with {failed} failed / {cancelled} cancelled"
        else:
            final_status, msg = "completed", "DOE campaign completed"
        self._update(campaign_id, status=final_status, message=msg)

    def refresh_summary(self, campaign_id: str) -> DoeCampaignInfo | None:
        info = self.get(campaign_id)
        if not info:
            return None
        export_only = info.status == "export_only"
        rows: list[dict[str, Any]] = []
        cases: list[DoeCase] = []
        for c in info.cases:
            row: dict[str, Any] = {"label": c.label, **c.overrides}
            status = c.status
            if c.job_id:
                job = self.jobs.get(c.job_id)
                if job:
                    # Keep export_ready for HPC-only campaigns (jobs stay queued forever)
                    if export_only or c.status == "export_ready":
                        if job.status.value == "queued":
                            status = "export_ready"
                        else:
                            status = job.status.value
                    else:
                        status = job.status.value
                    row["job_id"] = job.id
                    row["status"] = status
                    ds = job.defect_summary or {}
                    row["vacancies"] = ds.get("vacancies")
                    row["interstitials"] = ds.get("interstitials")
                    row["clusters"] = ds.get("clusters")
                    if job.surface_summary:
                        row["mean_host_recession_A"] = job.surface_summary.get("mean_host_recession_A")
                        row["fuzz_atom_count"] = job.surface_summary.get("fuzz_atom_count")
                else:
                    row["status"] = "missing"
                    status = "missing"
            else:
                row["status"] = status
            rows.append(row)
            cases.append(DoeCase(job_id=c.job_id, label=c.label, overrides=c.overrides, status=status))
        done = sum(1 for c in cases if c.status in {"completed", "failed", "cancelled", "export_ready"})
        failed = sum(1 for c in cases if c.status == "failed")
        msg = f"{done}/{len(cases)} cases finished"
        if failed:
            msg += f" ({failed} failed)"
        return self._update(campaign_id, cases=cases, summary_rows=rows, message=msg)


def write_hpc_pack(
    job_dir: Path,
    *,
    out_dir: Path,
    req: HpcExportRequest,
    job_id: str = "",
    make_zip: bool = True,
) -> Path:
    """Assemble a portable pack for remote HPC (inputs + scheduler scripts).

    Returns the zip path when make_zip=True, otherwise out_dir.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for name in (
        "in.aegis",
        "material.json",
        "potential.json",
        "run_params.json",
        "request.json",
        "structure.data",
        "structure_meta.json",
        "cascade_timeline.json",
    ):
        src = job_dir / name
        if src.exists():
            shutil.copy2(src, out_dir / name)
    # Copy potential file if present in job dir
    for cand in job_dir.iterdir():
        if cand.is_file() and cand.suffix.lower() in {
            ".eam",
            ".alloy",
            ".fs",
            ".meam",
            ".dat",
            ".placeholder",
        }:
            shutil.copy2(cand, out_dir / cand.name)

    readme = f"""# Aegis HPC pack
Job: {job_id or job_dir.name}
Generated for remote execution (Phase-4).

## Run locally / on login node
```bash
{req.lammps_bin} -in in.aegis
```

## Notes
- Review pair_style / potential paths in `in.aegis` (files are copied beside the input).
- If `structure.data` is present, `in.aegis` uses `read_data structure.data` — keep that file next to the input.
- After MD, copy dumps back to your Aegis `runs/<job_id>/` and re-open Results, or point Aegis at the artifacts.
- Do not commit cluster accounts or tokens into the Aegis repo.
"""
    (out_dir / "README_HPC.md").write_text(readme, encoding="utf-8")

    if req.scheduler == "slurm":
        acct = f"#SBATCH --account={req.account}\n" if req.account else ""
        queue = f"#SBATCH --partition={req.queue}\n" if req.queue else ""
        mod = f"module load {req.lammps_module}\n" if req.lammps_module else ""
        script = f"""#!/bin/bash
#SBATCH --job-name=aegis-{job_id or 'job'}
#SBATCH --nodes=1
#SBATCH --ntasks={req.cores}
#SBATCH --time={req.walltime}
{acct}{queue}set -euo pipefail
cd "$SLURM_SUBMIT_DIR"
{mod}{req.lammps_bin} -in in.aegis
"""
        (out_dir / "submit.slurm").write_text(script, encoding="utf-8")
    elif req.scheduler == "pbs":
        acct = f"#PBS -A {req.account}\n" if req.account else ""
        queue = f"#PBS -q {req.queue}\n" if req.queue else ""
        mod = f"module load {req.lammps_module}\n" if req.lammps_module else ""
        script = f"""#!/bin/bash
#PBS -N aegis-{job_id or 'job'}
#PBS -l nodes=1:ppn={req.cores}
#PBS -l walltime={req.walltime}
{acct}{queue}set -euo pipefail
cd "$PBS_O_WORKDIR"
{mod}{req.lammps_bin} -in in.aegis
"""
        (out_dir / "submit.pbs").write_text(script, encoding="utf-8")

    if not make_zip:
        return out_dir

    zip_path = out_dir.parent / f"{out_dir.name}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in out_dir.rglob("*"):
            if f.is_file() and f != zip_path:
                zf.write(f, arcname=str(f.relative_to(out_dir.parent)))
    return zip_path


def write_campaign_submit_helper(bundle_root: Path, req: HpcExportRequest, case_dirs: list[str]) -> None:
    """Write a one-shot helper that submits every case on Slurm/PBS."""
    if req.scheduler == "slurm":
        lines = ["#!/bin/bash", "set -euo pipefail", f"ROOT=\"$(cd \"$(dirname \"$0\")\" && pwd)\""]
        for d in case_dirs:
            lines.append(f'(cd "$ROOT/{d}" && sbatch submit.slurm)')
        (bundle_root / "submit_all.sh").write_text("\n".join(lines) + "\n", encoding="utf-8")
    elif req.scheduler == "pbs":
        lines = ["#!/bin/bash", "set -euo pipefail", f"ROOT=\"$(cd \"$(dirname \"$0\")\" && pwd)\""]
        for d in case_dirs:
            lines.append(f'(cd "$ROOT/{d}" && qsub submit.pbs)')
        (bundle_root / "submit_all.sh").write_text("\n".join(lines) + "\n", encoding="utf-8")
