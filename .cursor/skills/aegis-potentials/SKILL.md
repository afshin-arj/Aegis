---
name: aegis-potentials
description: Aegis potential catalog, upload validation, damage-suitable tagging. Use when editing catalog.json, upload API, or potential picker UI.
---

# Aegis potentials

## Catalog

`data/potentials/catalog.json` entries include: id, name, formalism, elements, recommended_for, citation/DOI, warnings, lammps_pair_style, pair_coeff_template, file_path, source, available.

## Upload

- Files land in `data/potentials/user/<id>/` (gitignored)
- Indexed in `user_index.json`
- Tag `source: user` and warn "unvalidated"

## Rules

- **Never invent potential coefficients.**
- Refuse job start if potential has no file (`available` / `file_path`).
- Prefer links + user download; only vendor redistributable files.
- Filter picker by material composition ⊆ potential elements.
- Curated entries may point at placeholder files for dry-run only — warn clearly.
