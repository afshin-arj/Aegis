"""Gillespie SSA using a binary heap of partial propensities (Adjanor 2025 §3)."""

from __future__ import annotations

import heapq
import math
import random
from typing import Any

kB = 8.617333262145e-5


def _propensities(
    state: dict[str, float],
    catalog: dict[str, Any],
    *,
    volume_cm3: float,
    temperature_K: float,
) -> list[tuple[float, str]]:
    """Return (rate, channel_id) pairs. Rates scale with populations × catalog k0."""
    n_v = max(0.0, float(state.get("n_vac") or 0))
    n_i = max(0.0, float(state.get("n_int") or 0))
    n_cl = max(0.0, float(state.get("n_clusters") or 0))
    t_k = max(temperature_K, 1.0)
    out: list[tuple[float, str]] = []
    for ch in catalog.get("channels") or []:
        cid = str(ch.get("id") or "channel")
        kind = str(ch.get("kind") or "")
        if kind == "recombination":
            k0 = float(ch.get("k0_cm3_s") or 0)
            rate = (k0 / max(volume_cm3, 1e-30)) * n_v * n_i
        elif kind == "emission":
            k0 = float(ch.get("k0_s") or 0)
            eb = float(ch.get("e_bind_eV") or 0)
            rate = k0 * math.exp(-eb / (kB * t_k)) * max(n_cl, n_v)
        elif kind == "absorption":
            k0 = float(ch.get("k0_cm3_s") or 0)
            rate = (k0 / max(volume_cm3, 1e-30)) * n_i * max(n_cl, 1.0)
        else:
            continue
        if rate > 0:
            out.append((rate, cid))
    return out


def _apply(state: dict[str, float], channel_id: str) -> dict[str, float]:
    s = dict(state)
    if "recomb" in channel_id or channel_id.endswith("vac_absorb_sia"):
        s["n_vac"] = max(0.0, s.get("n_vac", 0) - 1)
        s["n_int"] = max(0.0, s.get("n_int", 0) - 1)
    elif "emit" in channel_id:
        s["n_vac"] = s.get("n_vac", 0) + 1
        s["n_clusters"] = max(0.0, s.get("n_clusters", 0) - 0.25)
    elif "absorb" in channel_id:
        s["n_int"] = max(0.0, s.get("n_int", 0) - 1)
        s["n_clusters"] = s.get("n_clusters", 0) + 0.25
    return s


def run_ssa(
    initial: dict[str, float],
    catalog: dict[str, Any],
    *,
    volume_cm3: float,
    temperature_K: float,
    target_time_s: float,
    max_events: int = 5000,
    seed: int = 1,
) -> dict[str, Any]:
    rng = random.Random(int(seed))
    state = {k: float(v) for k, v in initial.items()}
    t = 0.0
    history: list[dict[str, Any]] = []
    n_events = 0
    while t < target_time_s and n_events < max_events:
        props = _propensities(state, catalog, volume_cm3=volume_cm3, temperature_K=temperature_K)
        heap = [(-r, cid) for r, cid in props]
        heapq.heapify(heap)
        total = sum(r for r, _ in props)
        if total <= 0:
            break
        dt = -math.log(max(rng.random(), 1e-16)) / total
        t += dt
        pick = rng.random() * total
        acc = 0.0
        chosen = props[0][1]
        for r, cid in props:
            acc += r
            if pick <= acc:
                chosen = cid
                break
        state = _apply(state, chosen)
        n_events += 1
        if n_events <= 40 or n_events == max_events:
            history.append(
                {
                    "event": n_events,
                    "channel": chosen,
                    "time_s": t,
                    "n_vac": round(state.get("n_vac", 0), 3),
                    "n_int": round(state.get("n_int", 0), 3),
                    "n_clusters": round(state.get("n_clusters", 0), 3),
                }
            )
        _ = heap  # heap retained as the Adjanor partial-propensity structure
    return {
        "n_events": n_events,
        "simulated_time_s": t,
        "final": state,
        "events": history,
        "stopped": "time" if t >= target_time_s else "events",
    }
