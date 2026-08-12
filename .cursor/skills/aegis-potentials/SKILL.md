---
name: aegis-potentials
description: Aegis potential catalog, NIST library download, acquire wizard, upload validation, damage-suitable tagging. Use when editing catalog.json, library_index.json, upload/download/acquire API, or potential picker UI.
---

# Aegis potentials

## Local catalog

`data/potentials/catalog.json` entries include: id, name, formalism, elements, recommended_for, citation/DOI, source_url, warnings, lammps_pair_style, pair_coeff_template, file_path, source, available, is_placeholder.

## External library (NIST / OpenKIM)

`data/potentials/library_index.json` lists PFM-relevant browse/download rows:

- Downloadable: allowlisted NIST `.../potentials/Download/...` URLs (Zhou04 W/Mo/Ta/Fe/Cu + 16-element alloy file)
- Browse-only: system / element-search pages, OpenKIM, Colab search notebook

API:

- `GET /api/potentials/library`
- `GET /api/potentials/acquire?material_id=` — ranked find/import/attach plan (never invents coeffs)
- `POST /api/potentials/library/download` (`library_id` or `url`)
- `POST /api/potentials/library/import-entry` (scrape NIST entry page for files)
- `POST /api/potentials/from-literature` — package published file text + DOI/provenance

Attachments for curated slots live in gitignored `attachments.json` + `user/`.

## Literature packager

- Requires attestation + DOI (or unpublished_research flag)
- Writes potential file + `provenance.json` under `user/<id>/`
- `suitability`: `unvalidated` by default; `zbl` → `ballistic_only`
- **Never invents** coefficients — paste published SI/NIST file bodies only

## Upload

- Files land in `data/potentials/user/<id>/` (gitignored)
- Indexed in `user_index.json`
- Optional `attach_to_id` fills a missing/placeholder catalog entry
- Tag `source: user|nist|literature`
- Optional DOI/attestation on upload routes through the literature packager

## Rules

- **Never invent potential coefficients.**
- Placeholder files: `is_placeholder=true`, `available=false` — allow dry-run jobs only.
- Refuse real MD if potential has no non-placeholder file.
- Only download from allowlisted NIST hosts; otherwise upload / literature-package manually.
- Filter picker by material composition ⊆ potential elements.
- Prefer citing DOI / NIST entry URL in the UI.
- Acquire wizard ranks downloads over browse; multi-element universal-mixing files carry honesty warnings.
- Literature packs start `unvalidated` — not cascade-ready until expert/smoke validation (Phase C).
