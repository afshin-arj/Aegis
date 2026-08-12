# Potential workbench (Aegis)

Aegis **acquires and attaches** published potentials. It never invents pair coefficients.

## Acquire flow (Phase A)

1. Choose a material (composition drives compatibility).
2. Open **Potential → Acquire / find potential** for a ranked plan.
3. Prefer **Download** rows (NIST IPR allowlisted URLs) that map onto catalog slots.
4. Otherwise **Open** browse/search pages, then **Import URL** or **Upload / attach**.
5. Cite the DOI before production science. Placeholders remain dry-run only.

API:

| Endpoint | Purpose |
|----------|---------|
| `GET /api/potentials?material_id=` | Compatible catalog + user pots |
| `GET /api/potentials/library` | Filtered library index |
| `GET /api/potentials/acquire?material_id=` | Ranked acquire plan |
| `POST /api/potentials/library/download` | Allowlisted NIST download / attach |
| `POST /api/potentials/library/import-entry` | Scrape NIST entry page |
| `POST /api/potentials/upload` | Manual attach |

Data:

- `data/potentials/catalog.json` — curated slots (placeholders until attached)
- `data/potentials/library_index.json` — NIST/OpenKIM rows
- `data/potentials/user/` + `attachments.json` — local files (gitignored)

## Literature packager (Phase B)

Paste **published** potential file text (or upload with attestation) plus DOI/citation.

- `POST /api/potentials/from-literature`
- Writes `data/potentials/user/<id>/` + `provenance.json`
- Suitability starts as `unvalidated` (`zbl` → `ballistic_only`)
- Still **never invents** coefficients — only packages user-supplied published content

## Honesty

- No coefficient synthesis / AI “make potential” inventing params.
- Multi-element Zhou04 universal-mixing file is offered for some alloys with explicit warnings.
- Systems without downloadable rows (Re, Cr, Be, W–He, WC, …) use browse + upload / literature packager.
- Later: hybrid/ZBL stitch (Phase C) — still no invention.
