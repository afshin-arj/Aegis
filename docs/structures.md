# Nanostructure builder

Aegis can start MD from a **single crystal** (LAMMPS `lattice` + `create_atoms`) or from a prebuilt **`structure.data`** loaded with `read_data`.

## Structure kinds

| Kind | Builder | Notes |
|------|---------|--------|
| `single_crystal` | LAMMPS | Default; no `structure.data` |
| `polycrystal` | Atomsk if present, else ASE Voronoi | Engineering multi-grain proxy |
| `bicrystal` | Atomsk merge if present, else ASE symmetric tilt | Tilt GB; set misorientation / tilt axis / GB normal |
| `void` | ASE | Spherical nano-void(s) punched from bulk |
| `void_lattice` | ASE | Simple-cubic lattice of spherical voids (bubble-lattice / swelling proxy) |
| `polycrystal_void` | Atomsk/ASE then void punch | Grains + cavity |
| `import` | Copy / ASE read | External LAMMPS data, dump, xyz, … |

Job folders get `structure.data` + `structure_meta.json` (backend, atom count, GB / void metadata).

### Bicrystal params

| Param | Default | Meaning |
|-------|---------|---------|
| `gb_misorientation_deg` | 15 | Relative tilt between grains (°) |
| `gb_tilt_axis` | `001` | Rotation axis (Miller compact: `001`, `011`, `111`, …) |
| `gb_normal` | `001` | GB plane normal / merge direction (`100`/`010`/`001`) |

ASE builds a **symmetric tilt** (±θ/2) and joins half-cells along the normal. Atomsk (when available) creates two grains and `--merge`s them. Both are engineering constructions — relax / verify in OVITO before production GB studies.

### Void lattice params

| Param | Default | Meaning |
|-------|---------|---------|
| `void_radius_A` | 5 | Sphere radius for each void (Å) |
| `void_lattice_nx/ny/nz` | 2 | Number of voids along each box edge |

Voids sit at subcell centers. Build fails if spacing ≲ 2× radius (overlapping cavities).

## Tools

- **ASE** — required for void / polycrystal / bicrystal fallback. Installed via `apps/api/requirements.txt` and `Ensure-Ase` in `setup_and_run.cmd`. Opt out: `AEGIS_INSTALL_ASE=0`.
- **Atomsk** — optional higher-fidelity polycrystal / bicrystal. Soft-fail bootstrap probes `PATH`, `AEGIS_ATOMSK_BIN`, and `third_party/atomsk/`. Opt out: `AEGIS_INSTALL_ATOMSK=0`.

## API / UI

- LAMMPS tab → **Structure** selector, void/poly/GB params, **Preview structure**, import upload.
- `POST /api/structure/preview` — build temp structure, return metadata.
- `POST /api/structure/import` — upload file; set `structure_import_path` on the run.

## Integrity rule

Polycrystal / bicrystal / void / void_lattice / import **must not** silently fall back to a perfect single crystal. If the builder fails, the job errors with a clear message (install ASE / fix Atomsk / check void radius, lattice spacing, or GB params).
