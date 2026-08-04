---
name: aegis-lammps
description: LAMMPS cascade/implant conventions for Aegis — run parameters, dumps, templates under engines/lammps. Use when editing inputs, job runners, or parameter UI/API.
---

# Aegis LAMMPS

## Layout

- Templates: `engines/lammps/templates.py` (`write_cascade_input`, `write_implant_input`)
- Jobs: `apps/api/aegis_api/jobs.py` — spawn `AEGIS_LAMMPS_BIN` (default `lmp`)
- Params schema: `LammpsRunParams` in `packages/schema`

## Conventions

- Units: `metal`
- Persist `run_params.json` + `in.aegis` per job under `runs/<id>/`
- Wire UI params: ensemble/NVT damp, dump style, restart, multi-PKA delay, implant count/angle
- Write `dump.initial.lammpstrj` before damage; cascade/implant dumps for analysis
- Prefer cascade/implant dumps over initial for defect analysis
- If LAMMPS missing or placeholder potential: dry-run demo dump so analysis/UI still work

## Parameter groups

System (nx/ny/nz, boundary, seed), thermostat, PKA/cascade, implant, dynamics, output, analysis hooks (`ws_lattice_A`, `cluster_cutoff_A`).

## Rules

- Refuse real MD without a non-placeholder potential file.
- Large cells (>20³): require `confirm_large`.
- Do not invent pair_style / coefficients; use catalog or user upload.
- Non-BCC materials: warn — templates still build BCC in Phase-1.