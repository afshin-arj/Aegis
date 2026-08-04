---
name: aegis-potentials
description: Aegis potential catalog, NIST library download, upload validation, damage-suitable tagging. Use when editing catalog.json, library_index.json, upload/download API, or potential picker UI.
---

# Aegis potentials

## Local catalog

`data/potentials/catalog.json` entries include: id, name, formalism, elements, recommended_for, citation/DOI, source_url, warnings, lammps_pair_style, pair_coeff_template, file_path, source, available, is_placeholder.

## External library (NIST / OpenKIM)

`data/potentials/library_index.json` lists PFM-relevant browse/download rows:

- Downloadable: allowlisted NIST `.../potentials/Download/...` URLs (e.g. Zhou04 W/Mo/Ta/Fe)
- Browse-only: system pages, OpenKIM, Colab search notebook

API:

- `GET /api/potentials/library`
- `POST /api/potentials/library/download` (`library_id` or `url`)
- `POST /api/potentials/library/import-entry` (scrape NIST entry page for files)

Attachments for curated slots live in gitignored `attachments.json` + `user/`.

## Upload

- Files land in `data/potentials/user/<id>/` (gitignored)
- Indexed in `user_index.json`
- Optional `attach_to_id` fills a missing/placeholder catalog entry
- Tag `source: user|nist`

## Rules

- **Never invent potential coefficients.**
- Placeholder files: `is_placeholder=true`, `available=false` — allow dry-run jobs only.
- Refuse real MD if potential has no non-placeholder file.
- Only download from allowlisted NIST hosts; otherwise upload manually.
- Filter picker by material composition ⊆ potential elements.
- Prefer citing DOI / NIST entry URL in the UI.
