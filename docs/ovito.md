# OVITO DXA for Aegis

Aegis uses [OVITO’s Python API](https://docs.ovito.org/python/) for optional dislocation analysis (DXA). It never invents dislocation networks when OVITO is missing.

> Do **not** put an `engines/ovito/` Python package in this repo — that name shadows the real `ovito` PyPI module on `PYTHONPATH`.

## Easiest path (recommended)

`setup_and_run.cmd` / `scripts/bootstrap.ps1` **tries** `pip install -U ovito` into `.venv` on first run when the module is missing. Failure is a **soft warning** — Aegis still launches; DXA stays unavailable until install succeeds.

Skip the attempt with `AEGIS_INSTALL_OVITO=0`.

Manual install in the Aegis virtualenv:

```bash
.venv\Scripts\python.exe -m pip install -U ovito
```

Or click **Install OVITO (pip)** on the Engines tab.

DXA then runs **in-process** (`import ovito`) — no separate `ovitos` binary required.

Docs: https://docs.ovito.org/python/introduction/installation.html

## OVITO Pro / ovitos

If you have OVITO Pro installed:

1. Point `AEGIS_OVITO_BIN` at `ovitos.exe` (Windows) or `ovitos` (Linux/macOS), **or**
2. Put `ovitos` on your PATH.

Example `.env`:

```
AEGIS_OVITO_BIN=C:\Program Files\OVITO Pro\ovitos.exe
```

Aegis falls back to an `ovitos` subprocess when the Python module is unavailable.

## Using DXA in the UI

1. **Engines** — confirm OVITO shows *found* (mode `module`, `ovitos`, or both).
2. **LAMMPS** — optionally check *Run OVITO DXA after job*.
3. **Results** — **Run / refresh DXA**; inspect length / segments / density / cell volume chips.
4. **Download .ca** — open `dislocations.ca` in the OVITO desktop app to scrub the network.

Crystal mapping: `bcc→BCC`, `fcc→FCC`, `hcp→HCP`, `diamond→CubicDiamond`, `hex(WC)→HCP` (**approximate** — the Results panel warns; do not treat WC→HCP DXA as calibrated WC dislocation analysis).

## Conda

Prefer the OVITO channel (not conda-forge’s GUI-only package):

```bash
conda install --strict-channel-priority -c https://conda.ovito.org -c conda-forge ovito
```

## API

| Endpoint | Purpose |
|----------|---------|
| `GET /api/engines/ovito` | Discovery + install hints |
| `POST /api/engines/ovito/install` | `pip install -U ovito` into the API interpreter |
| `GET /api/jobs/{id}/dxa?refresh=true` | Run / refresh DXA |
| `GET /api/jobs/{id}/dxa/ca` | Download Crystal Analysis file |
