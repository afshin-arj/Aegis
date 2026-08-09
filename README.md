# Aegis

**Local workbench for microscopic radiation damage in tokamak plasma-facing materials (PFMs).**

Select material and composition → attach a published interatomic potential → apply D–D / D–T irradiation presets → run LAMMPS cascade or He implantation → inspect defects → optionally anneal with k-ART.

![Aegis — radiation damage MD for PFMs](docs/assets/aegis-banner.png)

> **Scale honesty:** Aegis runs **cascade / implant MD** and optional **KMC annealing**. Fuel choices (D–D / D–T) are **irradiation scenario presets** (energies, temperature, labels)—not plasma transport or neutronics.

---

## Workflow

![Aegis simulation workflow](docs/assets/aegis-workflow.png)

| Step | What you do | What Aegis produces |
|------|-------------|---------------------|
| 1 | Choose or name a project; browse prior jobs | Job history under `runs/` |
| 2 | Optional: DEMO DOE sweep (energy × T, …) | Campaign summary + serial local jobs or HPC zip |
| 3 | Choose PFM preset; edit composition (at%/wt%) | `material.json` |
| 4 | Pick curated or uploaded potential | Validated `pair_style` / file path |
| 5 | Select D–D / D–T / He / surface scenario; override fields | `run_params.json` |
| 6 | Queue LAMMPS job (or export Slurm/PBS pack) | Live log, dumps, or remote `submit.slurm` |
| 7 | Review structure + defects; optional k-ART / OKMC | Trajectory frames, vacancy / SIA proxy, clusters |

---

## Quick start (Windows)

```bat
setup_and_run.cmd
```

Installs only what is missing (Python, Node, Git, API/UI deps, **LAMMPS Windows**, KART **clone**), then opens the UI at [http://127.0.0.1:5173](http://127.0.0.1:5173).

| Already installed? | Behavior |
|--------------------|----------|
| `python` / `node` / `git` on PATH | Skipped |
| `lmp.exe` found | Skipped |
| `third_party/kart` + binary | Skipped |

**KART:** private GitLab project. Put `GITLAB_TOKEN` in a gitignored `.env` (or use SSH). Full obtain/build guide: [`engines/kart/SETUP.md`](engines/kart/SETUP.md). On Windows, build in **WSL** or **Docker**—native MSVC is unsupported.

---

## Manual start

```bash
# API
cd apps/api
python -m venv ../../.venv
../../.venv/Scripts/activate   # Windows
pip install -r requirements.txt -e ../../packages/schema
uvicorn aegis_api.main:app --reload --port 8000

# UI (second terminal)
cd apps/web
npm install
npm run dev
```

---

## Stack

| Layer | Technology |
|-------|------------|
| UI | React + Vite — expert console for nuclear materials workflows |
| API | FastAPI job orchestrator + WebSocket logs |
| MD | LAMMPS (out-of-process) |
| Potentials | Local catalog + NIST IPR download (allowlisted) / manual upload |
| KMC | KART / k-ART (optional; stubs if binary missing) |
| Data | JSON materials, scenarios, potential catalog |

---

## Environment

Copy `.env.example` → `.env` (never commit secrets).

| Variable | Purpose |
|----------|---------|
| `AEGIS_LAMMPS_BIN` | Path to `lmp` / `lmp.exe` |
| `AEGIS_OVITO_BIN` | Optional path to OVITO Pro `ovitos` (bootstrap also tries `pip install -U ovito`) |
| `AEGIS_INSTALL_OVITO` | Set `0` to skip first-run OVITO pip (default: attempt; soft-fail) |
| `AEGIS_ATOMSK_BIN` | Optional Atomsk binary for polycrystal / GB builds (ASE Voronoi fallback) |
| `AEGIS_INSTALL_ASE` / `AEGIS_INSTALL_ATOMSK` | Set `0` to skip ASE / Atomsk bootstrap steps |
| `AEGIS_KART_ROOT` / `AEGIS_KART_BIN` | KART clone / binary |
| `AEGIS_KART_COMMIT` | Pin (default `62d66adf`) |
| `GITLAB_TOKEN` | Clone KART only (local `.env`) |

---

## Repository layout

```
setup_and_run.cmd     Windows bootstrap + UI
scripts/bootstrap.ps1
apps/web/             React workbench
apps/api/             FastAPI
packages/schema/      Shared schemas
engines/lammps/       Input templates
engines/kart/         Adapter + SETUP.md
data/                 Materials, scenarios, potentials
docs/assets/          README figures
third_party/kart/     Local KART clone (gitignored)
runs/                 Job artifacts (gitignored)
```

---

## Engineering notes

- **Potentials:** Aegis never invents coefficients. Upload a published file or place one under `data/potentials/curated/`. The bundled placeholder is for pipeline wiring only—real MD requires a valid EAM/FS/MEAM file.
- **Defect analysis:** Phase-1 Wigner–Seitz-style proxy for engineering inspection—not a replacement for OVITO production analysis. Enable DXA from the LAMMPS tab or Results. `setup_and_run` tries `pip install -U ovito` on first run (soft-fail); see [docs/ovito.md](docs/ovito.md).
- **Nanostructures:** LAMMPS tab → Structure (`polycrystal`, `bicrystal`, `void`, `void_lattice`, `polycrystal_void`, `import`) builds `structure.data` via ASE (Atomsk optional) and loads it with `read_data` — see [docs/structures.md](docs/structures.md).
- **Large cells:** runs with &gt;20³ unit cells require explicit confirmation.

---

## First tutorial: W cascade (then He)

1. Run `setup_and_run.cmd` and open the UI.
2. **Projects** — name the study (e.g. `W-cascade-demo`).
3. **Material** — preset *Tungsten (pure)*; optionally toggle wt%/at%.
4. **Potential** — for a real run, upload a published W EAM/FS file (NIST potentials). The demo placeholder only exercises dry-run dumps.
5. **Scenario** — start with *D–T divertor-like defaults*, or switch to *D–D* / *He implantation* / *Low-E He|D surface*.
6. **LAMMPS** — keep a small cell (≤10³) for the first job; confirm if you go larger. Surface mode uses vacuum + free `z` boundary.
7. **Run** — start the job; watch the live log. Without LAMMPS or with the placeholder, Aegis writes demo dumps so Results still work.
8. **Results** — scrub before/after structure frames; inspect vacancy/SIA proxy, surface/fuzz chips (surface mode), and clusters.
9. Optional: enable **Queue KART anneal** and/or **MMonCa OKMC**. Engines explains missing binaries; anneals stub honestly.

For **W–He**, upload a W–He potential, pick the *He implantation* or *Low-E He surface* scenario, and ensure the potential’s element list includes `W` and `He`.

---

## License & citation

MIT for Aegis application code. LAMMPS is GPL; KART has upstream terms. Cite the interatomic potential and engine versions in publications.
