"""Interstitial formation-energy catalog loader."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[3]
CATALOG = REPO_ROOT / "data" / "crystals" / "interstitial_ef.json"


def load_interstitial_ef() -> list[dict[str, Any]]:
    if not CATALOG.exists():
        return []
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def lookup_interstitial_ef(
    *,
    crystal: str,
    host: str | None = None,
    defect_species: str | None = None,
    geometry: str | None = None,
) -> list[dict[str, Any]]:
    rows = load_interstitial_ef()
    cry = (crystal or "").lower()
    out = [r for r in rows if str(r.get("crystal", "")).lower() == cry]
    if host:
        out = [r for r in out if str(r.get("host", "")).lower() == host.lower()]
    if defect_species:
        out = [r for r in out if str(r.get("defect_species", "")).lower() == defect_species.lower()]
    if geometry:
        out = [r for r in out if str(r.get("geometry", "")).lower() == geometry.lower()]
    return out


def suggest_defaults(
    crystal: str,
    host: str,
    defect_species: str,
    geometry: str,
) -> dict[str, Any] | None:
    rows = lookup_interstitial_ef(
        crystal=crystal, host=host, defect_species=defect_species, geometry=geometry
    )
    if not rows:
        rows = lookup_interstitial_ef(crystal=crystal, geometry=geometry)
    if not rows:
        rows = lookup_interstitial_ef(crystal=crystal)
    return rows[0] if rows else None
