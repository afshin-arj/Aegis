"""Validate shipped cascade-MD examples as a user would: schema, PKA host, LAMMPS timestep."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "packages" / "schema"))
sys.path.insert(0, str(ROOT / "engines"))
sys.path.insert(0, str(ROOT / "apps" / "api"))

from aegis_schema import JobCreate, Material  # noqa: E402
from aegis_api.coverage import validate_cascade_pka  # noqa: E402
from lammps.templates import (  # noqa: E402
    apply_growth_timestep_scaling,
    plan_cascade_stages,
    timestep_metal_ps,
    write_cascade_input,
)

PRESETS = json.loads((ROOT / "data" / "materials" / "presets.json").read_text(encoding="utf-8"))
MATERIALS = {m["id"]: m for m in PRESETS}


def _examples() -> list[Path]:
    return sorted(Path(__file__).resolve().parent.glob("*/job.json"))


def main() -> int:
    jobs = _examples()
    if not jobs:
        print("no example job.json files found", file=sys.stderr)
        return 1
    errors: list[str] = []
    with tempfile.TemporaryDirectory(prefix="aegis-examples-") as tmp:
        out_root = Path(tmp)
        for path in jobs:
            data = json.loads(path.read_text(encoding="utf-8"))
            try:
                body = JobCreate.model_validate(data["job"])
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{path.parent.name}: JobCreate invalid: {exc}")
                continue
            mat_raw = MATERIALS.get(body.material_id)
            if not mat_raw:
                errors.append(f"{path.parent.name}: unknown material_id {body.material_id}")
                continue
            material = Material.model_validate(mat_raw)
            try:
                validate_cascade_pka(material, body.run_params)
            except ValueError as exc:
                errors.append(f"{path.parent.name}: PKA check: {exc}")
                continue
            params = body.run_params.model_dump(mode="json")
            dt_ps = timestep_metal_ps(params.get("timestep_fs"))
            if float(params.get("timestep_fs") or 0) == 1.0 and abs(dt_ps - 0.001) > 1e-12:
                errors.append(f"{path.parent.name}: 1 fs did not convert to 0.001 ps (got {dt_ps})")
            dest = out_root / path.parent.name
            dest.mkdir(exist_ok=True)
            dummy_pot = dest / "dummy.eam.alloy"
            dummy_pot.write_text("# example dummy pair file (not coefficients)\n", encoding="utf-8")
            in_path = dest / "in.aegis"
            write_cascade_input(
                in_path,
                material=material.model_dump(mode="json"),
                potential={
                    "lammps_pair_style": "eam/alloy",
                    "pair_coeff_template": "pair_coeff * * {file} {elements}",
                },
                params=params,
                potential_file=dummy_pot.name,
            )
            text = in_path.read_text(encoding="utf-8")
            if "timestep 0.001" not in text:
                errors.append(f"{path.parent.name}: in.aegis missing 'timestep 0.001' (got metal dt_ps={dt_ps})")
                continue
            # Growth dt scaling must be reflected in cascade_timeline.json (UI scrubber)
            timeline = json.loads((dest / "cascade_timeline.json").read_text(encoding="utf-8"))
            growth = next((s for s in timeline.get("stages") or [] if s.get("id") == "growth"), None)
            raw = plan_cascade_stages(
                energy_eV=float(params.get("pka_energy_eV") or 1000),
                timestep_fs=float(params.get("timestep_fs") or 1.0),
                max_steps=int(params.get("max_steps") or 1000),
                dump_every=int(params.get("dump_every") or 100),
                auto=bool(params.get("cascade_auto_stages", True)),
            )
            scaled = apply_growth_timestep_scaling(raw, dt_ps=dt_ps)
            if growth and timeline.get("total_steps") != scaled.get("total_steps"):
                errors.append(
                    f"{path.parent.name}: timeline total_steps "
                    f"{timeline.get('total_steps')} != scaled {scaled.get('total_steps')}"
                )
                continue
            if growth and int(growth.get("steps") or 0) != int(
                next(s["steps"] for s in scaled["stages"] if s["id"] == "growth")
            ):
                errors.append(f"{path.parent.name}: growth steps not synced to finer timestep")
                continue
            # Script run count for growth must match timeline
            if growth and f"run {int(growth['steps'])}" not in text:
                errors.append(
                    f"{path.parent.name}: in.aegis missing run {growth['steps']} for scaled growth"
                )
                continue
            pka = str(params.get("pka_species") or "")
            hosts = [c["symbol"] for c in mat_raw["composition"] if float(c.get("atomic_percent") or 0) > 0]
            if pka not in hosts:
                errors.append(f"{path.parent.name}: pka_species {pka!r} not in hosts {hosts}")
                continue
            print(
                f"OK {path.parent.name}: pka={pka} dt_ps={dt_ps} "
                f"timeline_steps={timeline.get('total_steps')}"
            )
    if errors:
        for e in errors:
            print("FAIL", e, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
