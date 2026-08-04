import { useEffect, useMemo, useRef, useState } from "react";
import * as THREE from "three";

type ElementFraction = { symbol: string; atomic_percent: number };
type Material = {
  id: string;
  name: string;
  description: string;
  crystal: string;
  lattice_constant_A: number;
  composition: ElementFraction[];
  tags: string[];
  metadata_only?: boolean;
};
type Potential = {
  id: string;
  name: string;
  elements: string[];
  recommended_for: string[];
  warnings: string[];
  available: boolean;
  source: string;
  lammps_pair_style: string;
};
type Scenario = {
  id: string;
  fuel: string;
  label: string;
  description: string;
  defaults: Record<string, unknown>;
};
type EngineStatus = {
  lammps_found: boolean;
  lammps_path?: string;
  lammps_version?: string;
  kart_found: boolean;
  kart_root?: string;
  kart_binary?: string;
  kart_commit_expected: string;
  kart_message: string;
};
type JobInfo = {
  id: string;
  status: string;
  project_name: string;
  message: string;
  defect_summary?: Record<string, number | string | object>;
  kart_summary?: Record<string, unknown>;
};
type RunParams = {
  mode: string;
  nx: number;
  ny: number;
  nz: number;
  boundary: string;
  seed: number;
  ensemble: string;
  temperature_K: number;
  damp_ps: number;
  pka_species: string;
  pka_energy_eV: number;
  pka_direction: string;
  n_pkas: number;
  pka_delay_steps: number;
  ion_type: string;
  ion_energy_eV: number;
  ion_count: number;
  ion_angle_deg: number;
  timestep_fs: number;
  max_steps: number;
  neighbor_skin: number;
  thermo_every: number;
  dump_every: number;
  dump_style: string;
  restart_every: number;
  cluster_cutoff_A: number;
  confirm_large: boolean;
};

const defaultParams: RunParams = {
  mode: "cascade",
  nx: 8,
  ny: 8,
  nz: 8,
  boundary: "p p p",
  seed: 592856,
  ensemble: "nve",
  temperature_K: 300,
  damp_ps: 0.1,
  pka_species: "W",
  pka_energy_eV: 10000,
  pka_direction: "random",
  n_pkas: 1,
  pka_delay_steps: 0,
  ion_type: "He",
  ion_energy_eV: 500,
  ion_count: 1,
  ion_angle_deg: 0,
  timestep_fs: 0.001,
  max_steps: 20000,
  neighbor_skin: 2,
  thermo_every: 100,
  dump_every: 1000,
  dump_style: "custom",
  restart_every: 0,
  cluster_cutoff_A: 3.5,
  confirm_large: false,
};

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const text = await res.text();
    throw new Error(text || res.statusText);
  }
  return res.json() as Promise<T>;
}

function DefectViz({ points }: { points: Array<{ x: number; y: number; z: number; kind: string }> }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x0c0e12);
    const camera = new THREE.PerspectiveCamera(45, el.clientWidth / el.clientHeight, 0.1, 1000);
    camera.position.set(12, 10, 16);
    camera.lookAt(0, 0, 0);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);
    const light = new THREE.DirectionalLight(0xffffff, 1.1);
    light.position.set(5, 10, 7);
    scene.add(light);
    scene.add(new THREE.AmbientLight(0x6688aa, 0.35));

    const group = new THREE.Group();
    for (const p of points.slice(0, 2000)) {
      const color = p.kind === "vacancy" ? 0xc45c4a : p.kind === "interstitial" ? 0xc47a3a : 0x5b9a6f;
      const geo = new THREE.SphereGeometry(0.12, 10, 10);
      const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.45, metalness: 0.2 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(p.x - 4, p.y - 4, p.z - 4);
      group.add(mesh);
    }
    scene.add(group);
    let frame = 0;
    let alive = true;
    const animate = () => {
      if (!alive) return;
      frame = requestAnimationFrame(animate);
      group.rotation.y += 0.004;
      renderer.render(scene, camera);
    };
    animate();
    return () => {
      alive = false;
      cancelAnimationFrame(frame);
      renderer.dispose();
      el.innerHTML = "";
    };
  }, [points]);
  return <div className="viz" ref={ref} />;
}

export default function App() {
  const [tab, setTab] = useState("setup");
  const [materials, setMaterials] = useState<Material[]>([]);
  const [potentials, setPotentials] = useState<Potential[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [engines, setEngines] = useState<EngineStatus | null>(null);
  const [materialId, setMaterialId] = useState("w-pure");
  const [composition, setComposition] = useState<ElementFraction[]>([
    { symbol: "W", atomic_percent: 100 },
  ]);
  const [lattice, setLattice] = useState(3.165);
  const [potentialId, setPotentialId] = useState("");
  const [scenarioId, setScenarioId] = useState("dt-divertor");
  const [params, setParams] = useState<RunParams>(defaultParams);
  const [projectName, setProjectName] = useState("W-He study");
  const [runKart, setRunKart] = useState(false);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [log, setLog] = useState("");
  const [defects, setDefects] = useState<{
    summary?: Record<string, unknown>;
    points?: Array<{ x: number; y: number; z: number; kind: string }>;
    clusters?: Array<{ size: number }>;
  } | null>(null);
  const [error, setError] = useState("");
  const [uploadName, setUploadName] = useState("");
  const [uploadElements, setUploadElements] = useState("W");
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [busy, setBusy] = useState(false);

  const material = useMemo(
    () => materials.find((m) => m.id === materialId),
    [materials, materialId]
  );

  useEffect(() => {
    Promise.all([
      api<Material[]>("/api/materials"),
      api<Scenario[]>("/api/scenarios"),
      api<EngineStatus>("/api/engines/status"),
    ])
      .then(([m, s, e]) => {
        setMaterials(m);
        setScenarios(s);
        setEngines(e);
        const first = m.find((x) => x.id === "w-pure") || m[0];
        if (first) {
          setMaterialId(first.id);
          setComposition(first.composition);
          setLattice(first.lattice_constant_A);
        }
      })
      .catch((err) => setError(String(err)));
  }, []);

  useEffect(() => {
    if (!materialId) return;
    api<Potential[]>(`/api/potentials?material_id=${materialId}`)
      .then((p) => {
        setPotentials(p);
        const avail = p.find((x) => x.available) || p[0];
        setPotentialId(avail?.id || "");
      })
      .catch((err) => setError(String(err)));
  }, [materialId, composition]);

  useEffect(() => {
    const sc = scenarios.find((s) => s.id === scenarioId);
    if (!sc) return;
    setParams((prev) => ({ ...prev, ...sc.defaults }) as RunParams);
  }, [scenarioId, scenarios]);

  useEffect(() => {
    if (!job) return;
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    // Through Vite proxy
    const ws = new WebSocket(`${wsProto}://${location.host}/api/jobs/${job.id}/log`);
    ws.onmessage = (ev) => setLog((prev) => prev + ev.data);
    const timer = setInterval(async () => {
      try {
        const info = await api<JobInfo>(`/api/jobs/${job.id}`);
        setJob(info);
        if (["completed", "failed", "cancelled"].includes(info.status)) {
          clearInterval(timer);
          if (info.status === "completed") {
            const d = await api<typeof defects>(`/api/jobs/${job.id}/defects`);
            setDefects(d);
            setTab("results");
          }
        }
      } catch {
        /* ignore transient */
      }
    }, 1000);
    return () => {
      ws.close();
      clearInterval(timer);
    };
  }, [job?.id]);

  function setParam<K extends keyof RunParams>(key: K, value: RunParams[K]) {
    setParams((p) => ({ ...p, [key]: value }));
  }

  async function saveComposition() {
    if (!material) return;
    setBusy(true);
    setError("");
    try {
      const updated = await api<Material>(`/api/materials/${material.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          composition,
          lattice_constant_A: lattice,
        }),
      });
      setMaterials((ms) => ms.map((m) => (m.id === updated.id ? updated : m)));
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function uploadPotential() {
    if (!uploadFile) return;
    setBusy(true);
    setError("");
    try {
      const meta = {
        name: uploadName || uploadFile.name,
        formalism: "eam/alloy",
        elements: uploadElements.split(/[\s,]+/).filter(Boolean),
        lammps_pair_style: "eam/alloy",
        pair_coeff_template: "pair_coeff * * {file} {elements}",
        notes: "Uploaded via Aegis UI",
        recommended_for: ["cascade"],
      };
      const fd = new FormData();
      fd.append("file", uploadFile);
      fd.append("meta", JSON.stringify(meta));
      const pot = await api<Potential>("/api/potentials/upload", { method: "POST", body: fd });
      setPotentials((p) => [...p, pot]);
      setPotentialId(pot.id);
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  async function runJob() {
    setBusy(true);
    setError("");
    setLog("");
    setDefects(null);
    try {
      const total = composition.reduce((s, e) => s + Number(e.atomic_percent), 0);
      const normalized =
        total > 0
          ? composition.map((e) => ({
              ...e,
              atomic_percent: (Number(e.atomic_percent) / total) * 100,
            }))
          : composition;
      const body = {
        project_name: projectName,
        material_id: materialId,
        material_override: material
          ? { ...material, composition: normalized, lattice_constant_A: lattice }
          : undefined,
        potential_id: potentialId,
        scenario_id: scenarioId,
        run_params: params,
        run_kart_anneal: runKart,
        kart_temperature_K: params.temperature_K,
        kart_max_events: 200,
      };
      const info = await api<JobInfo>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setJob(info);
      setTab("run");
    } catch (err) {
      setError(String(err));
    } finally {
      setBusy(false);
    }
  }

  const clusterSizes = defects?.clusters?.map((c) => c.size) || [];
  const maxCluster = Math.max(1, ...clusterSizes);

  return (
    <div className="app">
      <header className="hero">
        <div>
          <span className="badge">PFM radiation damage bench</span>
          <h1>Aegis</h1>
          <p>
            Configure plasma-facing materials, potentials, and LAMMPS cascade/implant
            parameters. Optional k-ART (KART) annealing. D–D / D–T are scenario presets —
            not a full tokamak.
          </p>
        </div>
        <div className="stack" style={{ alignItems: "flex-end" }}>
          <span className="pill">
            LAMMPS:{" "}
            <strong className={engines?.lammps_found ? "status-ok" : "status-warn"}>
              {engines?.lammps_found ? "found" : "dry-run"}
            </strong>
          </span>
          <span className="pill">
            KART:{" "}
            <strong className={engines?.kart_found ? "status-ok" : "status-warn"}>
              {engines?.kart_found ? "found" : "stub"}
            </strong>
          </span>
        </div>
      </header>

      <div className="tabs">
        {["setup", "params", "run", "results", "engines"].map((t) => (
          <button key={t} className={tab === t ? "active" : ""} onClick={() => setTab(t)}>
            {t}
          </button>
        ))}
      </div>

      {error && (
        <div className="panel" style={{ marginBottom: "1rem", borderColor: "var(--err)" }}>
          <span className="status-err">{error}</span>
        </div>
      )}

      {tab === "setup" && (
        <div className="grid">
          <section className="panel stack">
            <h2>Material</h2>
            <label>
              Preset
              <select
                value={materialId}
                onChange={(e) => {
                  const id = e.target.value;
                  setMaterialId(id);
                  const m = materials.find((x) => x.id === id);
                  if (m) {
                    setComposition(m.composition);
                    setLattice(m.lattice_constant_A);
                  }
                }}
              >
                {materials.map((m) => (
                  <option key={m.id} value={m.id}>
                    {m.name}
                    {m.metadata_only ? " (metadata)" : ""}
                  </option>
                ))}
              </select>
            </label>
            <p className="muted">{material?.description}</p>
            <h3>Composition (at%)</h3>
            {composition.map((row, idx) => (
              <div className="comp-row" key={idx}>
                <label>
                  Element
                  <input
                    value={row.symbol}
                    onChange={(e) => {
                      const next = [...composition];
                      next[idx] = { ...row, symbol: e.target.value };
                      setComposition(next);
                    }}
                  />
                </label>
                <label>
                  at%
                  <input
                    type="number"
                    value={row.atomic_percent}
                    onChange={(e) => {
                      const next = [...composition];
                      next[idx] = { ...row, atomic_percent: Number(e.target.value) };
                      setComposition(next);
                    }}
                  />
                </label>
                <button
                  className="secondary"
                  type="button"
                  onClick={() => setComposition(composition.filter((_, i) => i !== idx))}
                >
                  Remove
                </button>
              </div>
            ))}
            <div className="row">
              <button
                className="secondary"
                type="button"
                onClick={() =>
                  setComposition([...composition, { symbol: "Ta", atomic_percent: 0 }])
                }
              >
                Add element
              </button>
              <label>
                Lattice a (Å)
                <input
                  type="number"
                  step="0.001"
                  value={lattice}
                  onChange={(e) => setLattice(Number(e.target.value))}
                />
              </label>
            </div>
            <button type="button" disabled={busy} onClick={saveComposition}>
              Save composition override
            </button>
          </section>

          <section className="panel stack">
            <h2>Potential</h2>
            <label>
              Compatible potentials
              <select value={potentialId} onChange={(e) => setPotentialId(e.target.value)}>
                {potentials.map((p) => (
                  <option key={p.id} value={p.id}>
                    {p.available ? "●" : "○"} {p.name} [{p.source}]
                  </option>
                ))}
              </select>
            </label>
            {potentials
              .filter((p) => p.id === potentialId)
              .map((p) => (
                <div key={p.id} className="muted">
                  <div>pair_style: {p.lammps_pair_style}</div>
                  <div>elements: {p.elements.join(", ")}</div>
                  <div>tags: {p.recommended_for.join(", ") || "—"}</div>
                  {p.warnings?.map((w) => (
                    <div key={w} className="status-warn">
                      {w}
                    </div>
                  ))}
                </div>
              ))}
            <h3>Upload local potential</h3>
            <label>
              Display name
              <input value={uploadName} onChange={(e) => setUploadName(e.target.value)} />
            </label>
            <label>
              Elements (space-separated)
              <input
                value={uploadElements}
                onChange={(e) => setUploadElements(e.target.value)}
              />
            </label>
            <label>
              File
              <input
                type="file"
                onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
              />
            </label>
            <button type="button" disabled={busy || !uploadFile} onClick={uploadPotential}>
              Upload potential
            </button>
            <p className="muted">
              Curated catalog entries need a redistributable file on disk (or upload) before a
              job can run. Aegis never invents coefficients.
            </p>
          </section>

          <section className="panel stack" style={{ gridColumn: "1 / -1" }}>
            <h2>Scenario</h2>
            <div className="row">
              <label>
                Fuel preset
                <select value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
                  {scenarios.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label} ({s.fuel})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Project name
                <input value={projectName} onChange={(e) => setProjectName(e.target.value)} />
              </label>
            </div>
            <p className="muted">{scenarios.find((s) => s.id === scenarioId)?.description}</p>
          </section>
        </div>
      )}

      {tab === "params" && (
        <section className="panel stack">
          <h2>LAMMPS parameters</h2>
          <div className="row">
            <label>
              Mode
              <select value={params.mode} onChange={(e) => setParam("mode", e.target.value)}>
                <option value="cascade">cascade / PKA</option>
                <option value="implant">ion implant</option>
              </select>
            </label>
            <label>
              T (K)
              <input
                type="number"
                value={params.temperature_K}
                onChange={(e) => setParam("temperature_K", Number(e.target.value))}
              />
            </label>
            <label>
              Seed
              <input
                type="number"
                value={params.seed}
                onChange={(e) => setParam("seed", Number(e.target.value))}
              />
            </label>
          </div>
          <h3>System</h3>
          <div className="row">
            {(["nx", "ny", "nz"] as const).map((k) => (
              <label key={k}>
                {k}
                <input
                  type="number"
                  value={params[k]}
                  onChange={(e) => setParam(k, Number(e.target.value))}
                />
              </label>
            ))}
            <label>
              Boundary
              <input
                value={params.boundary}
                onChange={(e) => setParam("boundary", e.target.value)}
              />
            </label>
          </div>
          <h3>Cascade / PKA</h3>
          <div className="row">
            <label>
              PKA species
              <input
                value={params.pka_species}
                onChange={(e) => setParam("pka_species", e.target.value)}
              />
            </label>
            <label>
              Energy (eV)
              <input
                type="number"
                value={params.pka_energy_eV}
                onChange={(e) => setParam("pka_energy_eV", Number(e.target.value))}
              />
            </label>
            <label>
              Direction
              <input
                value={params.pka_direction}
                onChange={(e) => setParam("pka_direction", e.target.value)}
                placeholder="random or 1 1 0"
              />
            </label>
            <label>
              # PKAs
              <input
                type="number"
                value={params.n_pkas}
                onChange={(e) => setParam("n_pkas", Number(e.target.value))}
              />
            </label>
          </div>
          <h3>Implant</h3>
          <div className="row">
            <label>
              Ion
              <input
                value={params.ion_type}
                onChange={(e) => setParam("ion_type", e.target.value)}
              />
            </label>
            <label>
              Ion E (eV)
              <input
                type="number"
                value={params.ion_energy_eV}
                onChange={(e) => setParam("ion_energy_eV", Number(e.target.value))}
              />
            </label>
            <label>
              Ion count
              <input
                type="number"
                value={params.ion_count}
                onChange={(e) => setParam("ion_count", Number(e.target.value))}
              />
            </label>
          </div>
          <h3>Dynamics / output</h3>
          <div className="row">
            <label>
              Timestep (fs)
              <input
                type="number"
                step="0.0001"
                value={params.timestep_fs}
                onChange={(e) => setParam("timestep_fs", Number(e.target.value))}
              />
            </label>
            <label>
              Max steps
              <input
                type="number"
                value={params.max_steps}
                onChange={(e) => setParam("max_steps", Number(e.target.value))}
              />
            </label>
            <label>
              Thermo every
              <input
                type="number"
                value={params.thermo_every}
                onChange={(e) => setParam("thermo_every", Number(e.target.value))}
              />
            </label>
            <label>
              Dump every
              <input
                type="number"
                value={params.dump_every}
                onChange={(e) => setParam("dump_every", Number(e.target.value))}
              />
            </label>
          </div>
          <label style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
            <input
              type="checkbox"
              checked={params.confirm_large}
              onChange={(e) => setParam("confirm_large", e.target.checked)}
              style={{ width: "auto" }}
            />
            Confirm large cell (&gt;20³)
          </label>
          <label style={{ flexDirection: "row", alignItems: "center", gap: "0.5rem" }}>
            <input
              type="checkbox"
              checked={runKart}
              onChange={(e) => setRunKart(e.target.checked)}
              style={{ width: "auto" }}
            />
            Queue KART anneal after MD
          </label>
          <button type="button" disabled={busy || !potentialId} onClick={runJob}>
            Run job
          </button>
        </section>
      )}

      {tab === "run" && (
        <section className="panel stack">
          <h2>Run</h2>
          {job ? (
            <>
              <div className="row">
                <span className="pill">id: {job.id}</span>
                <span className="pill">status: {job.status}</span>
                <span className="pill">{job.message}</span>
              </div>
              <div className="log">{log || "Waiting for log…"}</div>
              <button
                className="secondary"
                type="button"
                onClick={() => api(`/api/jobs/${job.id}/cancel`, { method: "POST" })}
              >
                Cancel
              </button>
            </>
          ) : (
            <p className="muted">No active job. Configure setup/params and run.</p>
          )}
        </section>
      )}

      {tab === "results" && (
        <div className="grid">
          <section className="panel stack">
            <h2>Defect summary</h2>
            {defects?.summary ? (
              <table className="table">
                <tbody>
                  {Object.entries(defects.summary).map(([k, v]) => (
                    <tr key={k}>
                      <th>{k}</th>
                      <td>{typeof v === "object" ? JSON.stringify(v) : String(v)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            ) : (
              <p className="muted">No results yet.</p>
            )}
            <h3>Cluster sizes</h3>
            <div className="chart">
              {clusterSizes.length === 0 && <span className="muted">—</span>}
              {clusterSizes.map((s, i) => (
                <div
                  key={i}
                  className="bar"
                  style={{ height: `${(s / maxCluster) * 100}%` }}
                  title={`size ${s}`}
                />
              ))}
            </div>
            {job?.kart_summary && (
              <>
                <h3>KART</h3>
                <pre className="muted" style={{ whiteSpace: "pre-wrap" }}>
                  {JSON.stringify(job.kart_summary, null, 2)}
                </pre>
              </>
            )}
          </section>
          <section className="panel stack">
            <h2>3D defect points</h2>
            <DefectViz points={defects?.points || []} />
          </section>
        </div>
      )}

      {tab === "engines" && (
        <section className="panel stack">
          <h2>Engines</h2>
          <h3>LAMMPS</h3>
          <p>
            Found:{" "}
            <strong className={engines?.lammps_found ? "status-ok" : "status-warn"}>
              {String(engines?.lammps_found)}
            </strong>
          </p>
          <p className="muted">{engines?.lammps_path || "Set AEGIS_LAMMPS_BIN"}</p>
          <p className="muted">{engines?.lammps_version}</p>
          <h3>KART (k-ART)</h3>
          <p>
            Found:{" "}
            <strong className={engines?.kart_found ? "status-ok" : "status-warn"}>
              {String(engines?.kart_found)}
            </strong>
          </p>
          <p className="muted">Expected commit: {engines?.kart_commit_expected}</p>
          <p className="muted">{engines?.kart_root || "third_party/kart not present"}</p>
          <p className="muted">{engines?.kart_message}</p>
          <pre className="log" style={{ height: "auto" }}>
{`# Clone KART (PAT or SSH — never commit tokens)
git clone git@gitlab.com:groupe_mousseau/kart.git third_party/kart
cd third_party/kart
git checkout 62d66adf
# then build per https://kart-doc.readthedocs.io/
# set AEGIS_KART_ROOT / AEGIS_KART_BIN`}
          </pre>
        </section>
      )}
    </div>
  );
}
