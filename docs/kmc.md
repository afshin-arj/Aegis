# Post-cascade kMC in Aegis

Aegis follows a **three-tier kinetic ladder** (Adjanor et al., *EPJ Nuclear Sci. Technol.* 2025) plus an ML rigid-lattice path for concentrated solid solutions (Huang et al., *J. Alloys Compd.* 2023).

| Tier | Method | Simulated window | Aegis status |
|------|--------|------------------|--------------|
| 1 | k-ART + hTST (off-lattice) | post-cascade anneal (ns–µs class) | **Wired** (`engines/kart`) |
| 2 | First-passage / kPS | trapping / rare escapes | Phase H (planned) |
| 3 | Stochastic cluster dynamics | reactor lifetimes | Phase G (planned) |
| E | ML-KMC (ANN-LAC + composition ν) | CSA sluggish diffusion | **Wired** (`engines/ml_kmc`, heuristic unless user ONNX) |
| — | MMonCa OKMC | comparison / object KMC | **Handoff v2** (clustered objects + binary probe; always `mmonca_compare`) |

## Honesty rules

- Every anneal summary carries **`aegis-kmc-provenance-v1`** (`tier`, `synthetic`, `prefactor_model`, `trapping_risk`, `validation_status`, warnings).
- Constant Γ₀ = 10¹³ s⁻¹ is **not** assumed adequate for concentrated alloys — handoff sets `prefactor_mode=htst` when ≥2 species exceed 5 at%.
- MMonCa paths are **comparison / engineering**, never silently presented as validated cascade anneals.
- Long target times (`≥ 1e6 s`) route to `stochastic_cd` with an explicit “not yet implemented” warning.

## Router

`POST /api/kmc/recommend` and job creation call `engines/kmc/router.py`:

- Inputs: material composition, anneal T / max KMC time, KART/MMonCa flags, structure kind, optional defect counts.
- Outputs: `recommended_tier`, warnings, `prefactor_model_hint`, `trapping_risk_hint`.
- Optional `JobCreate.kmc_tier` overrides the recommendation (note recorded in provenance).

## k-ART handoff v3 / summary v4

Under `runs/<job_id>/kart_work/T*/` (and `T*_constant` / `T*_htst` in prefactor-compare mode):

```text
initial.conf · conf.lammps · in.lammps · KMC.sh.aegis · handoff.json
```

`handoff.json` format **`aegis-kart-handoff-v3`** includes:

- `prefactor_mode`: `htst` | `constant`
- `MIN_EVENT_SEARCHES=25` and optional `USE_HTST_PREFACTOR=.true.` in `KMC.sh.aegis`
- Trapping diagnostics from `Energy.dat` (`analyze_trapping` → flicker ratio / risk)
- Optional per-event `prefactor_Hz` / `rate_Hz` when Energy.dat columns allow

Summaries use **`aegis-kart-summary-v4`** (adds `kinetics`, optional `prefactor_compare_results`).

## UI

LAMMPS **Params** tab → **Post-cascade kMC** panel shows the live router recommendation and optional
**Prefactor compare** checkbox. Results and the recipe aside show job-level `kmc_provenance`,
kinetics chips, and constant-vs-hTST deltas when compare mode ran.

## Phase roadmap (approved order)

1. **D** — schema, router, provenance, KART v3 flags, UI — shipped
2. **F** — hTST alignment, richer Energy.dat, prefactor compare — shipped
3. **E** — ML-KMC (ANN-LAC / rigid lattice) — shipped
4. **I** — richer MMonCa handoff — this slice
5. **G** — stochastic cluster dynamics
6. **H** — first-passage kPS

See also: [engines/kart/SETUP.md](../engines/kart/SETUP.md), [engines/ml_kmc/SETUP.md](../engines/ml_kmc/SETUP.md).
