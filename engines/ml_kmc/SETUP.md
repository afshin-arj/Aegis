# ML-KMC (rigid-lattice ANN-KMC)

Phase E implements the Huang et al. (*J. Alloys Compd.* 2023) **methodology** for concentrated-alloy vacancy diffusion: LAC features, composition-dependent attempt frequencies, and residence-time KMC on FCC.

Aegis does **not** ship the 32k NEB training set or pretrained ANN weights.

## What runs today

| Piece | Status |
|-------|--------|
| 4-shell FCC LAC extractor | Wired (`lac.py`) |
| Warren–Cowley SRO (1st–4th shell) | Wired (`sro.py`) |
| ν(T, x) polynomial vs constant Γ₀ | Wired (`nu_model.py`) |
| Rigid-lattice 12-NN vacancy KMC + Einstein D | Wired (`kmc_engine.py`) |
| ONNX ANN-LAC | Optional — `AEGIS_ML_KMC_ONNX` + `onnxruntime` |
| Heuristic barriers | Default when ONNX missing — `validation_status=unvalidated` |

## API

```text
POST /api/jobs/{id}/ml-kmc/anneal
GET  /api/jobs/{id}/ml-kmc
```

Job must be `completed` (cascade present). Results land in `runs/<id>/ml_kmc_summary.json`.

## Environment

| Variable | Meaning |
|----------|---------|
| `AEGIS_ML_KMC_ONNX` | Path to a user-trained ONNX model (input = weighted LAC + jump vector) |

```bash
pip install onnxruntime   # optional
```

## Honesty

- Heuristic D(T, x) is **not** a reproduction of Huang Fig. 3.
- `engines/ml_kmc/data/ni_fe_d_reference.json` holds sparse relative checkpoints for trend tests only.
- Constant ν on a CSA is flagged in the UI (Huang §attempt frequency).
