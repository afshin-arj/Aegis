---
name: aegis-kart
description: KART (k-ART) integration for Aegis — clone/build notes, path discovery, anneal adapter. Use when working on engines/kart or Engines UI status.
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

## Behavior

| State | UI / anneal |
|---|---|
| Not cloned/built | Banner + stub anneal curve |
| Binary found | Probe/invoke; full cascade handoff is Phase-2 |

Prefer WSL/Linux if native Windows builds fail.
