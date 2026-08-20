"""Act as a real user: download potentials, run both cascade examples, hit every panel API."""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
BASE = os.environ.get("AEGIS_API", "http://127.0.0.1:8000")


def _req(method: str, path: str, body: dict | None = None, timeout: float = 120.0):
    data = None
    headers = {"Accept": "application/json"}
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read().decode("utf-8")
            return resp.status, json.loads(raw) if raw else {}
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(raw)
        except json.JSONDecodeError:
            detail = {"detail": raw}
        raise RuntimeError(f"{method} {path} -> {exc.code}: {detail}") from exc


def get(path: str, **kw):
    return _req("GET", path, **kw)[1]


def post(path: str, body: dict | None = None, **kw):
    return _req("POST", path, body=body, **kw)[1]


def wait_job(job_id: str, timeout_s: float = 3600.0) -> dict:
    t0 = time.time()
    last = ""
    while time.time() - t0 < timeout_s:
        info = get(f"/api/jobs/{job_id}")
        st = info.get("status")
        msg = info.get("message") or ""
        line = f"{st}: {msg}"
        if line != last:
            print(f"  [{job_id}] {line}")
            last = line
        if st in {"completed", "failed", "cancelled"}:
            return info
        time.sleep(2.0)
    raise TimeoutError(job_id)


def panel_walk(job_id: str) -> dict:
    """Hit Results / KMC / Engines-adjacent endpoints a user would open."""
    out: dict = {"job_id": job_id}
    out["job"] = get(f"/api/jobs/{job_id}")
    try:
        out["defects"] = get(f"/api/jobs/{job_id}/defects")
    except Exception as exc:  # noqa: BLE001
        out["defects_error"] = str(exc)
    try:
        out["cascade_timeline"] = get(f"/api/jobs/{job_id}/cascade-timeline")
    except Exception as exc:  # noqa: BLE001
        out["cascade_timeline_error"] = str(exc)
    try:
        out["trajectory"] = get(f"/api/jobs/{job_id}/trajectory")
    except Exception as exc:  # noqa: BLE001
        out["trajectory_error"] = str(exc)
    try:
        out["kart"] = get(f"/api/jobs/{job_id}/kart")
    except Exception as exc:  # noqa: BLE001
        out["kart_error"] = str(exc)
    try:
        out["ml_kmc"] = get(f"/api/jobs/{job_id}/ml-kmc")
    except Exception as exc:  # noqa: BLE001
        out["ml_kmc_error"] = str(exc)
    try:
        out["cd"] = get(f"/api/jobs/{job_id}/cluster-dynamics")
    except Exception as exc:  # noqa: BLE001
        out["cd_error"] = str(exc)
    try:
        out["dxa"] = get(f"/api/jobs/{job_id}/dxa")
    except Exception as exc:  # noqa: BLE001
        out["dxa_error"] = str(exc)
    return out


def ensure_potential(library_id: str, attach_to: str) -> dict:
    pots = get(f"/api/potentials?material_id={'w-pure' if 'w' in attach_to else 'fe-pure'}")
    ready = next((p for p in pots if p.get("id") == attach_to and p.get("available") and not p.get("is_placeholder")), None)
    if ready:
        print(f"  potential ready: {attach_to}")
        return ready
    print(f"  downloading {library_id} -> {attach_to}")
    return post(
        "/api/potentials/library/download",
        {"library_id": library_id, "attach_to_id": attach_to},
        timeout=180.0,
    )


def load_example(name: str) -> dict:
    path = ROOT / "examples" / "cascade_md" / name / "job.json"
    return json.loads(path.read_text(encoding="utf-8"))


def submit_example(ex: dict, potential_id: str, *, shorten: bool = False) -> dict:
    job = dict(ex["job"])
    job["potential_id"] = potential_id
    rp = dict(job["run_params"])
    if shorten:
        # Keep cell; shorten wall-clock via energy + step budget (cell cuts caused Fe EAM blow-ups).
        rp["pka_energy_eV"] = min(float(rp.get("pka_energy_eV") or 1000), 500.0)
        rp["max_steps"] = min(int(rp.get("max_steps") or 12000), 6000)
        rp["dump_every"] = max(200, int(rp.get("dump_every") or 400))
        rp["nx"] = max(int(rp.get("nx") or 12), 10)
        rp["ny"] = rp["nx"]
        rp["nz"] = rp["nx"]
    job["run_params"] = rp
    print(
        f"  submitting {ex['id']} potential={potential_id} "
        f"cell={rp['nx']}^3 E={rp['pka_energy_eV']}eV steps={rp['max_steps']}"
    )
    return post("/api/jobs", job, timeout=60.0)


def main() -> int:
    issues: list[str] = []
    report: dict = {"base": BASE, "panels": {}, "jobs": {}}

    print("=== Projects / health / examples ===")
    health = get("/api/health")
    examples = get("/api/examples")
    engines = get("/api/engines/status")
    materials = get("/api/materials")
    scenarios = get("/api/scenarios")
    crystals = get("/api/crystals")
    report["health"] = health
    report["examples_count"] = len(examples.get("examples") or [])
    report["engines"] = {
        "lammps_found": engines.get("lammps_found"),
        "lammps_path": engines.get("lammps_path"),
        "lammps_mpi_capable": engines.get("lammps_mpi_capable"),
        "mpi_found": engines.get("mpi_found"),
        "kart_found": engines.get("kart_found"),
        "ovito_found": engines.get("ovito_found"),
    }
    print(f"  health={health} examples={report['examples_count']}")
    print(f"  engines={report['engines']}")
    if not engines.get("lammps_found"):
        issues.append("LAMMPS not found — cascades will dry-run")
    if report["examples_count"] < 2:
        issues.append(f"expected >=2 examples, got {report['examples_count']}")

    print("=== Material / Potential / Scenario panels ===")
    w = next(m for m in materials if m["id"] == "w-pure")
    fe = next(m for m in materials if m["id"] == "fe-pure")
    print(f"  materials ok: {w['id']}, {fe['id']}")
    print(f"  scenarios: {len(scenarios)}, crystals: {len(crystals.get('crystals') or crystals)}")
    acquire_w = get("/api/potentials/acquire?material_id=w-pure")
    acquire_fe = get("/api/potentials/acquire?material_id=fe-pure")
    report["acquire_w"] = acquire_w.get("next_steps")
    report["acquire_fe"] = acquire_fe.get("next_steps")
    lib_w = get("/api/potentials/library?material_id=w-pure")
    print(f"  library W entries: {len(lib_w)}")

    print("=== Acquire Zhou04 potentials ===")
    pot_w = ensure_potential("nist-zhou04-w", "w-fs-cascade")
    pot_fe = ensure_potential("nist-zhou04-fe", "fe-eam-placeholder")
    if not pot_w.get("available"):
        issues.append("W Zhou04 not available after download")
    if not pot_fe.get("available"):
        issues.append("Fe Zhou04 not available after download")

    print("=== Structure preview (Simulate panel) ===")
    try:
        prev = post(
            "/api/structure/preview",
            {
                "material_id": "w-pure",
                "params": {
                    "nx": 4,
                    "ny": 4,
                    "nz": 4,
                    "structure_kind": "single_crystal",
                    "mode": "cascade",
                },
            },
            timeout=120.0,
        )
        report["structure_preview"] = {
            "kind": prev.get("kind"),
            "backend": prev.get("backend"),
            "atom_count": prev.get("atom_count"),
            "note": prev.get("note"),
        }
        print(f"  preview={report['structure_preview']}")
        prev_void = post(
            "/api/structure/preview",
            {
                "material_id": "w-pure",
                "params": {
                    "nx": 6,
                    "ny": 6,
                    "nz": 6,
                    "structure_kind": "void",
                    "void_radius_A": 4.0,
                    "mode": "cascade",
                },
            },
            timeout=180.0,
        )
        report["structure_preview_void"] = {
            "atom_count": prev_void.get("atom_count") or prev_void.get("n_atoms"),
            "backend": prev_void.get("backend"),
            "keys": sorted(prev_void.keys())[:12],
        }
        print(f"  void preview={report['structure_preview_void']}")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"structure preview failed: {exc}")
        report["structure_preview_error"] = str(exc)

    print("=== KMC recommend (Simulate post-cascade) ===")
    try:
        rec = post(
            "/api/kmc/recommend",
            {
                "material_id": "w-pure",
                "temperature_K": 600,
                "target_time_s": 1.0,
                "run_kart_anneal": True,
                "structure_kind": "single_crystal",
            },
        )
        report["kmc_recommend"] = rec
        print(f"  kmc tier={rec.get('recommended_tier')}")
    except Exception as exc:  # noqa: BLE001
        issues.append(f"kmc recommend failed: {exc}")
        report["kmc_recommend_error"] = str(exc)

    shorten = os.environ.get("AEGIS_EXAMPLE_SHORTEN", "1") == "1"
    ex_w = load_example("01_w_self_pka_5kev")
    ex_fe = load_example("02_fe_self_pka_10kev")

    print("=== Run W cascade ===")
    jw = submit_example(ex_w, "w-fs-cascade", shorten=shorten)
    info_w = wait_job(jw["id"])
    report["jobs"]["w"] = {"id": jw["id"], "status": info_w.get("status"), "message": info_w.get("message")}
    if info_w.get("status") != "completed":
        issues.append(f"W job failed: {info_w.get('message')}")

    print("=== Run Fe cascade ===")
    jfe = submit_example(ex_fe, "fe-eam-placeholder", shorten=shorten)
    info_fe = wait_job(jfe["id"])
    report["jobs"]["fe"] = {"id": jfe["id"], "status": info_fe.get("status"), "message": info_fe.get("message")}
    if info_fe.get("status") != "completed":
        issues.append(f"Fe job failed: {info_fe.get('message')}")

    print("=== Results panels ===")
    for key, jid in (("w", jw["id"]), ("fe", jfe["id"])):
        walk = panel_walk(jid)
        report["panels"][key] = {
            "status": walk["job"].get("status"),
            "defects": walk.get("defects"),
            "timeline_stages": len((walk.get("cascade_timeline") or {}).get("stages") or []),
            "trajectory_frames": (walk.get("trajectory") or {}).get("n_frames")
            or (walk.get("trajectory") or {}).get("frame_count"),
            "errors": {k: v for k, v in walk.items() if k.endswith("_error")},
        }
        d = walk.get("defects") or {}
        summary = d.get("summary") if isinstance(d, dict) else None
        if not isinstance(summary, dict):
            summary = d if isinstance(d, dict) else {}
        print(
            f"  {key}: defects vacancies={summary.get('vacancies')} "
            f"sia={summary.get('interstitials')} "
            f"frames={report['panels'][key]['trajectory_frames']} "
            f"stages={report['panels'][key]['timeline_stages']}"
        )
        if walk.get("defects_error"):
            issues.append(f"{key} defects: {walk['defects_error']}")
        if walk.get("trajectory_error"):
            issues.append(f"{key} trajectory: {walk['trajectory_error']}")
        if walk.get("cascade_timeline_error"):
            issues.append(f"{key} timeline: {walk['cascade_timeline_error']}")

    print("=== Campaigns list (should be empty-ok) ===")
    camps = get("/api/campaigns")
    report["campaigns"] = len(camps)
    print(f"  campaigns={len(camps)}")

    out_path = ROOT / "examples" / "cascade_md" / "_last_walkthrough.json"
    report["issues"] = issues
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"=== wrote {out_path} ===")
    if issues:
        print("ISSUES:")
        for i in issues:
            print(" -", i)
        return 1
    print("ALL OK")
    return 0


if __name__ == "__main__":
    # Load local env if present
    envf = ROOT / "tools" / "aegis_env.ps1"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8", errors="replace").splitlines():
            line = line.strip()
            if line.startswith("$env:") and "=" in line:
                # $env:FOO = 'bar'
                try:
                    left, right = line.split("=", 1)
                    key = left.replace("$env:", "").strip()
                    val = right.strip().strip("'").strip('"')
                    if key and val:
                        os.environ.setdefault(key, val)
                except ValueError:
                    pass
    raise SystemExit(main())
