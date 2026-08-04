---
name: aegis-ui
description: Aegis workbench UI information architecture and visual design rules. Use when editing apps/web React UI.
---

# Aegis UI

## IA (rail workflow)

1. Material — presets + composition (Σ at% KPI)
2. Potential — curated filter + upload + file-on-disk status
3. Scenario — D–D / D–T + default chips
4. LAMMPS — fieldsets + advanced expander
5. Run — console log / empty state
6. Results — defect table, cluster chart, 3D
7. Engines — LAMMPS + KART status

## Expert-console patterns (SHAMS / Fair-MAST / ui-ux-pro-max)

- **Verdict-first** readiness strip (Ready / Blocked / dry-run)
- Sticky topbar: brand + engine KPIs + primary **Run job**
- Dense forms: units in labels, mono inputs, chip metadata
- Empty states with next steps
- Focus-visible rings; `prefers-reduced-motion`; skip link

## Visual

- Graphite + copper tokens in `styles.css`
- Syne + Fira Sans / Fira Code
- Avoid purple/cream AI cliché, emoji icons, card-spam

## Tech

- React + Vite; proxy `/api`
- WebSocket job log
- Three.js defect points (respect reduced motion)
