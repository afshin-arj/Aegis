---
name: aegis-ui
description: Aegis workbench UI information architecture and visual design rules. Use when editing apps/web React UI.
---

# Aegis UI

## IA (rail workflow)

1. Projects — name study + job history + per-job HPC export
2. DOE — DEMO Cartesian sweeps + campaign summary table + HPC zip
3. Material — presets + composition (Σ at% KPI; at%/wt% toggle)
3. Potential — local library + NIST/OpenKIM download + upload/attach
5. Scenario — D–D / D–T + project name + default chips
6. LAMMPS — fieldsets + advanced expander
7. Run — console log / empty state / HPC pack download
8. Results — structure before/after, cascade stages, defect table, cluster chart, 3D, defects JSON + cascade GIF export
9. Engines — LAMMPS + KART + optional MMonCa status
## Expert-console patterns (SHAMS / Fair-MAST / ui-ux-pro-max)

- **Verdict-first** readiness strip (Ready / Blocked / dry-run)
- Sticky topbar: brand + engine KPIs + primary **Run job**
- Dense forms: units in labels, mono inputs, chip metadata
- Empty states with next steps
- Focus-visible rings; `prefers-reduced-motion`; skip link
- Placeholder potentials: warn and allow dry-run only

## Visual

- Graphite + copper tokens in `styles.css`
- Syne + Fira Sans / Fira Code
- Avoid purple/cream AI cliché, emoji icons, card-spam

## Tech

- React + Vite; proxy `/api`
- WebSocket job log
- Three.js defect points + StructureViewer trajectory scrub (respect reduced motion)
- Cascade GIF: `GET /api/jobs/{id}/animation.gif` (Pillow 2D); also written as `animation.gif` after analysis
- Crystal registry: Material shows a/c, filtered interstitial geometries; Engines reports ASE/OVITO/Atomsk
- Results: OVITO DXA panel (install via Engines → Install OVITO / `pip install -U ovito`)
- Engines: OVITO mode/version + one-click pip install; see `docs/ovito.md`