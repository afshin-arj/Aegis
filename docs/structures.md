# Nanostructure builder

Aegis can start MD from a **single crystal** (LAMMPS `lattice` + `create_atoms`) or from a prebuilt **`structure.data`** loaded with `read_data`.

## Structure kinds

| Kind | Builder | Notes |
|------|---------|--------|
| `single_crystal` | LAMMPS | Default; no `structure.data` |
| `polycrystal` | Atomsk if present, else ASE Voronoi | Engineering GB proxy |
| `void` | ASE | Spherical nano-void(s) punched from bulk |
| `polycrystal_void` | Atomsk/ASE then void punch | Grains + cavity |
| `import` | Copy / ASE read | External LAMMPS data, dump, xyz, … |

Job folders get `structure.data` + `structure_meta.json` (backend, atom count, void removals).

## Tools

- **ASE** — required for void / polycrystal fallback. Installed via `apps/api/requirements.txt` and `Ensure-Ase` in `setup_and_run.cmd`. Opt out: `AEGIS_INSTALL_ASE=0`.
- **Atomsk** — optional higher-fidelity polycrystal. Soft-fail bootstrap probes `PATH`, `AEGIS_ATOMSK_BIN`, and `third_party/atomsk/`. Opt out: `AEGIS_INSTALL_ATOMSK=0`.

## API / UI

- LAMMPS tab → **Structure** selector, void/poly params, **Preview structure**, import upload.
- `POST /api/structure/preview` — build temp structure, return metadata.
- `POST /api/structure/import` — upload file; set `structure_import_path` on the run.

## Integrity rule

Polycrystal / void / import **must not** silently fall back to a perfect single crystal. If the builder fails, the job errors with a clear message (install ASE / fix Atomsk / check void radius).
