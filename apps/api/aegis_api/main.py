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
from fastapi.responses import FileResponse, Response
from pydantic import ValidationError

# Repo paths: .../apps/api/aegis_api/main.py → parents[3] = repo root
REPO_ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = REPO_ROOT / "packages" / "schema"
ENGINES_PATH = REPO_ROOT / "engines"
sys.path.insert(0, str(SCHEMA_PATH))
sys.path.insert(0, str(ENGINES_PATH))

from aegis_schema import (  # noqa: E402
    DoeCampaignCreate,
    DoeCampaignInfo,
    EngineStatus,
    HpcExportRequest,
    JobCreate,
    JobInfo,
    JobStatus,
    KartAnnealRequest,
    KmcRecommendRequest,
    MlKmcAnnealRequest,
    ClusterDynamicsRequest,
    KmcRecommendResponse,
    KmcTier,
    LammpsRunParams,
    Material,
    MaterialUpdate,
    Potential,
    PotentialAcquireResponse,
    PotentialDownloadRequest,
    PotentialFormalism,
    PotentialHybridStitchRequest,
    PotentialImportEntryRequest,
    PotentialLibraryEntry,
    PotentialLiteratureRequest,
    PotentialUploadMeta,
    Scenario,
)
from kart.adapter import discover_kart, run_anneal_stub_or_real  # noqa: E402
from ml_kmc.adapter import discover_ml_kmc, run_ml_kmc_anneal  # noqa: E402
from cluster_dynamics.adapter import run_cluster_dynamics  # noqa: E402
from mmonca.adapter import discover_mmonca  # noqa: E402
from lammps.templates import write_cascade_input, write_implant_input  # noqa: E402

from aegis_api.analysis import analyze_job_dir  # noqa: E402
from aegis_api.campaigns import CampaignManager, write_campaign_submit_helper, write_hpc_pack  # noqa: E402
from aegis_api.jobs import JobManager  # noqa: E402
from aegis_api.nist_potentials import (  # noqa: E402
    build_acquire_plan,
    download_bytes,
    filter_library,
    guess_formalism,
    load_library_index,
    parse_nist_entry_downloads,
)
from aegis_api.store import DataStore  # noqa: E402

DATA_ROOT = Path(os.environ.get("AEGIS_DATA_ROOT") or (REPO_ROOT / "data"))
RUNS_ROOT = Path(os.environ.get("AEGIS_RUNS_ROOT") or (REPO_ROOT / "runs"))
RUNS_ROOT.mkdir(parents=True, exist_ok=True)

store = DataStore(DATA_ROOT)
jobs = JobManager(RUNS_ROOT, store)
campaigns = CampaignManager(RUNS_ROOT, jobs, store)

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
    mmonca = discover_mmonca()
    mlk = discover_ml_kmc()
    from aegis_api.dxa import discover_ovito
    from aegis_api.lattice_relax import discover_ase, discover_atomsk

    ase = discover_ase()
    ovito = discover_ovito()
    atomsk = discover_atomsk()
    return EngineStatus(
        lammps_found=path is not None,
        lammps_path=path,
        lammps_version=version,
        kart_root=kart.get("kart_root"),
        kart_found=bool(kart.get("kart_found")),
        kart_binary=kart.get("kart_binary"),
        kart_commit_expected=kart.get("kart_commit_expected", "62d66adf"),
        kart_message=kart.get("kart_message", ""),
        mmonca_found=bool(mmonca.get("mmonca_found")),
        mmonca_path=mmonca.get("mmonca_path"),
        mmonca_message=mmonca.get("mmonca_message", ""),
        ml_kmc_onnx_found=bool(mlk.get("ml_kmc_onnx_found")),
        ml_kmc_onnx_path=mlk.get("ml_kmc_onnx_path"),
        onnxruntime_found=bool(mlk.get("onnxruntime_found")),
        ml_kmc_message=mlk.get("ml_kmc_message", ""),
        ase_found=bool(ase.get("ase_found")),
        ase_message=str(ase.get("ase_message", "")),
        ovito_found=bool(ovito.get("ovito_found")),
        ovito_path=ovito.get("ovito_path"),
        ovito_message=str(ovito.get("ovito_message", "")),
        ovito_mode=str(ovito.get("ovito_mode", "")),
        ovito_version=ovito.get("ovito_version"),
        atomsk_found=bool(atomsk.get("atomsk_found")),
        atomsk_path=atomsk.get("atomsk_path"),
    )


@app.get("/api/crystals")
def list_crystal_systems() -> dict[str, Any]:
    from lammps import crystal as crystal_reg
    from aegis_api.interstitial_ef import load_interstitial_ef

    return {
        "crystals": crystal_reg.list_crystals(),
        "interstitial_ef": load_interstitial_ef(),
    }


@app.get("/api/crystals/{crystal_id}/interstitials")
def crystal_interstitials(crystal_id: str, host: str | None = None, geometry: str | None = None) -> dict[str, Any]:
    from aegis_api.interstitial_ef import lookup_interstitial_ef

    rows = lookup_interstitial_ef(crystal=crystal_id, host=host, geometry=geometry)
    return {"crystal": crystal_id, "entries": rows}


@app.post("/api/materials/{material_id}/lattice-relax")
def lattice_relax(material_id: str) -> dict[str, Any]:
    m = store.get_material(material_id)
    if not m:
        raise HTTPException(404, "material not found")
    from aegis_api.lattice_relax import try_ase_relax

    return try_ase_relax(m.model_dump())


@app.post("/api/structure/preview")
def structure_preview(payload: dict[str, Any]) -> dict[str, Any]:
    """Build a temporary structure.data and return metadata (atom count, backend, box)."""
    material_id = str(payload.get("material_id") or "")
    params = dict(payload.get("params") or {})
    m = store.get_material(material_id) if material_id else None
    if payload.get("material"):
        try:
            m = Material(**payload["material"])
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"invalid material: {exc}") from exc
    if not m:
        raise HTTPException(400, "material_id or material required")
    kind = str(
        getattr(params.get("structure_kind"), "value", params.get("structure_kind"))
        or "single_crystal"
    ).lower()
    if kind in {"", "single_crystal"}:
        return {
            "kind": "single_crystal",
            "backend": "lammps_lattice",
            "atom_count": None,
            "note": "Single crystal uses LAMMPS lattice + create_atoms (no structure.data).",
        }
    import tempfile

    from lammps.structure import build_structure, needs_structure_file

    if not needs_structure_file(params):
        raise HTTPException(400, f"structure_kind={kind} does not build a file")
    # Defaults for preview cell
    params.setdefault("nx", 6)
    params.setdefault("ny", 6)
    params.setdefault("nz", 6)
    params.setdefault("seed", 42)
    try:
        with tempfile.TemporaryDirectory(prefix="aegis-struct-") as tmp:
            tmp_path = Path(tmp)
            meta = build_structure(tmp_path, material=m.model_dump(mode="json"), params=params)
            # Lightweight atom sample for visual preview (not MD)
            sample: list[dict[str, Any]] = []
            data = tmp_path / "structure.data"
            if data.exists():
                try:
                    from ase.io import read

                    atoms = read(str(data), format="lammps-data")
                    symbols = atoms.get_chemical_symbols()
                    pos = atoms.get_positions()
                    max_prev = 4000
                    step = max(1, len(atoms) // max_prev)
                    type_symbols = list(meta.get("type_symbols") or [])
                    if not type_symbols:
                        # unique order of appearance
                        seen: set[str] = set()
                        for s in symbols:
                            if s not in seen:
                                seen.add(s)
                                type_symbols.append(s)
                    sym_to_type = {s: i + 1 for i, s in enumerate(type_symbols)}
                    for i in range(0, len(atoms), step):
                        if len(sample) >= max_prev:
                            break
                        sample.append(
                            {
                                "id": i + 1,
                                "type": int(sym_to_type.get(str(symbols[i]), 1)),
                                "x": float(pos[i][0]),
                                "y": float(pos[i][1]),
                                "z": float(pos[i][2]),
                            }
                        )
                    cell = atoms.get_cell()
                    meta["preview_atoms"] = sample
                    meta["preview_truncated"] = len(atoms) > len(sample)
                    meta["preview_n_full"] = len(atoms)
                    meta.setdefault(
                        "box_A",
                        [float(cell[0, 0]), float(cell[1, 1]), float(cell[2, 2])],
                    )
                    meta["type_symbols"] = type_symbols
                except Exception as preview_exc:  # noqa: BLE001
                    meta["preview_note"] = f"atom sample unavailable: {preview_exc}"
            return meta
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"structure preview failed: {exc}") from exc


@app.post("/api/structure/import")
async def structure_import(file: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a LAMMPS data / ASE-readable structure for structure_kind=import."""
    imports = DATA_ROOT / "imports"
    imports.mkdir(parents=True, exist_ok=True)
    safe = Path(file.filename or "structure.data").name.replace("..", "_")
    dest = imports / f"{uuid.uuid4().hex[:10]}_{safe}"
    raw = await file.read()
    if not raw:
        raise HTTPException(400, "empty upload")
    dest.write_bytes(raw)
    # Validate by importing into a temp structure.data
    import tempfile

    from lammps.structure.import_backend import import_structure

    try:
        with tempfile.TemporaryDirectory(prefix="aegis-import-") as tmp:
            meta = import_structure(dest, Path(tmp) / "structure.data")
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        raise HTTPException(400, str(exc)) from exc
    return {
        "path": str(dest),
        "filename": dest.name,
        "atom_count": meta.get("atom_count"),
        "note": meta.get("note"),
        "hint": "Set structure_kind=import and structure_import_path to this path (or relative under the job dir after copy).",
    }


@app.get("/api/materials/{material_id}/export-poscar")
def export_material_poscar(material_id: str, nx: int = 1, ny: int = 1, nz: int = 1) -> Response:
    m = store.get_material(material_id)
    if not m:
        raise HTTPException(404, "material not found")
    from aegis_api.lattice_relax import export_poscar

    try:
        text = export_poscar(m.model_dump(), nx=nx, ny=ny, nz=nz)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    return Response(
        content=text,
        media_type="text/plain",
        headers={"Content-Disposition": f'attachment; filename="{material_id}.POSCAR"'},
    )


@app.post("/api/materials/{material_id}/lattice-from-poscar")
async def lattice_from_poscar(material_id: str, file: UploadFile = File(...)) -> Material:
    m = store.get_material(material_id)
    if not m:
        raise HTTPException(404, "material not found")
    from aegis_api.lattice_relax import parse_lattice_from_poscar

    raw = (await file.read()).decode("utf-8", errors="replace")
    try:
        lat = parse_lattice_from_poscar(raw)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    data = m.model_dump(mode="json")
    data["lattice_constant_A"] = lat["lattice_constant_A"]
    if lat.get("lattice_c_A"):
        data["lattice_c_A"] = lat["lattice_c_A"]
    return store.save_material(Material(**data))


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
    data = m.model_dump(mode="json")
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


@app.get("/api/potentials/library", response_model=list[PotentialLibraryEntry])
def list_potential_library(
    material_id: str | None = None,
    elements: str | None = None,
    q: str = "",
    source: str | None = None,
) -> list[PotentialLibraryEntry]:
    raw = load_library_index(DATA_ROOT / "potentials" / "library_index.json")
    el_list: list[str] | None = None
    if elements:
        el_list = [x for x in elements.replace(",", " ").split() if x]
    elif material_id:
        m = store.get_material(material_id)
        if not m:
            raise HTTPException(404, "material not found")
        el_list = [e.symbol for e in m.composition if e.atomic_percent > 0]
    filtered = filter_library(raw, elements=el_list, q=q, source=source)
    installed = store.installed_library_ids()
    out: list[PotentialLibraryEntry] = []
    for e in filtered:
        downloadable = bool(e.get("download_url"))
        fname = (e.get("filename") or "").lower()
        installed_flag = e.get("id") in installed or (fname and fname in installed)
        # Also mark installed if mapped catalog entry is available
        mapped = e.get("maps_to_catalog_id")
        if mapped:
            pot = store.get_potential(mapped)
            if pot and pot.available:
                installed_flag = True
        out.append(
            PotentialLibraryEntry(
                **{k: v for k, v in e.items() if k in PotentialLibraryEntry.model_fields},
                downloadable=downloadable,
                installed=bool(installed_flag),
            )
        )
    return out


@app.get("/api/potentials/acquire", response_model=PotentialAcquireResponse)
def acquire_potential_plan(material_id: str) -> PotentialAcquireResponse:
    """Ranked acquire plan for a material — find/import/attach only (never invent coeffs)."""
    m = store.get_material(material_id)
    if not m:
        raise HTTPException(404, "material not found")
    if bool(getattr(m, "metadata_only", False)):
        return PotentialAcquireResponse(
            material_id=material_id,
            elements=[e.symbol for e in m.composition if e.atomic_percent > 0],
            has_ready_potential=False,
            ready_potential_ids=[],
            compatible_potential_ids=[],
            suggestions=[],
            next_steps=[
                "This material is metadata_only — Aegis will not imply a runnable potential exists.",
                "Use a composition with published potentials, or upload a cited multi-element file under Upload.",
            ],
        )
    elements = [e.symbol for e in m.composition if e.atomic_percent > 0]
    raw = load_library_index(DATA_ROOT / "potentials" / "library_index.json")
    plan = build_acquire_plan(
        material_id=material_id,
        elements=elements,
        library_entries=raw,
        potentials=store.list_potentials(),
        installed_library_ids=store.installed_library_ids(),
    )
    return PotentialAcquireResponse(**plan)


@app.post("/api/potentials/library/download", response_model=Potential)
def download_library_potential(body: PotentialDownloadRequest) -> Potential:
    """Download a published file from NIST IPR (allowlisted) or register from URL."""
    lib_entry = None
    url = body.url
    name = body.name
    elements = body.elements
    style = body.lammps_pair_style
    attach_to = body.attach_to_id
    library_id = body.library_id
    pair_coeff = "pair_coeff * * {file} {elements}"
    citation = ""
    doi = ""
    source_url = ""
    warnings: list[str] = []

    if library_id:
        raw = load_library_index(DATA_ROOT / "potentials" / "library_index.json")
        lib_entry = next((e for e in raw if e.get("id") == library_id), None)
        if not lib_entry:
            raise HTTPException(404, "library entry not found")
        url = lib_entry.get("download_url")
        if not url:
            raise HTTPException(
                400,
                "This library entry is browse-only. Open the NIST/OpenKIM link, then Import URL or Upload.",
            )
        name = name or lib_entry.get("name")
        elements = elements or list(lib_entry.get("elements") or [])
        style = style or lib_entry.get("pair_style") or "eam/alloy"
        pair_coeff = lib_entry.get("pair_coeff_template") or pair_coeff
        citation = lib_entry.get("citation") or ""
        doi = lib_entry.get("doi") or ""
        source_url = lib_entry.get("entry_url") or ""
        warnings = list(lib_entry.get("warnings") or [])
        attach_to = attach_to or lib_entry.get("maps_to_catalog_id")

    if not url:
        raise HTTPException(400, "library_id or url required")
    try:
        content, filename = download_bytes(url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    if not content:
        raise HTTPException(400, "empty download")

    elements = elements or ["W"]
    style = (style or guess_formalism("", filename)).strip().lower()
    allowed_styles = {
        "eam",
        "eam/alloy",
        "eam/fs",
        "meam",
        "snap",
        "table",
        "zbl",
        "tersoff",
    }
    if style not in allowed_styles:
        # Still store file but mark pair style cautiously
        if style in {"", "other"}:
            style = guess_formalism("", filename)
        if style not in allowed_styles:
            raise HTTPException(
                400,
                f"pair_style '{style}' not supported for auto-download — "
                "use Hybrid / ZBL stitch for hybrid/overlay assemblies",
            )

    pot_id = attach_to or f"nist-{uuid.uuid4().hex[:10]}"
    dest_dir = DATA_ROOT / "potentials" / "user" / pot_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / (lib_entry.get("filename") if lib_entry and lib_entry.get("filename") else filename)
    dest.write_bytes(content)
    rel = str(dest.relative_to(DATA_ROOT)).replace("\\", "/")

    if attach_to and store.get_potential(attach_to):
        pot = store.attach_file(attach_to, rel)
        if not pot:
            raise HTTPException(404, "attach target not found")
        # Enrich metadata on a user shadow
        enriched = pot.model_dump()
        enriched["citation"] = citation or enriched.get("citation") or ""
        enriched["doi"] = doi or enriched.get("doi") or ""
        enriched["source_url"] = source_url or enriched.get("source_url") or url
        enriched["library_id"] = library_id
        enriched["lammps_pair_style"] = style
        try:
            enriched["formalism"] = PotentialFormalism(style if style != "eam" else "eam").value
        except ValueError:
            pass
        if elements:
            enriched["elements"] = elements
        if pair_coeff:
            enriched["pair_coeff_template"] = pair_coeff.replace(
                "{elements}", " ".join(elements)
            )
        warnings = list(enriched.get("warnings") or [])
        for w in list(lib_entry.get("warnings") or []) if lib_entry else []:
            if w not in warnings:
                warnings.append(w)
        for w in ["Downloaded from NIST IPR — verify citation before publication."]:
            if w not in warnings:
                warnings.append(w)
        # Strip leftover placeholder messaging after a real attach
        drop_needles = ("placeholder", "dry-run only", "not bundled", "upload required", "demo placeholder")
        warnings = [w for w in warnings if not any(n in w.lower() for n in drop_needles)]
        enriched["warnings"] = warnings
        enriched["source"] = "nist"
        return store.add_user_potential(Potential(**enriched))

    try:
        formalism = PotentialFormalism(style if style != "eam" else "eam")
    except ValueError:
        formalism = PotentialFormalism.OTHER

    pot = Potential(
        id=pot_id,
        name=name or filename,
        formalism=formalism,
        elements=elements,
        recommended_for=["cascade"],
        citation=citation,
        doi=doi,
        source_url=source_url or url,
        warnings=warnings
        + ["Downloaded from NIST IPR — verify citation before publication."],
        lammps_pair_style=style,
        pair_coeff_template=pair_coeff.replace("{elements}", " ".join(elements)),
        file_path=rel,
        source="nist",
        available=True,
        library_id=library_id,
    )
    return store.add_user_potential(pot)


@app.post("/api/potentials/library/import-entry")
def import_nist_entry(body: PotentialImportEntryRequest) -> dict[str, Any]:
    """Parse a NIST entry page for downloadable parameter files."""
    try:
        files = parse_nist_entry_downloads(body.entry_url)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"could not fetch NIST entry: {exc}") from exc
    return {"entry_url": body.entry_url, "files": files}


@app.post("/api/potentials/upload", response_model=Potential)
async def upload_potential(
    file: UploadFile = File(...),
    meta: str = Form(...),
) -> Potential:
    """Upload a published potential file; optional DOI/attestation for provenance."""
    try:
        meta_obj = PotentialUploadMeta.model_validate_json(meta)
    except ValidationError as exc:
        raise HTTPException(400, f"invalid meta: {exc}") from exc
    allowed_styles = {
        "eam",
        "eam/alloy",
        "eam/fs",
        "meam",
        "snap",
        "table",
        "zbl",
        "tersoff",
    }
    style = meta_obj.lammps_pair_style.strip().lower()
    if style not in allowed_styles:
        raise HTTPException(
            400,
            f"pair_style '{meta_obj.lammps_pair_style}' not in whitelist: {sorted(allowed_styles)}. "
            "Use Hybrid / ZBL stitch for hybrid/overlay assemblies.",
        )
    if not meta_obj.elements:
        raise HTTPException(400, "upload must declare at least one element")
    content = await file.read()
    if not content:
        raise HTTPException(400, "empty potential file")
    suffix = Path(file.filename or "potential.dat").name

    # Optional literature provenance when attestation + DOI provided on upload
    if meta_obj.attestation or meta_obj.doi or meta_obj.unpublished_research:
        from aegis_api.literature_potentials import validate_literature_request, write_literature_package

        errs = validate_literature_request(
            elements=meta_obj.elements,
            lammps_pair_style=style,
            doi=meta_obj.doi,
            citation=meta_obj.citation or meta_obj.notes,
            attestation=meta_obj.attestation,
            unpublished_research=meta_obj.unpublished_research,
            content=content,
        )
        if errs:
            raise HTTPException(400, "; ".join(errs))
        packed = write_literature_package(
            DATA_ROOT,
            name=meta_obj.name,
            elements=meta_obj.elements,
            lammps_pair_style=style,
            formalism=meta_obj.formalism.value if hasattr(meta_obj.formalism, "value") else str(meta_obj.formalism),
            doi=meta_obj.doi,
            citation=meta_obj.citation or meta_obj.notes,
            source_url=meta_obj.source_url,
            content=content,
            filename=suffix,
            attestation=meta_obj.attestation,
            unpublished_research=meta_obj.unpublished_research,
            notes=meta_obj.notes,
            attach_to_id=meta_obj.attach_to_id,
        )
        if meta_obj.attach_to_id:
            if not store.get_potential(meta_obj.attach_to_id):
                raise HTTPException(404, "attach_to_id not found")
            pot = store.attach_file(meta_obj.attach_to_id, packed["file_path"])
            if not pot:
                raise HTTPException(404, "attach target missing")
            data = pot.model_dump()
            for k in (
                "citation",
                "doi",
                "source_url",
                "warnings",
                "lammps_pair_style",
                "pair_coeff_template",
                "suitability",
                "provenance",
                "provenance_path",
                "elements",
                "source",
            ):
                if packed.get(k) is not None:
                    data[k] = packed[k]
            try:
                data["formalism"] = PotentialFormalism(
                    packed["formalism"] if packed["formalism"] != "eam" else "eam"
                ).value
            except ValueError:
                pass
            return store.add_user_potential(Potential(**data))
        return store.add_user_potential(Potential(**{k: v for k, v in packed.items() if k in Potential.model_fields}))

    if meta_obj.attach_to_id:
        if not store.get_potential(meta_obj.attach_to_id):
            raise HTTPException(404, "attach_to_id not found")
        pot_id = meta_obj.attach_to_id
        dest_dir = DATA_ROOT / "potentials" / "user" / pot_id
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest = dest_dir / suffix
        dest.write_bytes(content)
        rel = str(dest.relative_to(DATA_ROOT)).replace("\\", "/")
        pot = store.attach_file(pot_id, rel)
        if not pot:
            raise HTTPException(404, "attach target missing")
        # Refresh pair style from upload meta when attaching
        data = pot.model_dump()
        data["lammps_pair_style"] = style
        data["formalism"] = meta_obj.formalism.value if hasattr(meta_obj.formalism, "value") else str(meta_obj.formalism)
        data["elements"] = meta_obj.elements
        data["pair_coeff_template"] = meta_obj.pair_coeff_template.replace(
            "{elements}", " ".join(meta_obj.elements)
        )
        if meta_obj.name:
            data["name"] = meta_obj.name
        return store.add_user_potential(Potential(**data))

    pot_id = f"user-{uuid.uuid4().hex[:10]}"
    dest_dir = DATA_ROOT / "potentials" / "user" / pot_id
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / suffix
    dest.write_bytes(content)
    rel = str(dest.relative_to(DATA_ROOT)).replace("\\", "/")
    pot = Potential(
        id=pot_id,
        name=meta_obj.name,
        formalism=meta_obj.formalism,
        elements=meta_obj.elements,
        recommended_for=meta_obj.recommended_for or ["cascade"],
        citation=meta_obj.notes or "User-uploaded potential — unvalidated by Aegis.",
        warnings=["User-uploaded potential — unvalidated by Aegis."],
        lammps_pair_style=style,
        pair_coeff_template=meta_obj.pair_coeff_template.replace(
            "{elements}", " ".join(meta_obj.elements)
        ),
        file_path=rel,
        source="user",
        available=True,
        suitability="unvalidated",
    )
    store.add_user_potential(pot)
    return pot


@app.post("/api/potentials/from-literature", response_model=Potential)
def package_literature_potential(body: PotentialLiteratureRequest) -> Potential:
    """Package pasted published potential text with DOI/provenance (no coefficient invention)."""
    from aegis_api.literature_potentials import validate_literature_request, write_literature_package

    content = (body.content or "").encode("utf-8")
    errs = validate_literature_request(
        elements=body.elements,
        lammps_pair_style=body.lammps_pair_style,
        doi=body.doi,
        citation=body.citation,
        attestation=body.attestation,
        unpublished_research=body.unpublished_research,
        content=content,
    )
    if errs:
        raise HTTPException(400, "; ".join(errs))
    formalism = body.formalism.value if hasattr(body.formalism, "value") else str(body.formalism)
    packed = write_literature_package(
        DATA_ROOT,
        name=body.name,
        elements=body.elements,
        lammps_pair_style=body.lammps_pair_style,
        formalism=formalism,
        doi=body.doi,
        citation=body.citation,
        source_url=body.source_url,
        content=content,
        filename=body.filename or "literature.potential",
        attestation=body.attestation,
        unpublished_research=body.unpublished_research,
        notes=body.notes,
        attach_to_id=body.attach_to_id,
    )
    if body.attach_to_id:
        if not store.get_potential(body.attach_to_id):
            raise HTTPException(404, "attach_to_id not found")
        pot = store.attach_file(body.attach_to_id, packed["file_path"])
        if not pot:
            raise HTTPException(404, "attach target missing")
        data = pot.model_dump()
        for k, v in packed.items():
            if k in Potential.model_fields and v is not None:
                data[k] = v
        return store.add_user_potential(Potential(**data))
    return store.add_user_potential(Potential(**{k: v for k, v in packed.items() if k in Potential.model_fields}))


@app.post("/api/potentials/hybrid-stitch", response_model=Potential)
def hybrid_zbl_stitch(body: PotentialHybridStitchRequest) -> Potential:
    """Assemble hybrid/overlay host + ZBL from an existing pot + attested published cutoffs."""
    from aegis_api.hybrid_stitch import build_hybrid_overlay_potential, validate_hybrid_stitch

    host = store.get_potential(body.host_potential_id)
    if not host:
        raise HTTPException(404, "host_potential_id not found")
    host_file = store.resolve_potential_file(host)
    if not host_file or not host.available or host.is_placeholder:
        raise HTTPException(400, "Host potential must be an on-disk non-placeholder file.")
    els = body.elements or list(host.elements)
    pairs = [p.model_dump() for p in body.zbl_pairs]
    errs = validate_hybrid_stitch(
        host_pair_style=host.lammps_pair_style,
        elements=els,
        zbl_pairs=pairs,
        citation=body.citation,
        doi=body.doi,
        attestation=body.attestation,
    )
    if errs:
        raise HTTPException(400, "; ".join(errs))
    rel = str(host_file.relative_to(DATA_ROOT)).replace("\\", "/")
    packed = build_hybrid_overlay_potential(
        data_root=DATA_ROOT,
        host_pot=host.model_dump(mode="json"),
        host_file_rel=rel,
        elements=els,
        zbl_pairs=pairs,
        citation=body.citation,
        doi=body.doi,
        source_url=body.source_url,
        notes=body.notes,
        name=body.name,
    )
    return store.add_user_potential(Potential(**{k: v for k, v in packed.items() if k in Potential.model_fields}))


def _suitability_gate(potential: Potential, *, for_hpc: bool = False) -> None:
    """Raise HTTPException when suitability forbids the requested action."""
    suit = (potential.suitability or "").strip().lower()
    if suit == "ballistic_only":
        raise HTTPException(
            400,
            "Potential suitability is ballistic_only (e.g. ZBL-only) — not allowed for residual-damage MD / HPC export. "
            "Use a many-body or hybrid/overlay stitch with a published host potential.",
        )
    if for_hpc and suit in {"", "unvalidated"} and potential.source in {"literature", "hybrid_stitch", "user"}:
        raise HTTPException(
            400,
            "HPC export refuses unvalidated literature/hybrid/user potentials. "
            "Mark suitability after expert review, or use a NIST-downloaded published file with citation.",
        )


@app.post("/api/jobs", response_model=JobInfo)
def create_job(body: JobCreate) -> JobInfo:
    from aegis_api.coverage import validate_cascade_pka, validate_potential_coverage

    material = body.material_override or store.get_material(body.material_id)
    if not material:
        raise HTTPException(404, "material not found")
    comps = [c for c in (material.composition or []) if float(getattr(c, "atomic_percent", 0) or 0) > 0]
    if not comps:
        raise HTTPException(400, "Material composition is empty — add at least one element with positive at%.")
    potential = store.get_potential(body.potential_id)
    if not potential:
        raise HTTPException(404, "potential not found")
    resolved = store.resolve_potential_file(potential)
    if not resolved:
        raise HTTPException(
            400,
            "Selected potential has no file on disk. Upload a potential file or place one under data/potentials/curated/.",
        )
    if not potential.available and not potential.is_placeholder:
        raise HTTPException(
            400,
            "Selected potential is not runnable. Upload a published potential file.",
        )
    if not potential.is_placeholder:
        _suitability_gate(potential, for_hpc=False)
    try:
        validate_potential_coverage(material, potential, body.run_params)
        validate_cascade_pka(material, body.run_params)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
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


@app.post("/api/campaigns", response_model=DoeCampaignInfo)
def create_campaign(body: DoeCampaignCreate) -> DoeCampaignInfo:
    from aegis_api.coverage import validate_cascade_pka, validate_potential_coverage

    material = body.base.material_override or store.get_material(body.base.material_id)
    if not material:
        raise HTTPException(404, "material not found")
    comps = [c for c in (material.composition or []) if float(getattr(c, "atomic_percent", 0) or 0) > 0]
    if not comps:
        raise HTTPException(400, "Material composition is empty — add at least one element with positive at%.")
    potential = store.get_potential(body.base.potential_id)
    if not potential:
        raise HTTPException(404, "potential not found")
    resolved = store.resolve_potential_file(potential)
    if not resolved:
        raise HTTPException(400, "Selected potential has no file on disk.")
    if not potential.available and not potential.is_placeholder:
        raise HTTPException(400, "Selected potential is not runnable.")
    if not potential.is_placeholder:
        _suitability_gate(potential, for_hpc=False)
    try:
        validate_potential_coverage(material, potential, body.base.run_params)
        validate_cascade_pka(material, body.base.run_params)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Large cell guard (same as single-job path; campaigns auto-confirm in create otherwise)
    cells = body.base.run_params.nx * body.base.run_params.ny * body.base.run_params.nz
    if cells > 20 * 20 * 20 and not body.base.run_params.confirm_large:
        raise HTTPException(
            400,
            "Large cell (>20³ unit cells). Set confirm_large=true on the base recipe to proceed.",
        )
    try:
        return campaigns.create(body, material, potential)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/campaigns", response_model=list[DoeCampaignInfo])
def list_campaigns() -> list[DoeCampaignInfo]:
    return campaigns.list_campaigns()


@app.get("/api/campaigns/{campaign_id}", response_model=DoeCampaignInfo)
def get_campaign(campaign_id: str) -> DoeCampaignInfo:
    info = campaigns.get(campaign_id)
    if not info:
        raise HTTPException(404, "campaign not found")
    refreshed = campaigns.refresh_summary(campaign_id)
    return refreshed or info


@app.post("/api/jobs/{job_id}/hpc-export")
def export_job_hpc(job_id: str, body: HpcExportRequest) -> FileResponse:
    info = jobs.get(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    pot = store.get_potential(info.potential_id)
    if pot and not pot.is_placeholder:
        _suitability_gate(pot, for_hpc=True)
    job_dir = RUNS_ROOT / job_id
    in_path = job_dir / "in.aegis"
    need_prepare = True
    if in_path.exists():
        head = in_path.read_text(encoding="utf-8", errors="replace")[:240]
        # Re-prepare if dry-run / HPC stub so packs are not silent SC/stub only
        if "Aegis dry-run stub" in head or "Aegis HPC stub" in head:
            need_prepare = True
        else:
            need_prepare = False
    if need_prepare:
        try:
            jobs.prepare_inputs(job_id)
        except Exception as exc:  # noqa: BLE001
            raise HTTPException(400, f"could not prepare inputs: {exc}") from exc
    if not (job_dir / "in.aegis").exists():
        raise HTTPException(400, "job has no in.aegis yet — wait until the run starts preparing inputs")
    # Refuse shipping an HPC stub as if it were production-ready
    head = (job_dir / "in.aegis").read_text(encoding="utf-8", errors="replace")[:240]
    if "Aegis HPC stub" in head or "Aegis dry-run stub" in head:
        raise HTTPException(
            400,
            "HPC export refused: inputs are still a dry-run/placeholder stub. "
            "Upload a published potential (and supported crystal) then export again.",
        )
    pack_dir = job_dir / "hpc_pack"
    if pack_dir.exists():
        shutil.rmtree(pack_dir)
    zip_path = write_hpc_pack(job_dir, out_dir=pack_dir, req=body, job_id=job_id)
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")


def _in_aegis_is_stub(job_dir: Path) -> bool:
    in_path = job_dir / "in.aegis"
    if not in_path.exists():
        return True
    head = in_path.read_text(encoding="utf-8", errors="replace")[:240]
    return "Aegis HPC stub" in head or "Aegis dry-run stub" in head


@app.post("/api/campaigns/{campaign_id}/hpc-export")
def export_campaign_hpc(campaign_id: str, body: HpcExportRequest) -> FileResponse:
    info = campaigns.get(campaign_id)
    if not info:
        raise HTTPException(404, "campaign not found")
    # Suitability gate from first case job's potential (campaigns share one base pot)
    for case in info.cases:
        if not case.job_id:
            continue
        job_info = jobs.get(case.job_id)
        if not job_info:
            continue
        pot = store.get_potential(job_info.potential_id)
        if pot and not pot.is_placeholder:
            _suitability_gate(pot, for_hpc=True)
        break
    root = RUNS_ROOT / "campaigns" / campaign_id / "hpc_bundle"
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True, exist_ok=True)
    exported = 0
    case_dirs: list[str] = []
    prepare_errors: list[str] = []
    for case in info.cases:
        if not case.job_id:
            continue
        job_dir = RUNS_ROOT / case.job_id
        need_prepare = True
        if (job_dir / "in.aegis").exists() and not _in_aegis_is_stub(job_dir):
            need_prepare = False
        if need_prepare:
            try:
                jobs.prepare_inputs(case.job_id)
            except Exception as exc:  # noqa: BLE001
                prepare_errors.append(f"{case.job_id}: {exc}")
                continue
        if not (job_dir / "in.aegis").exists():
            prepare_errors.append(f"{case.job_id}: in.aegis still missing after prepare")
            continue
        if _in_aegis_is_stub(job_dir):
            prepare_errors.append(
                f"{case.job_id}: skipped dry-run/placeholder stub "
                "(upload a published potential + supported crystal)"
            )
            continue
        case_out = root / case.job_id
        write_hpc_pack(job_dir, out_dir=case_out, req=body, job_id=case.job_id, make_zip=False)
        case_dirs.append(case.job_id)
        exported += 1
    if exported == 0:
        detail = "; ".join(prepare_errors[:5]) if prepare_errors else "no cases with prepared inputs"
        raise HTTPException(
            400,
            f"no production-ready cases for HPC export ({detail}). "
            "Stub/dry-run inputs are refused.",
        )
    if prepare_errors:
        (root / "prepare_warnings.txt").write_text(
            "\n".join(prepare_errors) + "\n",
            encoding="utf-8",
        )
    write_campaign_submit_helper(root, body, case_dirs)
    import zipfile

    zip_path = root.parent / f"{campaign_id}_hpc_bundle.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in root.rglob("*"):
            if f.is_file():
                zf.write(f, arcname=str(f.relative_to(root.parent)))
    return FileResponse(zip_path, filename=zip_path.name, media_type="application/zip")


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
    if "/" in name or "\\" in name or ".." in name:
        raise HTTPException(400, "invalid artifact name")
    job_root = (RUNS_ROOT / job_id).resolve()
    path = (job_root / name).resolve()
    try:
        path.relative_to(job_root)
    except ValueError as exc:
        raise HTTPException(400, "invalid artifact path") from exc
    if not path.exists() or not path.is_file():
        raise HTTPException(404, "artifact not found")
    return FileResponse(path)


@app.get("/api/jobs/{job_id}/defects")
def get_defects(job_id: str) -> dict[str, Any]:
    path = RUNS_ROOT / job_id / "defects.json"
    if not path.exists():
        raise HTTPException(404, "defects not ready")
    return json.loads(path.read_text(encoding="utf-8"))


@app.post("/api/kmc/recommend", response_model=KmcRecommendResponse)
def recommend_kmc_route(body: KmcRecommendRequest) -> KmcRecommendResponse:
    """Preview KMC tier routing for UI (Adjanor 2025 / Huang 2023 ladder)."""
    from kmc.router import recommend_kmc

    material = store.get_material(body.material_id)
    if not material:
        raise HTTPException(404, "material not found")
    kart_info = discover_kart()
    plan = recommend_kmc(
        material=material.model_dump(mode="json"),
        target_time_s=body.target_time_s,
        temperature_K=body.temperature_K,
        run_kart_anneal=body.run_kart_anneal,
        run_mmonca_okmc=body.run_mmonca_okmc,
        kart_found=bool(kart_info.get("kart_found")),
        structure_kind=body.structure_kind,
        requested_tier=body.kmc_tier.value if body.kmc_tier else None,
    )
    return KmcRecommendResponse(
        recommended_tier=KmcTier(plan["recommended_tier"]),
        warnings=list(plan.get("warnings") or []),
        notes=list(plan.get("notes") or []),
        concentrated_alloy=bool(plan.get("concentrated_alloy")),
        prefactor_model_hint=str(plan.get("prefactor_model_hint") or "unknown"),
        trapping_risk_hint=str(plan.get("trapping_risk_hint") or "unknown"),
        target_time_s=float(plan.get("target_time_s") or body.target_time_s),
        temperature_K=float(plan.get("temperature_K") or body.temperature_K),
    )


@app.get("/api/jobs/{job_id}/kart")
def get_kart_summary(job_id: str) -> dict[str, Any]:
    info = jobs.get(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    path = RUNS_ROOT / job_id / "kart_summary.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if info.kart_summary:
        return info.kart_summary
    raise HTTPException(404, "kart summary not ready")


@app.post("/api/jobs/{job_id}/kart/anneal")
def post_kart_anneal(job_id: str, body: KartAnnealRequest) -> dict[str, Any]:
    """Phase-2 DOE: re-anneal an existing cascade at one or more temperatures."""
    info = jobs.get(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    if info.status != JobStatus.COMPLETED:
        raise HTTPException(400, f"job status {info.status} cannot anneal yet (need completed cascade)")
    job_dir = RUNS_ROOT / job_id
    if not (job_dir / "defects.json").exists() and not list(job_dir.glob("dump*.lammpstrj")):
        raise HTTPException(400, "no cascade dumps/defects available for handoff")
    jobs._update(job_id, status=JobStatus.ANNEALING, message="KART DOE anneal")
    try:
        from kmc.router import recommend_kmc

        material = store.get_material(info.material_id) if info.material_id else None
        req_path = job_dir / "request.json"
        req = json.loads(req_path.read_text(encoding="utf-8")) if req_path.exists() else {}
        sk = str(
            getattr(info.run_params.structure_kind, "value", info.run_params.structure_kind)
            or "single_crystal"
        )
        router = recommend_kmc(
            material=material.model_dump(mode="json") if material else None,
            target_time_s=float(body.max_kmc_time_s),
            temperature_K=float(body.temperature_K),
            run_kart_anneal=True,
            run_mmonca_okmc=bool(req.get("run_mmonca_okmc")),
            kart_found=True,
            structure_kind=sk.lower(),
            defect_summary=info.defect_summary if isinstance(info.defect_summary, dict) else None,
            requested_tier=req.get("kmc_tier"),
        )
        summary = run_anneal_stub_or_real(
            job_dir,
            temperature_K=body.temperature_K,
            max_events=body.max_events,
            max_wall_s=body.max_wall_s,
            max_kmc_time_s=body.max_kmc_time_s,
            temperatures=body.temperatures,
            material=material.model_dump(mode="json") if material else None,
            router=router,
            prefactor_compare=bool(body.prefactor_compare),
        )
        kmc_prov = None
        if isinstance(summary, dict) and isinstance(summary.get("provenance"), dict):
            try:
                from aegis_schema import KmcProvenance

                kmc_prov = KmcProvenance(**summary["provenance"])
            except Exception:  # noqa: BLE001
                kmc_prov = None
        jobs._update(
            job_id,
            status=JobStatus.COMPLETED,
            message="completed",
            kart_summary=summary,
            defect_summary=info.defect_summary,
            kmc_provenance=kmc_prov,
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        # Keep cascade COMPLETED — anneal is a post-step; surface error on kart_summary only.
        err_summary = {
            **(info.kart_summary or {}),
            "error": str(exc),
            "anneal_failed": True,
        }
        jobs._update(
            job_id,
            status=JobStatus.COMPLETED,
            message=f"cascade completed; anneal failed: {exc}",
            kart_summary=err_summary,
            defect_summary=info.defect_summary,
        )
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/jobs/{job_id}/ml-kmc")
def get_ml_kmc_summary(job_id: str) -> dict[str, Any]:
    info = jobs.get(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    path = RUNS_ROOT / job_id / "ml_kmc_summary.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if info.ml_kmc_summary:
        return info.ml_kmc_summary
    raise HTTPException(404, "ml-kmc summary not ready")


@app.post("/api/jobs/{job_id}/ml-kmc/anneal")
def post_ml_kmc_anneal(job_id: str, body: MlKmcAnnealRequest) -> dict[str, Any]:
    """Phase E: rigid-lattice ML-KMC on a completed cascade (Huang 2023 path)."""
    info = jobs.get(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    if info.status != JobStatus.COMPLETED:
        raise HTTPException(400, f"job status {info.status} cannot anneal yet (need completed cascade)")
    job_dir = RUNS_ROOT / job_id
    from kmc.router import recommend_kmc

    material = store.get_material(info.material_id) if info.material_id else None
    router = recommend_kmc(
        material=material.model_dump(mode="json") if material else None,
        target_time_s=1.0,
        temperature_K=float(body.temperature_K),
        run_kart_anneal=False,
        kart_found=False,
        requested_tier="ml_kmc",
    )
    jobs._update(job_id, status=JobStatus.ANNEALING, message="ML-KMC anneal")
    try:
        summary = run_ml_kmc_anneal(
            job_dir,
            temperature_K=body.temperature_K,
            n_steps=body.n_steps,
            structure_class=body.structure_class,
            nu_model=body.nu_model,
            onnx_path=body.onnx_path,
            seed=body.seed,
            router=router,
        )
        kmc_prov = None
        if isinstance(summary.get("provenance"), dict):
            try:
                from aegis_schema import KmcProvenance

                kmc_prov = KmcProvenance(**summary["provenance"])
            except Exception:  # noqa: BLE001
                kmc_prov = None
        jobs._update(
            job_id,
            status=JobStatus.COMPLETED,
            message="completed",
            ml_kmc_summary=summary,
            defect_summary=info.defect_summary,
            kmc_provenance=kmc_prov or info.kmc_provenance,
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        jobs._update(
            job_id,
            status=JobStatus.COMPLETED,
            message=f"cascade completed; ML-KMC failed: {exc}",
            defect_summary=info.defect_summary,
        )
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/jobs/{job_id}/cluster-dynamics")
def get_cd_summary(job_id: str) -> dict[str, Any]:
    info = jobs.get(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    path = RUNS_ROOT / job_id / "cd_summary.json"
    if path.exists():
        return json.loads(path.read_text(encoding="utf-8"))
    if info.cd_summary:
        return info.cd_summary
    raise HTTPException(404, "cluster-dynamics summary not ready")


@app.post("/api/jobs/{job_id}/cluster-dynamics/run")
def post_cd_run(job_id: str, body: ClusterDynamicsRequest) -> dict[str, Any]:
    info = jobs.get(job_id)
    if not info:
        raise HTTPException(404, "job not found")
    if info.status != JobStatus.COMPLETED:
        raise HTTPException(400, f"job status {info.status} cannot run CD yet")
    job_dir = RUNS_ROOT / job_id
    from kmc.router import recommend_kmc

    material = store.get_material(info.material_id) if info.material_id else None
    router = recommend_kmc(
        material=material.model_dump(mode="json") if material else None,
        target_time_s=float(body.target_time_s),
        temperature_K=float(body.temperature_K),
        requested_tier="stochastic_cd",
    )
    jobs._update(job_id, status=JobStatus.ANNEALING, message="cluster dynamics")
    try:
        summary = run_cluster_dynamics(
            job_dir,
            temperature_K=body.temperature_K,
            target_time_s=body.target_time_s,
            volume_cm3=body.volume_cm3,
            max_events=body.max_events,
            catalog_path=body.catalog_path,
            seed=body.seed,
            router=router,
        )
        kmc_prov = None
        if isinstance(summary.get("provenance"), dict):
            try:
                from aegis_schema import KmcProvenance

                kmc_prov = KmcProvenance(**summary["provenance"])
            except Exception:  # noqa: BLE001
                kmc_prov = None
        jobs._update(
            job_id,
            status=JobStatus.COMPLETED,
            message="completed",
            cd_summary=summary,
            defect_summary=info.defect_summary,
            kmc_provenance=kmc_prov or info.kmc_provenance,
        )
        return summary
    except Exception as exc:  # noqa: BLE001
        jobs._update(
            job_id,
            status=JobStatus.COMPLETED,
            message=f"cascade completed; CD failed: {exc}",
            defect_summary=info.defect_summary,
        )
        raise HTTPException(500, str(exc)) from exc


@app.get("/api/engines/ovito")
def ovito_status() -> dict[str, Any]:
    """OVITO discovery + install hints for the Engines / DXA panels."""
    from aegis_api.dxa import discover_ovito, install_ovito_hint

    info = discover_ovito()
    info["install"] = install_ovito_hint()
    return info


@app.post("/api/engines/ovito/install")
def ovito_pip_install() -> dict[str, Any]:
    """Best-effort ``pip install -U ovito`` into the running API interpreter."""
    import subprocess
    import sys

    from aegis_api.dxa import discover_ovito, install_ovito_hint

    hint = install_ovito_hint()
    pip_spec = str(hint.get("pip_spec") or "ovito==3.15.5")
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", pip_spec],
            capture_output=True,
            text=True,
            timeout=600,
            check=False,
        )
        ok = proc.returncode == 0
        info = discover_ovito()
        return {
            "ok": ok and bool(info.get("ovito_found")),
            "returncode": proc.returncode,
            "stdout_tail": (proc.stdout or "")[-2000:],
            "stderr_tail": (proc.stderr or "")[-2000:],
            "discover": info,
            "install": hint,
            "message": (
                "OVITO installed — refresh Engines / run DXA"
                if ok and info.get("ovito_found")
                else "pip finished with errors — see stderr_tail or install OVITO Pro and set AEGIS_OVITO_BIN"
            ),
        }
    except Exception as exc:  # noqa: BLE001
        return {
            "ok": False,
            "message": str(exc),
            "install": hint,
            "discover": discover_ovito(),
        }


@app.get("/api/jobs/{job_id}/cascade-timeline")
def get_cascade_timeline(job_id: str) -> dict[str, Any]:
    """Heuristic growth/peak/quench/residual schedule written with the cascade input."""
    job_dir = RUNS_ROOT / job_id
    path = job_dir / "cascade_timeline.json"
    if not path.exists():
        raise HTTPException(404, "cascade timeline not available (run a cascade job with auto stages)")
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/api/jobs/{job_id}/dxa")
def get_job_dxa(job_id: str, refresh: bool = False) -> dict[str, Any]:
    """Return cached DXA summary. Only run OVITO when ``refresh=true`` (explicit UI action)."""
    job_dir = RUNS_ROOT / job_id
    if not job_dir.exists():
        raise HTTPException(404, "job not found")
    from aegis_api.dxa import load_dxa_summary, run_dxa_on_job

    if refresh:
        return run_dxa_on_job(job_dir)
    data = load_dxa_summary(job_dir)
    if not data:
        raise HTTPException(404, "DXA summary not available")
    return data


@app.get("/api/jobs/{job_id}/dxa/ca")
def download_dxa_ca(job_id: str) -> FileResponse:
    """Download OVITO Crystal Analysis (``.ca``) network for desktop inspection."""
    job_dir = RUNS_ROOT / job_id
    path = job_dir / "dislocations.ca"
    if not path.exists():
        raise HTTPException(404, "dislocations.ca not found — run DXA first")
    return FileResponse(path, filename=f"aegis-{job_id}-dislocations.ca", media_type="text/plain")


@app.get("/api/jobs/{job_id}/trajectory")
def get_trajectory_index(job_id: str) -> dict[str, Any]:
    job_dir = RUNS_ROOT / job_id
    if not job_dir.exists():
        raise HTTPException(404, "job not found")
    from aegis_api.trajectory import list_trajectory_frames

    frames = list_trajectory_frames(job_dir)
    return {
        "job_id": job_id,
        "n_frames": len(frames),
        "frames": frames,
        "before_index": next((f["index"] for f in frames if f.get("role") == "before"), 0 if frames else None),
        "after_indices": [f["index"] for f in frames if f.get("role") != "before"],
    }


@app.get("/api/jobs/{job_id}/trajectory/{frame_index}")
def get_trajectory_frame(job_id: str, frame_index: int, max_atoms: int = 12000) -> dict[str, Any]:
    job_dir = RUNS_ROOT / job_id
    if not job_dir.exists():
        raise HTTPException(404, "job not found")
    from aegis_api.trajectory import get_trajectory_frame as _get_frame

    try:
        return _get_frame(job_dir, frame_index, max_atoms=max(100, min(max_atoms, 50000)))
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except IndexError as exc:
        raise HTTPException(400, str(exc)) from exc


@app.get("/api/jobs/{job_id}/animation.gif")
def get_job_animation_gif(
    job_id: str,
    max_frames: int = 40,
    max_atoms: int = 3000,
    size: int = 480,
    proj: str = "xy",
    duration_ms: int = 120,
    refresh: bool = False,
) -> Response:
    """2D projection GIF from dump frames (before + time series). Cached on disk."""
    job_dir = RUNS_ROOT / job_id
    if not job_dir.exists():
        raise HTTPException(404, "job not found")
    cache_path = job_dir / "animation.gif"
    # Serve cached GIF when query matches defaults (or any prior build) unless refresh
    use_cache = (
        not refresh
        and cache_path.exists()
        and max_frames == 40
        and max_atoms == 3000
        and size == 480
        and proj == "xy"
        and duration_ms == 120
    )
    if use_cache:
        return Response(
            content=cache_path.read_bytes(),
            media_type="image/gif",
            headers={"Content-Disposition": f'attachment; filename="aegis-{job_id}.gif"'},
        )
    from aegis_api.animation import build_trajectory_gif, cache_trajectory_gif

    try:
        gif = build_trajectory_gif(
            job_dir,
            max_frames=max(2, min(max_frames, 80)),
            max_atoms=max(100, min(max_atoms, 20000)),
            size=max(160, min(size, 1024)),
            proj=proj,
            duration_ms=max(40, min(duration_ms, 2000)),
        )
    except FileNotFoundError as exc:
        raise HTTPException(404, str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(503, str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(500, f"GIF render failed: {exc}") from exc

    # Cache default-parameter builds for quick re-download
    if max_frames == 40 and max_atoms == 3000 and size == 480 and proj == "xy" and duration_ms == 120:
        try:
            cache_trajectory_gif(job_dir, gif)
        except OSError:
            pass
    return Response(
        content=gif,
        media_type="image/gif",
        headers={"Content-Disposition": f'attachment; filename="aegis-{job_id}.gif"'},
    )


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
