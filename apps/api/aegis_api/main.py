from __future__ import annotations

import json
import os
import shutil
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import ValidationError

# Repo paths: .../apps/api/aegis_api/main.py → parents[3] = repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "packages" / "schema"
ENGINES_PATH = REPO_ROOT / "engines"
sys.path.insert(0, str(SCHEMA_PATH))
sys.path.insert(0, str(ENGINES_PATH))

from aegis_schema import (  # noqa: E402
    EngineStatus,
    JobCreate,
    JobInfo,
    JobStatus,
    LammpsRunParams,
    Material,
    MaterialUpdate,
    Potential,
    PotentialUploadMeta,
    Scenario,
)
from kart.adapter import discover_kart, run_anneal_stub_or_real  # noqa: E402
from lammps.templates import write_cascade_input, write_implant_input  # noqa: E402

from aegis_api.analysis import analyze_job_dir  # noqa: E402
from aegis_api.jobs import JobManager  # noqa: E402
from aegis_api.store import DataStore  # noqa: E402

DATA_ROOT = Path(os.environ.get("AEGIS_DATA_ROOT") or (REPO_ROOT / "data"))
RUNS_ROOT = Path(os.environ.get("AEGIS_RUNS_ROOT") or (REPO_ROOT / "runs"))
RUNS_ROOT.mkdir(parents=True, exist_ok=True)

store = DataStore(DATA_ROOT)
jobs = JobManager(RUNS_ROOT, store)

app = FastAPI(title="Aegis API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "aegis"}


@app.get("/api/engines/status", response_model=EngineStatus)
def engines_status() -> EngineStatus:
    lmp = os.environ.get("AEGIS_LAMMPS_BIN", "lmp")
    path = shutil.which(lmp) or (lmp if Path(lmp).exists() else None)
    version = None
    if path:
        try:
            import subprocess

            proc = subprocess.run(
                [path, "-h"], capture_output=True, text=True, timeout=10, check=False
            )
            text = (proc.stdout or "") + (proc.stderr or "")
            for line in text.splitlines():
                if "LAMMPS" in line:
                    version = line.strip()[:120]
                    break
        except Exception:  # noqa: BLE001
            version = "found (version probe failed)"
    kart = discover_kart()
    return EngineStatus(
        lammps_found=path is not None,
        lammps_path=path,
        lammps_version=version,
        kart_root=kart.get("kart_root"),
        kart_found=bool(kart.get("kart_found")),
        kart_binary=kart.get("kart_binary"),
        kart_commit_expected=kart.get("kart_commit_expected", "62d66adf"),
        kart_message=kart.get("kart_message", ""),
    )


@app.get("/api/materials", response_model=list[Material])
def list_materials() -> list[Material]:
    return store.list_materials()


@app.get("/api/materials/{material_id}", response_model=Material)
def get_material(material_id: str) -> Material:
    m = store.get_material(material_id)
    if not m:
        raise HTTPException(404, "material not found")
    return m


@app.post("/api/materials", response_model=Material)
def create_material(material: Material) -> Material:
    return store.save_material(material)


@app.put("/api/materials/{material_id}", response_model=Material)
def update_material(material_id: str, patch: MaterialUpdate) -> Material:
    m = store.get_material(material_id)
    if not m:
        raise HTTPException(404, "material not found")
    data = m.model_dump()
    for k, v in patch.model_dump(exclude_unset=True).items():
        if v is not None:
            data[k] = v
    try:
        updated = Material(**data)
    except ValidationError as exc:
        raise HTTPException(400, str(exc)) from exc
    return store.save_material(updated)


@app.get("/api/scenarios", response_model=list[Scenario])
def list_scenarios() -> list[Scenario]:
    return store.list_scenarios()


@app.get("/api/potentials", response_model=list[Potential])
def list_potentials(material_id: str | None = None) -> list[Potential]:
    pots = store.list_potentials()
    if material_id:
        m = store.get_material(material_id)
        if not m:
            raise HTTPException(404, "material not found")
        symbols = {e.symbol for e in m.composition if e.atomic_percent > 0}
        # Keep potentials that cover every material element (superset OK).
        pots = [p for p in pots if symbols <= set(p.elements)]
    return pots


@app.post("/api/potentials/upload", response_model=Potential)
async def upload_potential(
    file: UploadFile = File(...),
    meta: str = Form(...),
) -> Potential:
    try:
        meta_obj = PotentialUploadMeta.model_validate_json(meta)
    except ValidationError as exc:
        raise HTTPException(400, f"invalid meta: {exc}") from exc
    pot_id = f"user-{uuid.uuid4().hex[:10]}"
    dest_dir = DATA_ROOT / "potentials" / "user" / pot_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    suffix = Path(file.filename or "potential.dat").name
    dest = dest_dir / suffix
    content = await file.read()
    dest.write_bytes(content)
    pot = Potential(
        id=pot_id,
        name=meta_obj.name,
        formalism=meta_obj.formalism,
        elements=meta_obj.elements,
        recommended_for=meta_obj.recommended_for,
        citation=meta_obj.notes,
        warnings=["User-uploaded potential — unvalidated by Aegis."],
        lammps_pair_style=meta_obj.lammps_pair_style,
        pair_coeff_template=meta_obj.pair_coeff_template,
        file_path=str(dest.relative_to(DATA_ROOT)).replace("\\", "/"),
        source="user",
        available=True,
    )
    store.add_user_potential(pot)
    return pot


@app.post("/api/jobs", response_model=JobInfo)
def create_job(body: JobCreate) -> JobInfo:
    material = body.material_override or store.get_material(body.material_id)
    if not material:
        raise HTTPException(404, "material not found")
    potential = store.get_potential(body.potential_id)
    if not potential:
        raise HTTPException(404, "potential not found")
    if not potential.available or not potential.file_path:
        raise HTTPException(
            400,
            "Selected potential has no file on disk. Upload a potential file or place one under data/potentials/curated/.",
        )
    # Large cell guard
    cells = body.run_params.nx * body.run_params.ny * body.run_params.nz
    if cells > 20 * 20 * 20 and not body.run_params.confirm_large:
        raise HTTPException(
            400,
            "Large cell (>20³ unit cells). Set confirm_large=true to proceed.",
        )
    info = jobs.create(body, material, potential)
    jobs.start(info.id)
    return info


@app.get("/api/jobs", response_model=list[JobInfo])
def list_jobs() -> list[JobInfo]:
    return jobs.list_jobs()


@app.get("/api/jobs/{job_id}", response_model=JobInfo)
def get_job(job_id: str) -> JobInfo:
    info = jobs.get(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    return info


@app.post("/api/jobs/{job_id}/cancel", response_model=JobInfo)
def cancel_job(job_id: str) -> JobInfo:
    info = jobs.cancel(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    return info


@app.get("/api/jobs/{job_id}/artifacts/{name}")
def get_artifact(job_id: str, name: str) -> FileResponse:
    path = RUNS_ROOT / job_id / name
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "artifact not found")
    return FileResponse(path)


@app.get("/api/jobs/{job_id}/defects")
def get_defects(job_id: str) -> dict[str, Any]:
    path = RUNS_ROOT / job_id / "defects.json"
    if not path.exists():
        raise HTTPException(404, "defects not ready")
    return json.loads(path.read_text(encoding="utf-8"))


@app.websocket("/api/jobs/{job_id}/log")
async def job_log_ws(websocket: WebSocket, job_id: str) -> None:
    await websocket.accept()
    log_path = RUNS_ROOT / job_id / "run.log"
    try:
        # Stream existing + poll for appends
        pos = 0
        idle = 0
        while True:
            if log_path.exists():
                data = log_path.read_text(encoding="utf-8", errors="replace")
                if len(data) > pos:
                    await websocket.send_text(data[pos:])
                    pos = len(data)
                    idle = 0
                else:
                    idle += 1
            info = jobs.get(job_id)
            if info and info.status in {
                JobStatus.COMPLETED,
                JobStatus.FAILED,
                JobStatus.CANCELLED,
            }:
                if log_path.exists():
                    data = log_path.read_text(encoding="utf-8", errors="replace")
                    if len(data) > pos:
                        await websocket.send_text(data[pos:])
                await websocket.send_text(f"\n[Aegis] job {info.status.value}\n")
                break
            import asyncio

            await asyncio.sleep(0.4)
            if idle > 750:  # ~5 min idle cap
                break
    except WebSocketDisconnect:
        return


# Re-export for analysis used by jobs module
__all__ = ["app", "analyze_job_dir", "write_cascade_input", "write_implant_input", "run_anneal_stub_or_real"]
