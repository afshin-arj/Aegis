# Aegis ↔ KART (k-ART) adapter

KART implements the kinetic Activation-Relaxation Technique (off-lattice KMC).

## Setup

1. Clone (membership required) with PAT or SSH — never commit tokens:

```bash
git clone git@gitlab.com:groupe_mousseau/kart.git third_party/kart
# or: git clone https://oauth2:$GITLAB_TOKEN@gitlab.com/groupe_mousseau/kart.git third_party/kart
cd third_party/kart
git checkout 62d66adf
```

2. Build following https://kart-doc.readthedocs.io/en/latest/
3. Set `AEGIS_KART_ROOT` and optionally `AEGIS_KART_BIN`

## Adapter

`adapter.py` discovers binaries and can launch a placeholder anneal command when present.
Full cascade→KART handoff is Phase-2 depth work; Phase-1 reports status and runs a dry-run anneal stub if the binary is missing.
