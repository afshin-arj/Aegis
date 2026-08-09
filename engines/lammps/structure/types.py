"""Canonical LAMMPS type order for nanostructures (must match pair_coeff)."""

from __future__ import annotations

from typing import Any


def _norm(sym: str) -> str:
    s = str(sym or "").strip()
    if not s:
        return ""
    if len(s) == 1:
        return s.upper()
    return s[0].upper() + s[1:].lower()


def _kind(params: dict[str, Any]) -> str:
    raw = params.get("structure_kind") or "single_crystal"
    return str(getattr(raw, "value", raw) or "single_crystal").strip().lower()


def structure_type_symbols(
    material: dict[str, Any],
    params: dict[str, Any],
    *,
    mode: str | None = None,
) -> list[str]:
    """Ordered atom types for structure.data + pair_coeff / mass lines.

    Host composition order first, then precipitate / ion / interstitial extras.
    Never alphabetical — ASE writers must use this as ``specorder``.
    """
    mode_s = str(getattr(mode, "value", mode) or params.get("mode") or "cascade")
    mode_s = str(getattr(mode_s, "value", mode_s) or "cascade").strip().lower()
    out: list[str] = []
    seen: set[str] = set()

    def add(sym: str) -> None:
        n = _norm(sym)
        if not n or n.lower() in seen:
            return
        seen.add(n.lower())
        out.append(n)

    for c in material.get("composition") or []:
        if float(c.get("atomic_percent") or 0) > 0:
            add(str(c.get("symbol") or ""))
    if not out:
        add("W")

    if _kind(params) == "precipitate":
        add(str(params.get("precipitate_species") or "Re"))
    if mode_s in {"implant", "surface"}:
        add(str(params.get("ion_type") or "He"))
    elif mode_s == "interstitial":
        add(str(params.get("interstitial_species") or "He"))
    return out
