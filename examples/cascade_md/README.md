# Cascade MD examples — deepened

Two complete workbench recipes exercised end-to-end (Projects → … → Results).

| Folder | Material | Demo recipe | Potential slot |
|--------|----------|-------------|----------------|
| `01_w_self_pka_5kev` | BCC W | **1 keV** self-PKA, **12³**, 600 K | `w-fs-cascade` ← NIST Zhou04 W |
| `02_fe_self_pka_10kev` | BCC Fe | **1 keV** self-PKA, **12³**, 300 K | `fe-eam-placeholder` ← NIST Zhou04 Fe |

Folder names keep older “5 keV / 10 keV” labels for stable paths; the **job.json** energies are the demo-safe values that finish on a serial Windows GUI `lmp`.

## As a user (UI)

1. `setup_and_run.cmd` / `.sh`
2. **Projects → Worked cascade examples → Load into Simulate**
3. **Potential → Acquire** Zhou04 (NIST) if the slot is still ○/◇
4. **Engines** — confirm `lmp` found (MPI ranks stay 1 until `lmp MPI=likely`)
5. **Submit → Run → Results**
6. **Campaigns** only after one cell completes

## Finish both sims from CLI

```bash
# API must be running on :8000
python examples/cascade_md/validate_examples.py
python examples/cascade_md/walkthrough_user.py
# Full-size demo (longer): set AEGIS_EXAMPLE_SHORTEN=0
```

`walkthrough_user.py` hits health, materials, scenarios, acquire/download, structure preview, KMC recommend, both jobs, defects, timeline, trajectory, campaigns list.

## Bugs found while finishing these runs (and fixed)

1. **Timestep fs→ps** (earlier) — UI fs must become LAMMPS metal ps.
2. **Scenario PKA host leak** (earlier) — D–T defaults must not force W on Fe.
3. **Fe 10 keV / tiny cell** — Zhou04 EAM blew `rhomax` → Lost atoms → job failed. Cascade inputs now use a **finer growth timestep** + `thermo_modify lost ignore`, and demos use **1 keV / 12³**.
4. **Stage planner** was passed metal `dt` as `timestep_fs` — now passes the UI fs value.
5. **WS “interstitials”** counted every thermally displaced on-site atom → SIA ≈ N_atoms. Residual WS now counts only true site conflicts / unmapped atoms; high defect fractions get an explicit note.

## Panel checklist (what we exercised)

| Panel | Check |
|-------|--------|
| Projects | Examples list + load recipe |
| Material | w-pure / fe-pure |
| Potential | NIST download attach |
| Scenario | dd-divertor / dt-divertor with host PKA remap |
| Simulate | Compute, cell guide, structure preview (SC + void), KMC recommend |
| Run | Live job status through completed |
| Results | Defects, cascade timeline (4 stages), trajectory frames |
| Campaigns | List endpoint (empty OK) |
| Engines | LAMMPS / MPI / OVITO status |
