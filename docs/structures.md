# Nanostructure builder

Aegis can start MD from a **single crystal** (LAMMPS `lattice` + `create_atoms`) or from a prebuilt **`structure.data`** loaded with `read_data`.

## Structure kinds

| Kind | Builder | Notes |
|------|---------|--------|
| `single_crystal` | LAMMPS | Default; no `structure.data` |
| `polycrystal` | Atomsk if present, else ASE Voronoi | `poly_texture`: random \| fiber (z) |
| `bicrystal` | Atomsk merge if present, else ASE symmetric tilt | Tilt GB; set misorientation / tilt axis / GB normal |
| `void` | ASE | Spherical nano-void(s) punched from bulk |
| `void_lattice` | ASE | Simple-cubic lattice of spherical voids |
| `nanowire` | ASE | Cylinder carved from bulk + transverse vacuum |
| `precipitate` | ASE | Spherical substitutional second-phase regions |
| `polycrystal_void` | Atomsk/ASE then void punch | Grains + cavity |
| `import` | Copy / ASE read | External LAMMPS data, dump, xyz, … |

Job folders get `structure.data` + `structure_meta.json` (backend, atom count, box_A, kind-specific meta).

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

### Precipitate params

| Param | Default | Meaning |
|-------|---------|---------|
| `precipitate_species` | `Re` | Second-phase symbol (must be in potential for real MD) |
| `precipitate_radius_A` | 5 | Sphere radius (Å) |
| `precipitate_count` | 1 | Number of precipitates (first at center; extras random) |

Substitutional proxy on the **host lattice** — not a second crystal structure.

## Tools

- **ASE** — required for most builders. Installed via `apps/api/requirements.txt` and `Ensure-Ase`. Opt out: `AEGIS_INSTALL_ASE=0`.
- **Atomsk** — optional polycrystal / bicrystal. Soft-fail bootstrap. Opt out: `AEGIS_INSTALL_ATOMSK=0`.

## API / UI

- LAMMPS tab → **Structure** selector + kind params, **Preview structure**, import upload.
- Run is blocked when ASE is missing for file-based kinds (except `import` of `.data`).
- `POST /api/structure/preview` · `POST /api/structure/import`
- HPC packs copy `structure.data` + `structure_meta.json` beside `in.aegis`.

## Integrity rule

Non–single-crystal kinds **must not** silently fall back to a perfect single crystal for real MD. Dry-run still builds `structure.data` when possible and warns that demo dumps are SC proxies. Builder failure → clear error (install ASE / fix params).
