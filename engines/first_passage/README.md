# First-passage / kPS spike (Adjanor 2025 §2)

Classical kMC kinetic-traps (flickers) in solute atmospheres. This package:

1. Detects trap basins from an event log (low-barrier cycles) — shared with KART `analyze_trapping`.
2. Builds a small absorbing Markov chain and draws a mean first-passage time (MFPT).
3. Does **not** wrap a full kPS library yet.

## Wrap vs implement (H1)

| Option | Verdict |
|--------|---------|
| Wrap existing kPS (e.g. research codes) | Prefer later — license/build friction similar to KART |
| Absorbing-chain MFPT in Aegis | **Shipped as spike** for basin escape on ML-KMC / KART event logs |

Full non-local jump caching (factorized A matrices) remains future work.
