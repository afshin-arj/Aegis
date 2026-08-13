"""Job-facing ML-KMC adapter (cascade handoff → rigid-lattice anneal)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from kmc.provenance import build_provenance, merge_router_warnings
from ml_kmc.barrier_model import load_barrier_model
from ml_kmc.kmc_engine import run_rigid_kmc

REF_PATH = Path(__file__).resolve().parent / "data" / "ni_fe_d_reference.json"


def discover_ml_kmc() -> dict[str, Any]:
    onnx = os.environ.get("AEGIS_ML_KMC_ONNX", "").strip()
    try:
        import onnxruntime  # noqa: F401

        ort = True
    except Exception:  # noqa: BLE001
        ort = False
    return {
        "ml_kmc_onnx_found": bool(onnx and Path(onnx).is_file()),
        "ml_kmc_onnx_path": onnx or None,
        "onnxruntime_found": ort,
        "ml_kmc_message": (
            "ONNX model ready."
            if onnx and Path(onnx).is_file() and ort
            else "ML-KMC uses heuristic barriers until AEGIS_ML_KMC_ONNX + onnxruntime are set. "
            "Aegis does not ship Huang 32k NEB weights."
        ),
    }


def _load_reference() -> dict[str, Any]:
    if not REF_PATH.exists():
        return {}
    try:
        return json.loads(REF_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _compare_reference(einstein_d: float, x: float, t_k: float, ref: dict[str, Any]) -> dict[str, Any]:
    pts = list(ref.get("points") or [])
    if not pts or einstein_d <= 0:
        return {"status": "unvalidated", "note": "no comparable reference point"}
    # nearest (x, T)
    def _key(p: dict[str, Any]) -> float:
        return abs(float(p.get("x_Fe") or 0) - x) + abs(float(p.get("T_K") or 0) - t_k) / 1000.0

    best = min(pts, key=_key)
    return {
        "status": "reference_comparison",
        "matched": best,
        "note": "Relative D checkpoints only — do not treat Aegis D as calibrated to Huang Fig. 3.",
        "einstein_D_A2_s": einstein_d,
    }


def run_ml_kmc_anneal(
    job_dir: Path,
    *,
    temperature_K: float = 900.0,
    n_steps: int = 200,
    structure_class: str = "random",
    nu_model: str = "composition_polynomial",
    onnx_path: str | None = None,
    seed: int = 1,
    router: dict[str, Any] | None = None,
) -> dict[str, Any]:
    material: dict[str, Any] = {}
    if (job_dir / "material.json").exists():
        material = json.loads((job_dir / "material.json").read_text(encoding="utf-8"))
    composition = list(material.get("composition") or [{"symbol": "Ni", "atomic_percent": 100}])
    lattice = float(material.get("lattice_constant_A") or 3.52)
    disc = discover_ml_kmc()
    path = onnx_path or disc.get("ml_kmc_onnx_path")
    model, model_src = load_barrier_model(str(path) if path else None)
    result = run_rigid_kmc(
        composition=composition,
        temperature_K=temperature_K,
        n_steps=n_steps,
        lattice_A=lattice,
        structure_class=structure_class,
        nu_model=nu_model,
        barrier=model,
        seed=seed,
    )
    ref = _load_reference()
    cmp = _compare_reference(float(result.get("einstein_D_A2_s") or 0), float(result.get("x_solute") or 0), temperature_K, ref)
    synthetic = model_src != "onnx"
    validation = "reference_curve" if (not synthetic and cmp.get("status") == "reference_comparison") else (
        "unvalidated" if synthetic else "reference_comparison"
    )
    warnings = list((router or {}).get("warnings") or [])
    if nu_model == "constant":
        warnings.append(
            "Constant ν on ML-KMC — Huang 2023 shows composition-dependent attempt frequencies "
            "are required for CSA sluggish diffusion."
        )
    if synthetic:
        warnings.append("Heuristic LAC barriers (no user ONNX) — qualitative trends only.")
    prov = build_provenance(
        "ml_kmc",
        synthetic=synthetic,
        prefactor_model="composition_polynomial" if nu_model == "composition_polynomial" else "constant",
        structure_class="random" if structure_class == "random" else "mmc",
        trapping_risk="unknown",
        validation_status=validation if validation in {"energy_dat", "reference_curve", "stub", "handoff_ready", "unvalidated"} else "unvalidated",
        target_time_s=float(result.get("simulated_time_s") or 0),
        sro_parameters={
            f"alpha_{i+1}": float(a)
            for i, a in enumerate((result.get("sro") or {}).get("alpha") or [])
            if a is not None
        }
        or None,
        warnings=warnings,
    )
    work = job_dir / "ml_kmc_work"
    work.mkdir(parents=True, exist_ok=True)
    out: dict[str, Any] = {
        "format": "aegis-ml-kmc-summary-v1",
        "engine": "ml_kmc",
        "status": "annealed" if result.get("events") else "stubbed",
        "message": disc["ml_kmc_message"],
        "barrier_source": model_src,
        "temperature_K": temperature_K,
        "n_steps": n_steps,
        "reference": cmp,
        "provenance": merge_router_warnings(prov, router),
        **result,
    }
    (work / "summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    (job_dir / "ml_kmc_summary.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out
