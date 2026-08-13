"""Load parameterized CD rates — never silently invent production coefficients."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

EXAMPLE = Path(__file__).resolve().parent / "data" / "rate_catalog.example.json"


def load_catalog(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else EXAMPLE
    if not p.is_file():
        return {
            "format": "aegis-cd-rate-catalog-v1",
            "channels": [],
            "volume_warn_cm3": 5e-10,
            "note": "catalog missing",
        }
    data = json.loads(p.read_text(encoding="utf-8"))
    data["catalog_path"] = str(p)
    data["is_example"] = p.resolve() == EXAMPLE.resolve()
    return data
