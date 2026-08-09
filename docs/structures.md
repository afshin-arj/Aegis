# Nanostructure builder

Aegis can start MD from a **single crystal** (LAMMPS `lattice` + `create_atoms`) or from a prebuilt **`structure.data`** loaded with `read_data`.

## Structure kinds

| Kind | Builder | Notes |
|------|---------|--------|
| `single_crystal` | LAMMPS | Default; no `structure.data` |
| `polycrystal` | Atomsk if present (mono-host), else ASE Voronoi | `poly_texture`: random \| fiber (z); not for WC hex |
| `bicrystal` | Atomsk merge if present, else ASE symmetric tilt | Tilt GB; not for WC hex |
| `void` | ASE | Spherical nano-void(s) punched from bulk |
| `void_lattice` | ASE | Simple-cubic lattice of spherical voids |
| `nanowire` | ASE | Cylinder carved from bulk + transverse vacuum |
| `precipitate` | ASE | Spherical substitutional second-phase regions |
| `polycrystal_void` | Atomsk/ASE then void punch | Grains + cavity |
| `import` | Copy / ASE read | External LAMMPS data, dump, xyz, … |

Job folders get `structure.data` + `structure_meta.json` (backend, atom count, box_A, `type_symbols`, alloy meta, kind-specific meta).

## Chemistry

- **Multi-element hosts (bcc/fcc/hcp/diamond):** ASE applies a **seeded substitutional random alloy** fill from composition `atomic_percent` before writing `structure.data`. `pair_coeff` / `specorder` follow composition order.
- **WC hex:** ASE builds a true hexagonal WC cell (metal @ 0,0,0; C @ ⅓,⅔,½) matching `crystal.py` — **not** HCP mono-metal and **not** random alloy. Polycrystal/bicrystal are refused for hex.
- **Atomsk:** used only for mono-host poly/bicrystal; never maps `hex→hcp` or unknown→`bcc`. Multi-host alloys always use ASE.
- **Import:** `type_symbols` come from the file when ASE can read them; ion/interstitial extras are appended only.

### Bicrystal params

| Param | Default | Meaning |
|-------|---------|---------|
| `gb_misorientation_deg` | 15 | Relative tilt between grains (°) |
| `gb_tilt_axis` | `001` | Rotation axis (ASE); Atomsk currently rotates about merge axis |
| `gb_normal` | `001` | GB plane normal / merge direction |

### Void lattice params

| Param | Default | Meaning |
|-------|---------|---------|
| `void_radius_A` | 5 | Sphere radius for each void (Å) |
| `void_lattice_nx/ny/nz` | 2 | Number of voids along each box edge |

### Nanowire params

| Param | Default | Meaning |
|-------|---------|---------|
| `nanowire_radius_A` | 8 | Cylinder radius (Å) |
| `nanowire_axis` | `z` | Wire axis (`x`\|`y`\|`z`) |
| `nanowire_vacuum_A` | 10 | Extra transverse vacuum (Å) |

Cascade / surface / implant on nanowires use **free transverse boundaries** and (for surface/implant) an **axis-aware beam** from a free face toward the wire.

### Precipitate params

| Param | Default | Meaning |
|-------|---------|---------|
| `precipitate_species` | `Re` | Second-phase symbol (must be in potential for real MD) |
| `precipitate_radius_A` | 5 | Sphere radius (Å) |
| `precipitate_count` | 1 | Number of precipitates (first at center; extras random) |

Substitutional proxy on the host lattice — not a second crystal structure. Matrix may be a random alloy before precipitate conversion.

## Tools

- **ASE** — required for most builders. Installed via `apps/api/requirements.txt` and `Ensure-Ase`. Opt out: `AEGIS_INSTALL_ASE=0`.
- **Atomsk** — optional mono-host polycrystal / bicrystal. Soft-fail bootstrap. Opt out: `AEGIS_INSTALL_ATOMSK=0`.

## API / UI

- LAMMPS tab → **Structure / nanostructures** fieldset + kind params, **Preview structure**, import upload.
- Preview accepts an optional material override (edited composition / `lattice_c`).
- Run is blocked when ASE is missing (or Engines status not loaded) for file-based kinds (except `import` of `.data`).
- Interstitial mode requires `single_crystal`. Surface mode refuses polycrystal/bicrystal.
- `POST /api/structure/preview` · `POST /api/structure/import`
- HPC packs copy `structure.data` + `structure_meta.json` beside `in.aegis`.

## Integrity rule

Non–single-crystal kinds **must not** silently fall back to a perfect single crystal for real MD. Dry-run still builds `structure.data` when possible, stamps `demo_structure_proxy` on Results, and warns that demo dumps are SC proxies. Builder failure → clear error (install ASE / fix params).

**HPC export** (single-job and campaign) refuses dry-run/placeholder stubs. Crystal orientation applies to single crystal only.
