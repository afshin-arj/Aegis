---
name: aegis-ui
description: Aegis workbench UI information architecture and visual design rules. Use when editing apps/web React UI.
---

# Aegis UI

## IA (rail workflow)

1. Projects — name study + job history
2. Material — presets + composition (Σ at% KPI; at%/wt% toggle)
3. Potential — curated filter + upload + file/placeholder status
4. Scenario — D–D / D–T + project name + default chips
5. LAMMPS — fieldsets + advanced expander
6. Run — console log / empty state
7. Results — structure before/after, defect table, cluster chart, 3D, export
8. Engines — LAMMPS + KART status
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