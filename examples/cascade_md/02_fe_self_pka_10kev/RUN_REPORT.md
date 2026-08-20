# Run report — α-Fe cascade demo

**Status:** completed on local serial LAMMPS GUI (Zhou04 Fe attached to `fe-eam-placeholder`).

## Recipe (job.json)

- Material: `fe-pure` (BCC, a = 2.866 Å)
- Cell: 12³ (~3456 atoms)
- PKA: **Fe** 1 keV (not W from D–T scenario defaults)
- T = 300 K, timestep = 1 fs → 0.001 ps, auto stages on
- mpi_procs = 1

## Failure we hit first (fixed)

A prior 10 keV / 8³ attempt exited LAMMPS with:

- `WARNING: ... density exceeded rhomax of EAM potential table`
- `ERROR: Lost atoms`

Fixes: demo energy/cell, finer growth timestep, `thermo_modify lost ignore`, and corrected WS interstitial counting.

## Panels exercised

Same full path as the W example; Fe is the regression case for **host PKA remapping** when Scenario = D–T.

## Observed Results (proxy WS)

V ≈ SIA after the analysis fix. High fractions still trigger a Results note about cell size / hot cascade — enlarge cell or lower E for residual studies.
