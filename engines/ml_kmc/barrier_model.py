"""Barrier prediction interface — user ONNX or honest heuristic fallback."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol


class BarrierModel(Protocol):
    name: str

    def predict_barrier(self, lac: dict[str, Any], pathway_dir: tuple[int, int, int]) -> float:
        ...


class HeuristicBarrierModel:
    """Composition-weighted dummy barrier — not a trained ANN.

    Used only when no ONNX weights are supplied. Mark results unvalidated.
    """

    name = "heuristic_lac"

    def predict_barrier(self, lac: dict[str, Any], pathway_dir: tuple[int, int, int]) -> float:
        vec = lac.get("weighted_vector") or []
        # bins per shell: [V, Ni, Fe, other, other]
        fe_w = 0.0
        ni_w = 0.0
        vac_w = 0.0
        for i in range(0, len(vec), 5):
            vac_w += float(vec[i]) if i < len(vec) else 0.0
            ni_w += float(vec[i + 1]) if i + 1 < len(vec) else 0.0
            fe_w += float(vec[i + 2]) if i + 2 < len(vec) else 0.0
        # Ni-rich neighborhoods slightly lower vacancy barrier (Huang trend, qualitative)
        base = 0.72 + 0.18 * (fe_w / (fe_w + ni_w + 1e-9)) - 0.04 * vac_w
        # Tiny direction jitter so 12 jumps are not identical
        jitter = 0.01 * ((pathway_dir[0] + 2 * pathway_dir[1] + 3 * pathway_dir[2]) % 5)
        return max(0.15, min(1.4, base + jitter))


class OnnxBarrierModel:
    name = "onnx_ann_lac"

    def __init__(self, path: Path):
        import onnxruntime as ort  # type: ignore[import-not-found]

        self.path = path
        self._sess = ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])
        self._input = self._sess.get_inputs()[0].name

    def predict_barrier(self, lac: dict[str, Any], pathway_dir: tuple[int, int, int]) -> float:
        import numpy as np

        vec = list(lac.get("weighted_vector") or [])
        vec.extend(pathway_dir)
        arr = np.asarray([vec], dtype="float32")
        out = self._sess.run(None, {self._input: arr})[0]
        val = float(out.reshape(-1)[0])
        return max(0.05, min(2.5, val))


def load_barrier_model(onnx_path: str | None) -> tuple[BarrierModel, str]:
    if onnx_path:
        p = Path(onnx_path)
        if p.is_file():
            try:
                return OnnxBarrierModel(p), "onnx"
            except Exception as exc:  # noqa: BLE001
                return HeuristicBarrierModel(), f"onnx_failed:{exc}"
        return HeuristicBarrierModel(), "onnx_missing"
    return HeuristicBarrierModel(), "heuristic"
