"""Shared potential ↔ species coverage checks for jobs and campaigns."""

from __future__ import annotations

from typing import Any


def host_symbols(material: Any) -> list[str]:
    comps = getattr(material, "composition", None) or []
    out: list[str] = []
    for c in comps:
        if isinstance(c, dict):
            pct = float(c.get("atomic_percent") or 0)
            sym = str(c.get("symbol") or "").strip()
        else:
            pct = float(getattr(c, "atomic_percent", 0) or 0)
            sym = str(getattr(c, "symbol", "") or "").strip()
        if pct > 0 and sym:
            out.append(sym)
    return out


def _param_get(params: Any, key: str, default: Any = None) -> Any:
    if isinstance(params, dict):
        return params.get(key, default)
    return getattr(params, key, default)


def _mode_value(params: Any) -> str:
    raw = _param_get(params, "mode", "cascade")
    return str(getattr(raw, "value", raw) or "cascade").strip().lower()


def required_species(material: Any, params: Any) -> list[str]:
    """Host composition plus mode-specific projectile / insert species."""
    hosts = host_symbols(material)
    mode = _mode_value(params)
    extra: list[str] = []
    if mode == "cascade":
        extra.append(str(_param_get(params, "pka_species") or (hosts[0] if hosts else "W")))
    elif mode in {"implant", "surface"}:
        extra.append(str(_param_get(params, "ion_type") or "He"))
    elif mode == "interstitial":
        extra.append(str(_param_get(params, "interstitial_species") or "He"))
    seen: set[str] = set()
    ordered: list[str] = []
    for sym in [*hosts, *extra]:
        if not sym:
            continue
        key = sym.lower()
        if key in seen:
            continue
        seen.add(key)
        ordered.append(sym)
    return ordered


def validate_potential_coverage(material: Any, potential: Any, params: Any) -> None:
    """Raise ValueError if potential cannot cover required species (placeholders exempt)."""
    if bool(getattr(potential, "is_placeholder", False)):
        return
    pot_elems = getattr(potential, "elements", None) or []
    pot = {str(e).lower() for e in pot_elems}
    need = required_species(material, params)
    missing = [s for s in need if s.lower() not in pot]
    if missing:
        covers = " ".join(str(e) for e in pot_elems) or "(none)"
        raise ValueError(
            f"Potential must cover species {', '.join(need)} "
            f"(missing {', '.join(missing)}); current covers {covers}"
        )


def validate_cascade_pka(material: Any, params: Any) -> None:
    """Cascade PKA must be a host lattice species (mass/type wiring)."""
    if _mode_value(params) != "cascade":
        return
    hosts = host_symbols(material)
    if not hosts:
        raise ValueError("Material composition is empty — cannot place a cascade PKA")
    pka = str(_param_get(params, "pka_species") or "").strip()
    if not pka:
        raise ValueError("Cascade mode requires pka_species")
    if pka.lower() not in {h.lower() for h in hosts}:
        raise ValueError(
            f"Cascade pka_species '{pka}' is not in the host composition ({', '.join(hosts)}). "
            "Pick a host atom type for the PKA kick."
        )
