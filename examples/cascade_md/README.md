# Cascade MD examples

Two complete workbench recipes a new user can load and submit.

| Folder | What it is | Typical first result |
|--------|------------|----------------------|
| `01_w_self_pka_5kev` | ITER-like W, 5 keV self-ion, 8³, 600 K | Dry-run until a published W potential is attached |
| `02_fe_self_pka_10kev` | α-Fe, 10 keV self-ion, 10³, 300 K | Same; PKA is **Fe**, not the D–T preset’s W |

## As a user (UI)

1. Start Aegis (`setup_and_run.cmd` / `.sh`).
2. **Projects** → **Worked cascade examples** → **Load into Simulate**.
3. **Potential** — placeholders only emit synthetic dumps. Acquire/upload a cited EAM/FS (e.g. Zhou04 from NIST).
4. **Engines** — for `mpi_procs > 1` you need MS-MPI/`mpiexec` **and** an MPI-built `lmp`.
5. **Submit** (top bar) → **Run** log → **Results**.

Do not start on **Campaigns** until one cell finishes.

## As a user (files)

Each folder has `job.json`: metadata plus a `job` object matching `POST /api/jobs` (`JobCreate`).

```text
examples/cascade_md/<name>/job.json
```

`GET /api/examples` lists them for the UI.

## Checks these recipes exist to catch

- Scenario D–T defaults used to set `pka_species=W` even on Fe — submit then failed coverage/PKA checks.
- **Timestep** is labeled **fs**. LAMMPS metal units are **ps**. Typing `1` must become `timestep 0.001`, not a 1 ps (unstable) cascade.
- Placeholder potentials must not pretend to be production MD.

Validate locally:

```bash
python examples/cascade_md/validate_examples.py
```
