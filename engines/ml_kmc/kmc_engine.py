"""Rigid-lattice vacancy KMC on FCC (residence-time, Einstein D)."""

from __future__ import annotations

import math
import random
from typing import Any

from ml_kmc.barrier_model import BarrierModel
from ml_kmc.lac import FCC_SHELLS, default_species_codes, extract_lac
from ml_kmc.nu_model import attempt_frequency
from ml_kmc.sro import warren_cowley

kB = 8.617333262145e-5
FCC_NN = FCC_SHELLS[0]  # 12 jumps


def build_random_fcc(
    *,
    nx: int,
    ny: int,
    nz: int,
    composition: list[dict[str, Any]],
    rng: random.Random,
) -> tuple[dict[tuple[int, int, int], int], dict[str, int], float]:
    """Occupy conventional FCC sites (4 per cubic cell) with random alloy + 1 vacancy."""
    codes = default_species_codes([str(c.get("symbol") or "") for c in composition])
    weights: list[tuple[int, float]] = []
    for row in composition:
        sym = str(row.get("symbol") or "")
        pct = float(row.get("atomic_percent") or 0)
        if sym and pct > 0 and codes.get(sym, 0) > 0:
            weights.append((codes[sym], pct))
    if not weights:
        weights = [(1, 100.0)]
    total = sum(w for _, w in weights)
    occ: dict[tuple[int, int, int], int] = {}
    # Conventional FCC: (0,0,0) and face centers in even-parity lattice units
    sites: list[tuple[int, int, int]] = []
    for i in range(nx):
        for j in range(ny):
            for k in range(nz):
                if (i + j + k) % 2 == 0:
                    sites.append((i, j, k))
    if not sites:
        sites = [(0, 0, 0)]
    vac = sites[rng.randrange(len(sites))]
    x_solute = 0.0
    fe_code = codes.get("Fe")
    for s in sites:
        if s == vac:
            occ[s] = 0
            continue
        r = rng.random() * total
        acc = 0.0
        chosen = weights[0][0]
        for code, w in weights:
            acc += w
            if r <= acc:
                chosen = code
                break
        occ[s] = chosen
        if fe_code and chosen == fe_code:
            x_solute += 1.0
    n_occ = max(1, len(sites) - 1)
    return occ, codes, x_solute / n_occ


def run_rigid_kmc(
    *,
    composition: list[dict[str, Any]],
    temperature_K: float,
    n_steps: int,
    nx: int = 8,
    ny: int = 8,
    nz: int = 8,
    lattice_A: float = 3.52,
    structure_class: str = "random",
    nu_model: str = "composition_polynomial",
    barrier: BarrierModel,
    seed: int = 1,
) -> dict[str, Any]:
    rng = random.Random(int(seed))
    occ, codes, x_fe = build_random_fcc(
        nx=nx, ny=ny, nz=nz, composition=composition, rng=rng
    )
    vac = next(k for k, v in occ.items() if v == 0)
    nu_info = attempt_frequency(
        temperature_K=temperature_K,
        x_solute=x_fe,
        model="composition_polynomial" if nu_model == "composition_polynomial" else "constant",
    )
    nu = float(nu_info["nu_Hz"])
    kT = max(temperature_K, 1.0) * kB
    t = 0.0
    msd = 0.0
    events: list[dict[str, Any]] = []
    vac_disp = [0, 0, 0]
    for step in range(1, max(1, int(n_steps)) + 1):
        lac = extract_lac(occ, vac, nx=nx, ny=ny, nz=nz)
        rates: list[tuple[tuple[int, int, int], float, float]] = []
        for jump in FCC_NN:
            dest = ((vac[0] + jump[0]) % nx, (vac[1] + jump[1]) % ny, (vac[2] + jump[2]) % nz)
            if occ.get(dest, 0) == 0:
                continue
            ea = barrier.predict_barrier(lac, jump)
            rate = nu * math.exp(-min(ea / kT, 80.0))
            rates.append((jump, ea, rate))
        total_rate = sum(r for _, _, r in rates)
        if total_rate <= 0:
            break
        dt = -math.log(max(rng.random(), 1e-16)) / total_rate
        t += dt
        pick = rng.random() * total_rate
        acc = 0.0
        chosen = rates[0]
        for item in rates:
            acc += item[2]
            if pick <= acc:
                chosen = item
                break
        jump, ea, rate = chosen
        dest = ((vac[0] + jump[0]) % nx, (vac[1] + jump[1]) % ny, (vac[2] + jump[2]) % nz)
        occ[vac] = occ[dest]
        occ[dest] = 0
        vac = dest
        vac_disp[0] += jump[0]
        vac_disp[1] += jump[1]
        vac_disp[2] += jump[2]
        hop_A = (lattice_A / 2.0) * math.sqrt(2.0)  # FCC 1NN
        msd += hop_A * hop_A
        if step <= 40 or step == n_steps:
            events.append(
                {
                    "event": step,
                    "barrier_eV": round(ea, 5),
                    "rate_Hz": rate,
                    "time_s": t,
                    "dt_s": dt,
                    "source": "ml_kmc",
                }
            )
    # Einstein: D = <R²> / (6 t) for 3D vacancy tracer (Å²/s)
    d_a2_s = (msd / (6.0 * t)) if t > 0 else 0.0
    sro = warren_cowley(
        occ,
        nx=nx,
        ny=ny,
        nz=nz,
        code_a=codes.get("Ni", 1),
        code_b=codes.get("Fe", 2),
    )
    return {
        "n_steps": n_steps,
        "simulated_time_s": t,
        "einstein_D_A2_s": d_a2_s,
        "x_solute": x_fe,
        "nu": nu_info,
        "sro": sro,
        "structure_class": structure_class,
        "events": events,
        "species_codes": codes,
        "box": {"nx": nx, "ny": ny, "nz": nz, "lattice_A": lattice_A},
        "vacancy_disp_lu": vac_disp,
    }
