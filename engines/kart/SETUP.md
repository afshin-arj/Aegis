# KART setup for Aegis

Aegis uses [KART](https://gitlab.com/groupe_mousseau/kart) (k-ART) as an optional post-cascade anneal engine.

## Clone (membership required)

Use SSH or a Personal Access Token. **Never** put a password in the clone URL or commit tokens.

```bash
# from repo root
git clone git@gitlab.com:groupe_mousseau/kart.git third_party/kart
# or: git clone https://oauth2:${GITLAB_TOKEN}@gitlab.com/groupe_mousseau/kart.git third_party/kart

cd third_party/kart
git checkout 62d66adf
```

`third_party/kart/` is gitignored.

## Build

Follow [kart-doc](https://kart-doc.readthedocs.io/en/latest/). On Windows, prefer WSL/Linux if the native build is painful.

## Wire into Aegis

| Variable | Purpose |
|---|---|
| `AEGIS_KART_ROOT` | Path to clone (default `third_party/kart`) |
| `AEGIS_KART_BIN` | Explicit binary path |
| `AEGIS_KART_COMMIT` | Expected pin (default `62d66adf`) |

The Engines page and `engines/kart/adapter.py` report discovery. If the binary is missing, anneal **stubs** with an honest status message.
