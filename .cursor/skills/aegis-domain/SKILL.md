---
name: aegis-domain
description: PFM radiation-damage vocabulary and scale honesty for the Aegis workbench. Use when discussing tokamak PFMs, cascades, He implantation, D-D/D-T scenarios, or interpreting simulation scope.
---

# Aegis domain

## Product

**Aegis** simulates microscopic radiation damage in plasma-facing materials (PFMs): LAMMPS cascade/implant MD → defect analysis → optional k-ART (KART) anneal.

## Scale honesty

- D–D / D–T are **scenario presets** (energies, T, labels), not plasma transport.
- Cascades are expensive; default to small cells; require explicit large-run confirm.
- Defect analysis in Phase-1 is a teaching/engineering proxy, not OVITO-grade production WS.

## Vocabulary

- PKA: primary knock-on atom
- SIA: self-interstitial atom
- Fuzz / blistering: He-driven surface morphology (often needs surface MD + longer scales)
- k-ART: off-lattice KMC with on-the-fly event catalogs (KART)

## Guardrails

- Never invent interatomic potential coefficients.
- Never claim full-tokamak fidelity.
- Cite potentials and engine versions in any scientific use.
