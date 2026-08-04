---
name: aegis-kart
description: KART (k-ART) integration for Aegis — clone/build notes, path discovery, anneal adapter, Phase-2 handoff. Use when working on engines/kart or Engines UI status.
---

# Aegis KART

## Upstream

- Repo: https://gitlab.com/groupe_mousseau/kart (membership required)
- Docs: https://kart-doc.readthedocs.io/
- Recommended first-time pin: commit `62d66adf` (`AEGIS_KART_COMMIT`)

## Auth

Clone with **PAT or SSH only**. Never store passwords in the repo, `.env` committed files, or chat. Prefer gitignored `GITLAB_TOKEN`.

## Layout

- Clone to `third_party/kart/` (gitignored) or set `AEGIS_KART_ROOT`
- Binary via `AEGIS_KART_BIN` or discovery in adapter
- Adapter: `engines/kart/adapter.py` — `discover_kart`, `run_anneal_stub_or_real`
- Handoff builder: `engines/kart/handoff.py` — `aegis-kart-handoff-v2`

## Phase-2 behavior

| State | Behavior |
|---|---|
| Not cloned/built | Handoff package + stub event timeline |
| Binary found | Probe + handoff under `kart_work/T*/`; parse `Energy.dat` if present |
| DOE | `kart_anneal_temperatures` or `POST /api/jobs/{id}/kart/anneal` |

Handoff includes `initial.conf`, `conf.lammps`, `in.lammps`, `KMC.sh.aegis`, defect XYZ overlays.

Prefer WSL/Linux if native Windows builds fail.
