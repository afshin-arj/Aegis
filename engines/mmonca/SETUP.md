# MMonCa (optional object-KMC) — Phase-3 comparison path

Aegis Phase-2 primary KMC path is **KART (k-ART)**. [MMonCa](https://www.sciencedirect.com/science/article/pii/S0010465513004051) is an **optional** classical object-KMC engine for comparison studies (vacancy / SIA object evolution).

## What Aegis does

- Discovers `AEGIS_MMONCA_BIN` / `AEGIS_MMONCA_ROOT` / `third_party/mmonca`
- Writes `runs/<job>/mmonca_work/` handoff **v2**: clustered vacancy/SIA objects (positions, sizes) plus optional DXA loops
- Probes the binary when found; writes `run_mmonca.sh.aegis`
- Always tags the path `mmonca_compare` — never the default post-cascade anneal
- Stubs an object-evolution timeline in Results until a real OKMC trajectory is imported

## What Aegis does **not** do

- Does **not** vendor or redistribute MMonCa
- Does **not** claim calibrated continuum OKMC rates from the stub curve

## Setup (operator)

1. Obtain and build MMonCa per upstream documentation.
2. Set in gitignored `.env`:
   ```
   AEGIS_MMONCA_BIN=/path/to/mmonca
   ```
3. Enable **Queue MMonCa OKMC** on the LAMMPS tab after a cascade/surface job.

Prefer KART for off-lattice cascade annealing; use MMonCa only when you need object-KMC comparison.
