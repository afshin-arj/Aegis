---
name: aegis-ui
description: Aegis workbench UI information architecture and visual design rules. Use when editing apps/web React UI.
---

# Aegis UI

## IA

1. Projects / project name  
2. Material — presets + composition  
3. Potential — curated filter + upload + select  
4. Scenario — D–D / D–T + overrides  
5. LAMMPS parameters — full control  
6. Run — start/stop/log (WebSocket)  
7. Results — defects, charts, 3D  
8. Engines — LAMMPS + KART status  

## Visual

- Instrument aesthetic: **graphite + copper** (CSS vars in `styles.css`)
- Fonts: Syne (display) + IBM Plex Sans (body) — already in `index.html`
- Avoid purple/cream AI cliché themes, emoji clutter, card-heavy dashboards

## Tech

- React + Vite; proxy `/api` to FastAPI
- Live job log via WebSocket `/api/jobs/:id/log`
- Basic Three.js defect points in Results
