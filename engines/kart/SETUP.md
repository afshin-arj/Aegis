# KART (k-ART) — obtain, install, and wire into Aegis

Aegis uses [KART](https://gitlab.com/groupe_mousseau/kart) for optional post-cascade **k-ART** annealing. KART is a **private GitLab** project: you need [groupe_mousseau/kart](https://gitlab.com/groupe_mousseau/kart) membership.

Docs: [kart-doc.readthedocs.io](https://kart-doc.readthedocs.io/en/latest/)

---

## What Aegis does **not** do

- Does **not** commit KART source into the public Aegis GitHub repo (license / access).
- Does **not** store GitLab passwords. Use **SSH** or a **Personal Access Token** only.
- If the binary is missing, anneal **stubs** with an honest status in the Engines / Results UI.

---

## Recommended pin

| Setting | Value |
|---|---|
| Commit | `62d66adf` (docs-recommended first-time / self-contained ARTn) |
| Env | `AEGIS_KART_COMMIT` (default `62d66adf`) |
| Local path | `third_party/kart/` (gitignored) |

Newer `master` may integrate LAMMPS + artn-plugin (pART). Prefer the pinned commit until Phase-2.

---

## Procedure A — automatic (`setup_and_run.cmd`)

From the Aegis repo root on Windows:

1. Optional: create `.env` (gitignored) with:
   ```
   GITLAB_TOKEN=glpat_...
   ```
   Token needs `read_repository` on `groupe_mousseau/kart`. Prefer SSH if you already use GitLab SSH keys (omit the token).
2. Double-click or run:
   ```bat
   setup_and_run.cmd
   ```
3. The bootstrap script will:
   - **Skip** if `third_party/kart` exists **and** a KART binary is already discoverable
   - Otherwise **clone** (SSH or token URL) and `git checkout 62d66adf`
   - Attempt a **WSL build** if `wsl` is available
   - Write local paths to `tools/aegis_env.ps1`
4. UI launches only after this step (and LAMMPS / deps).

---

## Procedure B — manual clone (any OS)

### B1. SSH (preferred)

```bash
cd /path/to/Aegis
git clone git@gitlab.com:groupe_mousseau/kart.git third_party/kart
cd third_party/kart
git checkout 62d66adf
```

### B2. HTTPS + Personal Access Token

```bash
# never put the token in chat, commits, or screenshots
export GITLAB_TOKEN=glpat_...   # Windows PowerShell: $env:GITLAB_TOKEN="..."
git clone "https://oauth2:${GITLAB_TOKEN}@gitlab.com/groupe_mousseau/kart.git" third_party/kart
cd third_party/kart
git checkout 62d66adf
```

### B3. Build

Follow [kart-doc](https://kart-doc.readthedocs.io/en/latest/). On **Windows**, use **WSL / Linux** if native MSVC builds fail.

Example WSL sketch (adjust to upstream docs):

```bash
cd /mnt/f/AI-Projects/RadDam/third_party/kart   # your path
mkdir -p build && cd build
cmake ..
cmake --build . -j
```

### B4. Point Aegis at the binary

| Variable | Meaning |
|---|---|
| `AEGIS_KART_ROOT` | Clone root (`third_party/kart`) |
| `AEGIS_KART_BIN` | Explicit path to `kart` / `kart.exe` |
| `AEGIS_KART_COMMIT` | Expected pin |

Restart the API after setting env vars. Engines page should show **found**.

---

## Online Git (Aegis repo) — what is published

Committed to **Aegis** (GitHub):

- `engines/kart/adapter.py` — discovery + stub/real anneal entry
- `engines/kart/SETUP.md` — this procedure
- `setup_and_run.cmd` + `scripts/bootstrap.ps1` — automated obtain/install
- `.gitignore` entry for `third_party/kart/`

**Not** published: KART source tree, tokens, built binaries.

---

## Verify

```bash
# API
curl http://127.0.0.1:8000/api/engines/status
```

Expect `kart_found: true` when the binary exists; otherwise `kart_message` explains clone/build next steps.
