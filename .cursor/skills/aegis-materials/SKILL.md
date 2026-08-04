---
name: aegis-materials
description: Aegis materials library — presets, composition editor (at%/wt%), validation, material.json recipes. Use when changing materials API, presets, or composition UI.
---

# Aegis materials

## Data

- Presets: `data/materials/presets.json`
- User overrides: `data/materials/user.json` (writable via API)
- Schema: `Material`, `ElementFraction` — composition must sum to 100 at% (±0.05)

## Phase-1 presets

W, Mo, Ta, Re, Cr, W–5Ta, W–Re, TaW, HEA stubs; ceramics may be metadata-only.

## Rules

- Editor supports **at% and wt%** (wt% converts via atomic masses; recipes always store at%).
- Normalize/validate before save.
- Emit `material.json` into each job directory.
- Potential compatibility: material element set ⊆ potential.elements (superset OK).
- `metadata_only` materials should not imply a runnable potential exists.
- Non-BCC crystals: warn — Phase-1 templates still build BCC.