# Aegis remote HPC packs (Phase-4)

Aegis remains a **local workbench**. For DEMO-scale cells or long cascades, export a portable pack and submit on your cluster.

## Per-job export

```http
POST /api/jobs/{job_id}/hpc-export
{ "scheduler": "slurm", "cores": 16, "walltime": "08:00:00", "lammps_bin": "lmp" }
```

Creates `runs/<job>/hpc_pack/` plus a zip containing:

- `in.aegis`, `material.json`, `potential.json`, `run_params.json`
- Copied potential file (when present)
- `submit.slurm` or `submit.pbs`
- `README_HPC.md`

## Campaign export

After a DOE campaign has prepared inputs (local runs that reached prepare, or `run_locally: false` export-only campaigns):

```http
POST /api/campaigns/{campaign_id}/hpc-export
```

Bundles each case into one zip plus `submit_all.sh` (Slurm `sbatch` / PBS `qsub` loop).

## Guardrails

- Never commit cluster accounts, tokens, or SSH keys into the Aegis repo.
- Review `pair_coeff` paths on the cluster before submission.
- Copy dumps/logs back under `runs/<job_id>/` to use Results / structure viz locally.
