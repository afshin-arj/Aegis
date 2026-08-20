# Run report — W cascade demo

**Status:** completed on local serial LAMMPS GUI (Zhou04 W via `w-fs-cascade`).

## Recipe (job.json)

- Material: `w-pure` (BCC, a = 3.165 Å)
- Cell: 12³ (~3456 atoms)
- PKA: 1 keV W (center); walkthrough shorten may use 0.5 keV
- T = 600 K, timestep = 1 fs → 0.001 ps, auto stages on
- mpi_procs = 1

## Panels exercised

Projects → Material → Potential (NIST Zhou04) → Scenario → Simulate → Run → Results → Engines.

## Observed Results (proxy WS)

After the WS counting fix, vacancy and SIA counts match (Frenkel-pair conservation). Absolute numbers stay elevated vs literature for this small cell — treat as a **workflow check**, not a published residual-damage yield. Prefer OVITO DXA + larger cells for science.

## Notes

- Apply recommended cell (~28³ at 1 keV) before production energies.
- Cascade log should include `thermo_modify lost ignore` and stage start/end markers.
