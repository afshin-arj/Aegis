---
name: aegis-lammps
description: LAMMPS cascade/implant conventions for Aegis — run parameters, dumps, templates under engines/lammps. Use when editing inputs, job runners, or parameter UI/API.
---

# Aegis LAMMPS

## Layout

- Crystal registry: `engines/lammps/crystal.py` (bcc/fcc/hcp/diamond/hex)
- Structure builders: `engines/lammps/structure/` (ASE / Atomsk / import → `structure.data`)
- Legacy polycrystal seed helper: `engines/lammps/polycrystal.py` (not the MD path)
- Templates: `engines/lammps/templates.py` (`read_data` when structure file present)
- Jobs: `apps/api/aegis_api/jobs.py` — spawn `AEGIS_LAMMPS_BIN` (default `lmp`)
- Params schema: `LammpsRunParams` in `packages/schema`
- DXA: `apps/api/aegis_api/dxa.py` · lattice relax: `lattice_relax.py`

## Conventions

- Units: `metal`
- Lattice command comes from `crystal.lattice_line(material, params)` — never hardcode BCC
- Persist `run_params.json` + `in.aegis` per job under `runs/<id>/`
- Write `dump.initial.lammpstrj` before damage; cascade/implant dumps for analysis
- Prefer cascade/implant dumps over initial/stage bookmarks for defect analysis
- If LAMMPS missing, placeholder potential, or unsupported crystal: dry-run demo dump
- WS analysis: `aegis-ws-proxy-v2` with crystal + optional sublattice (WC)

## Parameter groups

System (nx/ny/nz, boundary, seed, crystal_orient, structure_kind/poly_*), thermostat, PKA/cascade, implant, interstitial, dynamics, output, analysis hooks, `run_dxa`.

## Rules

- Refuse real MD without a non-placeholder potential file.
- Large cells (>20³): require `confirm_large`.
- Do not invent pair_style / coefficients; use catalog or user upload.
- Crystal-aware interstitial geometries from the registry.
