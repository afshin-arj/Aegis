"""Absorbing-chain MFPT sampler for trap-limited kMC (Phase H spike)."""

from __future__ import annotations

import math
from typing import Any

from kart.handoff import analyze_trapping


def detect_basins(events: list[dict[str, Any]], *, flicker_barrier_eV: float = 0.15) -> dict[str, Any]:
    trap = analyze_trapping(events, flicker_barrier_eV=flicker_barrier_eV)
    runs: list[int] = []
    run = 0
    for e in events:
        if float(e.get("barrier_eV") or 0) < flicker_barrier_eV:
            run += 1
        elif run:
            runs.append(run)
            run = 0
    if run:
        runs.append(run)
    return {
        **trap,
        "flicker_run_lengths": runs[:40],
        "n_basins": len(runs),
        "max_run": max(runs) if runs else 0,
    }


def mfpt_two_state(
    *,
    k_flicker_hz: float,
    k_escape_hz: float,
) -> dict[str, Any]:
    """Two-state trap: states {flicker, absorb/escape}.

    MFPT from flicker to escape is 1/k_escape when flicker is a self-loop
    (standard absorbing-chain result for a single transient state).
    """
    ke = max(float(k_escape_hz), 1e-30)
    kf = max(float(k_flicker_hz), 0.0)
    p_stay = kf / (kf + ke) if (kf + ke) > 0 else 1.0
    mfpt_s = 1.0 / ke
    return {
        "mfpt_s": mfpt_s,
        "p_remain_flicker": p_stay,
        "k_flicker_Hz": kf,
        "k_escape_Hz": ke,
        "method": "absorbing_chain_2state",
    }


def first_passage_from_events(
    events: list[dict[str, Any]],
    *,
    temperature_K: float = 600.0,
    flicker_barrier_eV: float = 0.15,
    escape_barrier_eV: float = 0.7,
    nu_hz: float = 1e13,
) -> dict[str, Any]:
    kB = 8.617333262145e-5
    kT = max(temperature_K, 1.0) * kB
    basins = detect_basins(events, flicker_barrier_eV=flicker_barrier_eV)
    k_f = nu_hz * math.exp(-flicker_barrier_eV / kT)
    k_e = nu_hz * math.exp(-escape_barrier_eV / kT)
    mfpt = mfpt_two_state(k_flicker_hz=k_f, k_escape_hz=k_e)
    return {
        "format": "aegis-first-passage-v1",
        "basins": basins,
        "mfpt": mfpt,
        "note": "Spike: 2-state absorbing chain. Full kPS matrix factorization not implemented.",
    }
