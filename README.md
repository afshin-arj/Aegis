# Aegis

**Aegis** is a local simulation workbench for microscopic radiation damage in tokamak plasma-facing materials (PFMs).

Configure material + composition → choose an interatomic potential → set D–D / D–T scenario and LAMMPS parameters → run cascade / implantation jobs → inspect defects → optionally anneal with **k-ART (KART)**.

> Scale honesty: Aegis runs **cascade MD** and **KMC annealing**, not a full tokamak plasma transport code. Fuel choices (D–D / D–T) set irradiation **scenario presets**.

## Stack

| Layer | Tech |
|---|---|
| UI | React + Vite (`apps/web`) |
| API | FastAPI (`apps/api`) |
| Engines | LAMMPS (out-of-process), KART / k-ART (optional) |
| Data | JSON materials, scenarios, potential catalog |

## Quick start

### Prerequisites

- Python 3.11+
- Node.js 20+
- [LAMMPS](https://www.lammps.org/) `lmp` on `PATH` (or set `AEGIS_LAMMPS_BIN`)
- Optional: [KART](https://gitlab.com/groupe_mousseau/kart) (GitLab membership required)

### API

```bash
cd apps/api
python -m venv .venv
# Windows:
.venv\Scripts\activate
pip install -r requirements.txt
uvicorn aegis_api.main:app --reload --port 8000
```

### Web UI

```bash
cd apps/web
npm install
npm run dev
```

Open http://localhost:5173 (proxies `/api` to the FastAPI server).

### Environment

Copy `.env.example` to `.env` (gitignored). Never commit tokens or passwords.

| Variable | Meaning |
|---|---|
| `AEGIS_LAMMPS_BIN` | Path to LAMMPS executable |
| `AEGIS_KART_ROOT` | Path to local KART clone |
| `AEGIS_KART_BIN` | Path to KART binary if not default |
| `GITLAB_TOKEN` | Optional; only for cloning KART locally — never commit |

## KART (k-ART)

1. Ensure GitLab access to `groupe_mousseau/kart`.
2. Clone with SSH or a Personal Access Token (not a password in the URL):

```bash
git clone https://oauth2:${GITLAB_TOKEN}@gitlab.com/groupe_mousseau/kart.git third_party/kart
cd third_party/kart
git checkout 62d66adf   # docs-recommended first-time pin
```

3. Build per [kart-doc](https://kart-doc.readthedocs.io/en/latest/).
4. Set `AEGIS_KART_ROOT` / `AEGIS_KART_BIN`. The Engines page reports status; anneal degrades gracefully if missing.

Do **not** commit the KART tree into this public repo unless upstream terms allow redistribution.

## Repository layout

```
apps/web/          React workbench
apps/api/          FastAPI orchestrator
packages/schema/   Shared Pydantic / JSON schemas
engines/lammps/    Input templates + launcher
engines/kart/      Adapter + status discovery
data/materials/    PFM presets
data/scenarios/    D-D / D-T presets
data/potentials/   Catalog + curated metadata (user uploads gitignored)
runs/              Job artifacts (gitignored)
.cursor/skills/    Agent skills for Aegis development
.cursor/rules/     Sim-engineer agent rule
```

## Cursor skills

Project skills under `.cursor/skills/`: `aegis-domain`, `aegis-lammps`, `aegis-materials`, `aegis-potentials`, `aegis-kart`, `aegis-ui`. Rule: `.cursor/rules/aegis-sim-engineer.mdc`.

## License

MIT for Aegis application code. LAMMPS is GPL; KART has its own upstream terms. Potential files retain their original licenses/citations.

## Citation context

Designed for research workflows informed by fusion PFM literature (W / He damage, divertor loads). Always cite the interatomic potential and any KART/LAMMPS versions you use in publications.
