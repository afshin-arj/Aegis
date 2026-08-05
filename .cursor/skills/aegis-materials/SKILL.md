---
name: aegis-materials
description: Aegis materials library — presets, composition editor (at%/wt%), validation, material.json recipes. Use when changing materials API, presets, or composition UI.
---

# Aegis materials

## Data

- Presets: `data/materials/presets.json`
- User overrides: `data/materials/user.json` (writable via API)
- Schema: `Material` (`crystal`, `lattice_constant_A`, `lattice_c_A`), `ElementFraction` — composition must sum to 100 at% (±0.05)
- Crystal registry: `engines/lammps/crystal.py` + `GET /api/crystals`
- Interstitial E_f catalog: `data/crystals/interstitial_ef.json`

## Presets

BCC: W, Mo, Ta, Fe, Cr, alloys. FCC: Cu. HCP: Be, Re. Diamond: C. Hex WC: `wc-hex`. HEA stubs may be `metadata_only`.

## Rules

- Editor supports **at% and wt%** (wt% converts via atomic masses; recipes always store at%).
- Normalize/validate before save.
- Emit `material.json` into each job directory.
- Potential compatibility: material element set ⊆ potential.elements (superset OK).
- `metadata_only` materials should not imply a runnable potential exists.
- Unsupported crystals: dry-run only (never silently build BCC).
- HCP/hex need `lattice_c_A` (or `c_over_a`).
