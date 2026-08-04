import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import * as THREE from "three";
import StructureViewer from "./StructureViewer";

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
  is_placeholder?: boolean;
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
  mmonca_found?: boolean;
  mmonca_path?: string;
  mmonca_message?: string;
};
type JobInfo = {
  id: string;
  status: string;
  project_name: string;
  material_id: string;
  potential_id: string;
  scenario_id: string;
  created_at: string;
  updated_at: string;
  message: string;
  run_params: RunParams;
  run_kart_anneal: boolean;
  run_mmonca_okmc?: boolean;
  defect_summary?: Record<string, number | string | object>;
  kart_summary?: Record<string, unknown>;
  mmonca_summary?: Record<string, unknown>;
  surface_summary?: Record<string, unknown>;
};
type RunParams = {
  mode: string;
  nx: number;
  ny: number;
  nz: number;
  boundary: string;
  crystal_orient: string;
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
  vacuum_layers: number;
  surface_fluence_ions: number;
  timestep_fs: number;
  max_steps: number;
  neighbor_skin: number;
  thermo_every: number;
  dump_every: number;
  dump_style: string;
  restart_every: number;
  ws_lattice_A: number | null;
  cluster_cutoff_A: number;
  confirm_large: boolean;
};

type TabId = "projects" | "material" | "potential" | "scenario" | "params" | "run" | "results" | "engines";

const TABS: { id: TabId; step: string; label: string }[] = [
  { id: "projects", step: "01", label: "Projects" },
  { id: "material", step: "02", label: "Material" },
  { id: "potential", step: "03", label: "Potential" },
  { id: "scenario", step: "04", label: "Scenario" },
  { id: "params", step: "05", label: "LAMMPS" },
  { id: "run", step: "06", label: "Run" },
  { id: "results", step: "07", label: "Results" },
  { id: "engines", step: "08", label: "Engines" },
];

const PAIR_STYLE_WHITELIST = [
  "eam",
  "eam/alloy",
  "eam/fs",
  "meam",
  "snap",
  "table",
  "hybrid",
  "hybrid/overlay",
];

const defaultParams: RunParams = {
  mode: "cascade",
  nx: 8,
  ny: 8,
  nz: 8,
  boundary: "p p p",
  crystal_orient: "100",
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
  vacuum_layers: 4,
  surface_fluence_ions: 1,
  timestep_fs: 0.001,
  max_steps: 20000,
  neighbor_skin: 2,
  thermo_every: 100,
  dump_every: 1000,
  dump_style: "custom",
  restart_every: 0,
  ws_lattice_A: null,
  cluster_cutoff_A: 3.5,
  confirm_large: false,
};

function formatApiError(payload: unknown, fallback: string): string {
  if (typeof payload === "string") return payload || fallback;
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) => {
        if (!item || typeof item !== "object") return String(item);
        const issue = item as { loc?: Array<string | number>; msg?: string };
        const path = issue.loc?.filter((part) => part !== "body").join(" → ");
        return `${path ? `${path}: ` : ""}${issue.msg || "Invalid value"}`;
      })
      .join(" · ");
  }
  return fallback;
}

async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init);
  if (!res.ok) {
    const text = await res.text();
    let payload: unknown = text;
    try {
      payload = JSON.parse(text);
    } catch {
      /* Plain-text response. */
    }
    throw new Error(formatApiError(payload, `${res.status} ${res.statusText}`));
  }
  return res.json() as Promise<T>;
}

function normalizeComposition(rows: ElementFraction[]): ElementFraction[] {
  const total = rows.reduce((sum, row) => sum + Math.max(0, Number(row.atomic_percent) || 0), 0);
  if (total <= 0) throw new Error("Composition must contain a positive atomic fraction.");
  return rows.map((row) => ({
    symbol: row.symbol.trim(),
    atomic_percent: (Math.max(0, Number(row.atomic_percent) || 0) / total) * 100,
  }));
}

const ATOMIC_MASS: Record<string, number> = {
  H: 1.008,
  D: 2.014,
  He: 4.0026,
  C: 12.011,
  V: 50.942,
  Cr: 51.996,
  Fe: 55.845,
  Mo: 95.95,
  Ta: 180.95,
  W: 183.84,
  Re: 186.21,
};

function massOf(symbol: string): number {
  return ATOMIC_MASS[symbol.trim()] || 1;
}

/** Convert stored at% rows into editable wt% display values. */
function atToWt(rows: ElementFraction[]): number[] {
  const masses = rows.map((r) => (Number(r.atomic_percent) || 0) * massOf(r.symbol));
  const total = masses.reduce((s, m) => s + m, 0) || 1;
  return masses.map((m) => (m / total) * 100);
}

/** Apply an edited wt% value at index and return new at% composition. */
function wtEditToAt(rows: ElementFraction[], idx: number, wtValue: number): ElementFraction[] {
  const wts = atToWt(rows);
  wts[idx] = Math.max(0, wtValue);
  const moles = rows.map((r, i) => wts[i] / massOf(r.symbol));
  const total = moles.reduce((s, m) => s + m, 0) || 1;
  return rows.map((r, i) => ({
    symbol: r.symbol,
    atomic_percent: (moles[i] / total) * 100,
  }));
}

function Field({
  label,
  unit,
  children,
  htmlFor,
}: {
  label: string;
  unit?: string;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <label htmlFor={htmlFor}>
      <span>
        {label}
        {unit ? <span className="unit"> · {unit}</span> : null}
      </span>
      {children}
    </label>
  );
}

function DefectViz({ points }: { points: Array<{ x: number; y: number; z: number; kind: string }> }) {
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!ref.current) return;
    const el = ref.current;
    const scene = new THREE.Scene();
    scene.background = new THREE.Color(0x07090d);
    const camera = new THREE.PerspectiveCamera(45, el.clientWidth / Math.max(el.clientHeight, 1), 0.1, 1000);
    camera.position.set(12, 10, 16);
    camera.lookAt(0, 0, 0);
    const renderer = new THREE.WebGLRenderer({ antialias: true });
    renderer.setSize(el.clientWidth, el.clientHeight);
    el.appendChild(renderer.domElement);
    const light = new THREE.DirectionalLight(0xffffff, 1.05);
    light.position.set(5, 10, 7);
    scene.add(light);
    scene.add(new THREE.AmbientLight(0x6688aa, 0.35));

    const group = new THREE.Group();
    for (const p of points.slice(0, 2000)) {
      const color = p.kind === "vacancy" ? 0xd46555 : p.kind === "interstitial" ? 0xd4894a : 0x3d9a6a;
      const geo = new THREE.SphereGeometry(0.12, 10, 10);
      const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.45, metalness: 0.2 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.position.set(p.x - 4, p.y - 4, p.z - 4);
      group.add(mesh);
    }
    scene.add(group);
    let frame = 0;
    let alive = true;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const animate = () => {
      if (!alive) return;
      frame = requestAnimationFrame(animate);
      if (!reduce) group.rotation.y += 0.004;
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
  return <div className="viz" ref={ref} role="img" aria-label="3D defect point cloud" />;
}

type KartEvent = { event: number; barrier_eV: number; time_s?: number; source?: string };
type KartRun = {
  temperature_K: number;
  status: string;
  message?: string;
  events?: KartEvent[];
  handoff?: string;
};
type KartSummary = {
  status?: string;
  message?: string;
  doe?: boolean;
  temperatures_K?: number[];
  events?: KartEvent[];
  runs?: KartRun[];
  handoff?: string;
};

function KartTimeline({ events, label }: { events: KartEvent[]; label: string }) {
  if (!events.length) {
    return <p className="hint">No anneal events yet.</p>;
  }
  const maxB = Math.max(...events.map((e) => e.barrier_eV), 0.1);
  return (
    <div className="stack">
      <p className="hint">{label}</p>
      <div className="kart-timeline" role="img" aria-label="KART barrier timeline">
        {events.slice(0, 60).map((e) => (
          <div
            key={e.event}
            className="kart-bar"
            style={{ height: `${(e.barrier_eV / maxB) * 100}%` }}
            title={`#${e.event} · ${e.barrier_eV.toFixed(3)} eV · t=${e.time_s ?? "—"}`}
          />
        ))}
      </div>
      <div className="chip-row">
        <span className="chip">
          <span className="chip-k">events</span>
          <span className="chip-v">{events.length}</span>
        </span>
        <span className="chip">
          <span className="chip-k">Ē_bar</span>
          <span className="chip-v">
            {(events.reduce((s, e) => s + e.barrier_eV, 0) / events.length).toFixed(3)} eV
          </span>
        </span>
      </div>
    </div>
  );
}

export default function App() {
  const [tab, setTab] = useState<TabId>("projects");
  const [materials, setMaterials] = useState<Material[]>([]);
  const [potentials, setPotentials] = useState<Potential[]>([]);
  const [scenarios, setScenarios] = useState<Scenario[]>([]);
  const [engines, setEngines] = useState<EngineStatus | null>(null);
  const [materialId, setMaterialId] = useState("w-pure");
  const [composition, setComposition] = useState<ElementFraction[]>([{ symbol: "W", atomic_percent: 100 }]);
  const [lattice, setLattice] = useState(3.165);
  const [potentialId, setPotentialId] = useState("");
  const [scenarioId, setScenarioId] = useState("dt-divertor");
  const [params, setParams] = useState<RunParams>(defaultParams);
  const [projectName, setProjectName] = useState("W-He study");
  const [runKart, setRunKart] = useState(false);
  const [runMmonca, setRunMmonca] = useState(false);
  const [kartTemperatureK, setKartTemperatureK] = useState(600);
  const [kartMaxEvents, setKartMaxEvents] = useState(1000);
  const [kartMaxWallS, setKartMaxWallS] = useState(600);
  const [kartMaxKmcTimeS, setKartMaxKmcTimeS] = useState(1);
  const [kartDoeTemps, setKartDoeTemps] = useState("");
  const [kartSummary, setKartSummary] = useState<KartSummary | null>(null);
  const [job, setJob] = useState<JobInfo | null>(null);
  const [jobs, setJobs] = useState<JobInfo[]>([]);
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
  const [uploadPairStyle, setUploadPairStyle] = useState("eam/alloy");
  const [busy, setBusy] = useState(false);
  const [compUnit, setCompUnit] = useState<"at%" | "wt%">("at%");
  const [projectFilter, setProjectFilter] = useState<string>("");

  const material = useMemo(() => materials.find((m) => m.id === materialId), [materials, materialId]);
  const selectedPot = useMemo(() => potentials.find((p) => p.id === potentialId), [potentials, potentialId]);
  const scenario = useMemo(() => scenarios.find((s) => s.id === scenarioId), [scenarios, scenarioId]);
  const projectNames = useMemo(() => {
    const names = new Set<string>();
    for (const j of jobs) {
      if (j.project_name) names.add(j.project_name);
    }
    if (projectName) names.add(projectName);
    return Array.from(names).sort((a, b) => a.localeCompare(b));
  }, [jobs, projectName]);
  const projectJobs = useMemo(() => {
    const key = projectFilter || projectName;
    if (!key) return jobs;
    return jobs.filter((j) => j.project_name === key);
  }, [jobs, projectFilter, projectName]);

  const compositionTotal = composition.reduce((s, e) => s + Number(e.atomic_percent || 0), 0);
  const cellVolume = params.nx * params.ny * params.nz;
  const largeCell = cellVolume > 20 * 20 * 20;
  const potIsDemo = Boolean(selectedPot?.is_placeholder);

  const blockers = useMemo(() => {
    const list: string[] = [];
    if (!potentialId) list.push("Select a potential");
    if (selectedPot && !selectedPot.available && !selectedPot.is_placeholder) {
      list.push("Potential file missing — upload or place under data/potentials/curated/");
    }
    if (compositionTotal <= 0) list.push("Composition requires a positive atomic fraction");
    if (largeCell && !params.confirm_large) list.push("Large cell (>20³) — confirm in LAMMPS tab");
    if (material?.metadata_only) list.push("Material is metadata-only (no runnable lattice recipe)");
    return list;
  }, [potentialId, selectedPot, compositionTotal, largeCell, params.confirm_large, material]);

  const verdict = blockers.length
    ? { tone: "blocked" as const, label: "Blocked", msg: blockers[0] }
    : potIsDemo || !engines?.lammps_found
      ? {
          tone: "warn" as const,
          label: "Ready · dry-run",
          msg: potIsDemo
            ? "Placeholder potential — demo dumps only. Upload a published potential for real MD."
            : "LAMMPS not on PATH — job will write demo dumps for pipeline testing.",
        }
      : { tone: "ready" as const, label: "Ready", msg: "Material, potential, and parameters look runnable." };

  useEffect(() => {
    Promise.all([
      api<{ status: string }>("/api/health"),
      api<Material[]>("/api/materials"),
      api<Scenario[]>("/api/scenarios"),
      api<EngineStatus>("/api/engines/status"),
      api<JobInfo[]>("/api/jobs"),
    ])
      .then(([, m, s, e, history]) => {
        setMaterials(m);
        setScenarios(s);
        setEngines(e);
        setJobs(history);
        const first = m.find((x) => x.id === "w-pure") || m[0];
        if (first) {
          setMaterialId(first.id);
          setComposition(first.composition);
          setLattice(first.lattice_constant_A);
        }
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, []);

  useEffect(() => {
    if (!materialId) return;
    api<Potential[]>(`/api/potentials?material_id=${materialId}`)
      .then((p) => {
        setPotentials(p);
        const avail = p.find((x) => x.available) || p.find((x) => x.is_placeholder) || p[0];
        setPotentialId(avail?.id || "");
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [materialId]);

  useEffect(() => {
    const sc = scenarios.find((s) => s.id === scenarioId);
    if (!sc) return;
    setParams((prev) => ({ ...prev, ...sc.defaults }) as RunParams);
  }, [scenarioId, scenarios]);

  useEffect(() => {
    if (tab !== "engines") return;
    api<EngineStatus>("/api/engines/status")
      .then(setEngines)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }, [tab]);

  useEffect(() => {
    if (!job) return;
    const wsProto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${wsProto}://${location.host}/api/jobs/${job.id}/log`);
    ws.onmessage = (ev) => setLog((prev) => prev + ev.data);
    const timer = setInterval(async () => {
      try {
        const info = await api<JobInfo>(`/api/jobs/${job.id}`);
        setJob(info);
        setJobs((history) => [info, ...history.filter((item) => item.id !== info.id)]);
        if (["completed", "failed", "cancelled"].includes(info.status)) {
          clearInterval(timer);
          if (info.status === "completed") {
            const d = await api<typeof defects>(`/api/jobs/${job.id}/defects`);
            setDefects(d);
            try {
              setKartSummary(await api<KartSummary>(`/api/jobs/${job.id}/kart`));
            } catch {
              setKartSummary((info.kart_summary as KartSummary) || null);
            }
            setTab("results");
          }
        }
      } catch {
        /* ignore */
      }
    }, 1000);
    return () => {
      ws.close();
      clearInterval(timer);
    };
  }, [job?.id]);

  async function loadJob(jobId: string) {
    if (!jobId) return;
    setBusy(true);
    setError("");
    setLog("");
    setDefects(null);
    setKartSummary(null);
    try {
      const info = await api<JobInfo>(`/api/jobs/${jobId}`);
      setJob(info);
      if (info.status === "completed") {
        setDefects(await api<NonNullable<typeof defects>>(`/api/jobs/${jobId}/defects`));
        try {
          setKartSummary(await api<KartSummary>(`/api/jobs/${jobId}/kart`));
        } catch {
          setKartSummary((info.kart_summary as KartSummary) || null);
        }
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function setParam<K extends keyof RunParams>(key: K, value: RunParams[K]) {
    setParams((p) => ({ ...p, [key]: value }));
  }

  async function saveComposition() {
    if (!material) return;
    setBusy(true);
    setError("");
    try {
      const normalized = normalizeComposition(composition);
      const updated = await api<Material>(`/api/materials/${material.id}`, {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ composition: normalized, lattice_constant_A: lattice }),
      });
      setComposition(updated.composition);
      setMaterials((ms) => ms.map((m) => (m.id === updated.id ? updated : m)));
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
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
        formalism: uploadPairStyle.startsWith("eam")
          ? uploadPairStyle
          : uploadPairStyle === "meam"
            ? "meam"
            : uploadPairStyle === "snap"
              ? "snap"
              : uploadPairStyle === "table"
                ? "table"
                : "other",
        elements: uploadElements.split(/[\s,]+/).filter(Boolean),
        lammps_pair_style: uploadPairStyle,
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
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function runJob() {
    if (blockers.length) {
      setError(blockers.join(" · "));
      return;
    }
    setBusy(true);
    setError("");
    setLog("");
    setDefects(null);
    setKartSummary(null);
    try {
      const normalized = normalizeComposition(composition);
      setComposition(normalized);
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
        kart_temperature_K: kartTemperatureK,
        kart_max_events: kartMaxEvents,
        kart_max_wall_s: kartMaxWallS,
        kart_max_kmc_time_s: kartMaxKmcTimeS,
        kart_anneal_temperatures: (() => {
          const doe = kartDoeTemps
            .split(/[\s,]+/)
            .map((x) => Number(x))
            .filter((x) => Number.isFinite(x) && x > 0);
          return doe.length ? doe : null;
        })(),
        run_mmonca_okmc: runMmonca,
        mmonca_temperature_K: kartTemperatureK,
        mmonca_max_events: kartMaxEvents,
      };
      const info = await api<JobInfo>("/api/jobs", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      setJob(info);
      setJobs((history) => [info, ...history.filter((item) => item.id !== info.id)]);
      setTab("run");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  async function cancelJob() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const cancelled = await api<JobInfo>(`/api/jobs/${job.id}/cancel`, { method: "POST" });
      setJob(cancelled);
      setJobs((history) => [cancelled, ...history.filter((item) => item.id !== cancelled.id)]);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  function exportDefects() {
    if (!defects || !job) return;
    const blob = new Blob([JSON.stringify(defects, null, 2)], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `aegis-${job.id}-defects.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function reannealDoe() {
    if (!job) return;
    setBusy(true);
    setError("");
    try {
      const doe = kartDoeTemps
        .split(/[\s,]+/)
        .map((x) => Number(x))
        .filter((x) => Number.isFinite(x) && x > 0);
      const summary = await api<KartSummary>(`/api/jobs/${job.id}/kart/anneal`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          temperature_K: kartTemperatureK,
          max_events: kartMaxEvents,
          max_wall_s: kartMaxWallS,
          max_kmc_time_s: kartMaxKmcTimeS,
          temperatures: doe.length ? doe : [kartTemperatureK],
        }),
      });
      setKartSummary(summary);
      const info = await api<JobInfo>(`/api/jobs/${job.id}`);
      setJob(info);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  }

  const clusterSizes = defects?.clusters?.map((c) => c.size) || [];
  const maxCluster = Math.max(1, ...clusterSizes);

  return (
    <div className="shell">
      <a className="skip-link" href="#main">
        Skip to main content
      </a>

      <header className="topbar">
        <div className="brand-block">
          <p className="eyebrow">PFM radiation damage workbench</p>
          <h1 className="brand">Aegis</h1>
          <p className="brand-sub">
            Cascade MD → defect analysis → optional k-ART. D–D / D–T are scenario presets, not plasma transport.
          </p>
        </div>
        <div className="kpi-row" aria-label="Engine status">
          <div className="kpi">
            <span className="kpi-k">LAMMPS</span>
            <span className={`kpi-v ${engines?.lammps_found ? "tone-ok" : "tone-warn"}`}>
              {engines?.lammps_found ? "found" : "dry-run"}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-k">KART</span>
            <span className={`kpi-v ${engines?.kart_found ? "tone-ok" : "tone-warn"}`}>
              {engines?.kart_found ? "found" : "stub"}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-k">Cell</span>
            <span className="kpi-v">
              {params.nx}×{params.ny}×{params.nz}
            </span>
          </div>
          <div className="kpi">
            <span className="kpi-k">Job</span>
            <span className="kpi-v">{job?.status || "idle"}</span>
          </div>
          <button
            type="button"
            className="primary-run"
            disabled={busy || blockers.length > 0}
            onClick={runJob}
            aria-label="Queue LAMMPS job"
          >
            {busy ? "Working…" : "Run job"}
          </button>
        </div>
      </header>

      <div className="verdict" role="status" aria-live="polite">
        <span className={`verdict-badge ${verdict.tone}`}>{verdict.label}</span>
        <span className="verdict-msg">{verdict.msg}</span>
        {blockers.length > 1 && (
          <span className="chip">
            <span className="chip-k">+</span>
            <span className="chip-v">{blockers.length - 1} more</span>
          </span>
        )}
      </div>

      <aside className="rail" aria-label="Workflow">
        <nav>
          {TABS.map((t) => (
            <button
              key={t.id}
              type="button"
              className={tab === t.id ? "active" : ""}
              onClick={() => setTab(t.id)}
              aria-current={tab === t.id ? "page" : undefined}
            >
              <span className="step">{t.step}</span>
              {t.label}
            </button>
          ))}
        </nav>
      </aside>

      <main id="main" className="main">
        {error && (
          <div className="alert alert-fail" role="alert">
            {error}
          </div>
        )}

        {tab === "projects" && (
          <section className="panel stack">
            <div className="panel-head">
              <h2>Projects</h2>
              <span className="chip">
                <span className="chip-k">jobs</span>
                <span className="chip-v">{jobs.length}</span>
              </span>
            </div>
            <p className="hint">
              Group runs by study name. Opening a job loads its status, log, and results without changing the current recipe
              until you re-run.
            </p>
            <div className="row">
              <Field label="Active project" htmlFor="proj-active">
                <input
                  id="proj-active"
                  value={projectName}
                  onChange={(e) => setProjectName(e.target.value)}
                  placeholder="e.g. W-He divertor study"
                />
              </Field>
              <Field label="Filter history" htmlFor="proj-filter">
                <select
                  id="proj-filter"
                  value={projectFilter}
                  onChange={(e) => setProjectFilter(e.target.value)}
                >
                  <option value="">All projects</option>
                  {projectNames.map((n) => (
                    <option key={n} value={n}>
                      {n}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            <div className="row">
              <button
                type="button"
                className="secondary"
                onClick={() => {
                  setProjectName("untitled");
                  setProjectFilter("");
                  setJob(null);
                  setLog("");
                  setDefects(null);
                }}
              >
                New study
              </button>
              <button type="button" className="secondary" onClick={() => setTab("material")}>
                Continue to Material
              </button>
            </div>
            <h3>Job history</h3>
            {projectJobs.length === 0 ? (
              <div className="empty">
                <div className="empty-kicker">No runs yet</div>
                <h3>Start a cascade</h3>
                <p className="hint">Configure material → potential → scenario → LAMMPS, then Run.</p>
              </div>
            ) : (
              <div className="stack">
                {projectJobs.slice(0, 40).map((j) => (
                  <button
                    key={j.id}
                    type="button"
                    className={`job-row ${job?.id === j.id ? "active" : ""}`}
                    onClick={() => {
                      void loadJob(j.id);
                      setProjectName(j.project_name);
                      setTab(j.status === "completed" || j.status === "failed" ? "results" : "run");
                    }}
                  >
                    <span className="mono">{j.id}</span>
                    <span>{j.project_name}</span>
                    <span className={`chip-v status-${j.status}`}>{j.status}</span>
                    <span className="hint">{j.created_at?.slice(0, 19)?.replace("T", " ")}</span>
                  </button>
                ))}
              </div>
            )}
          </section>
        )}

        {tab === "material" && (
          <section className="panel stack">
            <div className="panel-head">
              <h2>Material</h2>
              <div className="chip-row">
                <span className="chip">
                  <span className="chip-k">crystal</span>
                  <span className="chip-v">{material?.crystal || "—"}</span>
                </span>
                <span className="chip">
                  <span className="chip-k">Σ at%</span>
                  <span className={`chip-v ${Math.abs(compositionTotal - 100) > 0.05 ? "tone-fail" : "tone-ok"}`}>
                    {compositionTotal.toFixed(2)}
                  </span>
                </span>
              </div>
            </div>
            <p className="hint">{material?.description}</p>
            {material && material.crystal.toLowerCase() !== "bcc" && (
              <div className="alert alert-warn" role="status">
                Crystal is {material.crystal}. Phase-1 LAMMPS templates always build BCC cells — results are not representative for this lattice.
              </div>
            )}
            {Math.abs(compositionTotal - 100) > 0.05 && compositionTotal > 0 && (
              <div className="alert alert-warn" role="status">
                Composition is {compositionTotal.toFixed(2)} at%. Aegis will proportionally normalize it to 100% before save or run.
              </div>
            )}
            <Field label="Preset" htmlFor="mat-preset">
              <select
                id="mat-preset"
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
            </Field>
            <div className="row">
              <h3>Composition</h3>
              <Field label="Units" htmlFor="comp-unit">
                <select
                  id="comp-unit"
                  value={compUnit}
                  onChange={(e) => setCompUnit(e.target.value as "at%" | "wt%")}
                >
                  <option value="at%">Atomic % (at%)</option>
                  <option value="wt%">Weight % (wt%)</option>
                </select>
              </Field>
            </div>
            {compUnit === "wt%" && (
              <p className="hint">Edits in wt% convert to at% using standard atomic masses; recipes always store at%.</p>
            )}
            {composition.map((row, idx) => {
              const wtValues = atToWt(composition);
              return (
              <div className="comp-row" key={idx}>
                <Field label="Element">
                  <input
                    value={row.symbol}
                    onChange={(e) => {
                      const next = [...composition];
                      next[idx] = { ...row, symbol: e.target.value };
                      setComposition(next);
                    }}
                  />
                </Field>
                <Field label={compUnit === "at%" ? "Atomic fraction" : "Weight fraction"} unit={compUnit}>
                  <input
                    type="number"
                    inputMode="decimal"
                    value={compUnit === "at%" ? row.atomic_percent : Number(wtValues[idx].toFixed(4))}
                    onChange={(e) => {
                      const v = Number(e.target.value);
                      if (compUnit === "at%") {
                        const next = [...composition];
                        next[idx] = { ...row, atomic_percent: v };
                        setComposition(next);
                      } else {
                        setComposition(wtEditToAt(composition, idx, v));
                      }
                    }}
                  />
                </Field>
                <button
                  className="secondary"
                  type="button"
                  aria-label={`Remove ${row.symbol}`}
                  onClick={() => setComposition(composition.filter((_, i) => i !== idx))}
                >
                  Remove
                </button>
              </div>
            );})}
            <div className="row">
              <button
                className="secondary"
                type="button"
                onClick={() => setComposition([...composition, { symbol: "Ta", atomic_percent: 0 }])}
              >
                Add element
              </button>
              <Field label="Lattice constant" unit="Å" htmlFor="lattice">
                <input
                  id="lattice"
                  type="number"
                  step="0.001"
                  inputMode="decimal"
                  value={lattice}
                  onChange={(e) => setLattice(Number(e.target.value))}
                />
              </Field>
            </div>
            <button type="button" disabled={busy || compositionTotal <= 0} onClick={saveComposition}>
              Normalize & save override
            </button>
          </section>
        )}

        {tab === "potential" && (
          <div className="grid-2">
            <section className="panel stack">
              <h2>Potential library</h2>
              <p className="hint">
                Aegis never invents coefficients. Curated entries need a redistributable file on disk or an upload.
              </p>
              <Field label="Compatible potentials" htmlFor="pot-select">
                <select id="pot-select" value={potentialId} onChange={(e) => setPotentialId(e.target.value)}>
                  {potentials.map((p) => (
                    <option key={p.id} value={p.id}>
                      {p.available ? "●" : p.is_placeholder ? "◇" : "○"} {p.name} [{p.source}]
                    </option>
                  ))}
                </select>
              </Field>
              {selectedPot && (
                <div className="stack">
                  <div className="chip-row">
                    <span className="chip">
                      <span className="chip-k">pair_style</span>
                      <span className="chip-v">{selectedPot.lammps_pair_style}</span>
                    </span>
                    <span className="chip">
                      <span className="chip-k">elements</span>
                      <span className="chip-v">{selectedPot.elements.join(" ")}</span>
                    </span>
                    <span className="chip">
                      <span className="chip-k">file</span>
                      <span
                        className={`chip-v ${
                          selectedPot.available ? "tone-ok" : selectedPot.is_placeholder ? "tone-warn" : "tone-fail"
                        }`}
                      >
                        {selectedPot.available
                          ? "on disk"
                          : selectedPot.is_placeholder
                            ? "placeholder"
                            : "missing"}
                      </span>
                    </span>
                  </div>
                  {selectedPot.recommended_for?.length > 0 && (
                    <p className="hint">Tags: {selectedPot.recommended_for.join(", ")}</p>
                  )}
                  {selectedPot.warnings?.map((w) => (
                    <div key={w} className="alert alert-warn">
                      {w}
                    </div>
                  ))}
                  {selectedPot.is_placeholder && (
                    <div className="alert alert-warn" role="status">
                      Demo placeholder — jobs use dry-run dumps. Upload a published potential for real LAMMPS MD.
                    </div>
                  )}
                  {!selectedPot.available && !selectedPot.is_placeholder && (
                    <div className="alert alert-fail" role="alert">
                      Unavailable for MD: place the potential file on disk or upload one.
                    </div>
                  )}
                </div>
              )}
            </section>
            <section className="panel stack">
              <h2>Upload local potential</h2>
              <Field label="Display name" htmlFor="up-name">
                <input id="up-name" value={uploadName} onChange={(e) => setUploadName(e.target.value)} />
              </Field>
              <Field label="Elements" unit="space-separated" htmlFor="up-el">
                <input id="up-el" value={uploadElements} onChange={(e) => setUploadElements(e.target.value)} />
              </Field>
              <Field label="LAMMPS pair_style" htmlFor="up-style">
                <select
                  id="up-style"
                  value={uploadPairStyle}
                  onChange={(e) => setUploadPairStyle(e.target.value)}
                >
                  {PAIR_STYLE_WHITELIST.map((s) => (
                    <option key={s} value={s}>
                      {s}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Potential file" htmlFor="up-file">
                <input
                  id="up-file"
                  type="file"
                  accept=".eam,.alloy,.fs,.meam,.snap,.table,.dat,.txt"
                  onChange={(e) => setUploadFile(e.target.files?.[0] || null)}
                />
              </Field>
              <button type="button" disabled={busy || !uploadFile} onClick={uploadPotential}>
                Upload potential
              </button>
            </section>
          </div>
        )}

        {tab === "scenario" && (
          <section className="panel stack">
            <h2>Irradiation scenario</h2>
            <p className="hint">
              Fuel choices set default PKA/He energies and temperature. They are not a tokamak transport model.
            </p>
            <div className="row">
              <Field label="Fuel preset" htmlFor="scenario">
                <select id="scenario" value={scenarioId} onChange={(e) => setScenarioId(e.target.value)}>
                  {scenarios.map((s) => (
                    <option key={s.id} value={s.id}>
                      {s.label} ({s.fuel})
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="Project name" htmlFor="proj">
                <input id="proj" value={projectName} onChange={(e) => setProjectName(e.target.value)} />
              </Field>
            </div>
            <p className="hint">{scenario?.description}</p>
            {scenario && (
              <div className="chip-row">
                {Object.entries(scenario.defaults)
                  .slice(0, 8)
                  .map(([k, v]) => (
                    <span className="chip" key={k}>
                      <span className="chip-k">{k}</span>
                      <span className="chip-v">{String(v)}</span>
                    </span>
                  ))}
              </div>
            )}
          </section>
        )}

        {tab === "params" && (
          <section className="panel stack">
            <div className="panel-head">
              <h2>LAMMPS parameters</h2>
              <span className="chip">
                <span className="chip-k">atoms proxy</span>
                <span className="chip-v">~{cellVolume * 2} BCC sites</span>
              </span>
            </div>
            <fieldset className="fieldset">
              <legend>Mode & thermostat</legend>
              <div className="row">
                <Field label="Mode" htmlFor="mode">
                  <select id="mode" value={params.mode} onChange={(e) => setParam("mode", e.target.value)}>
                    <option value="cascade">cascade / PKA</option>
                    <option value="implant">ion implant (bulk)</option>
                    <option value="surface">low-E surface (fuzz proxy)</option>
                  </select>
                </Field>
                <Field label="Temperature" unit="K" htmlFor="T">
                  <input
                    id="T"
                    type="number"
                    inputMode="decimal"
                    value={params.temperature_K}
                    onChange={(e) => setParam("temperature_K", Number(e.target.value))}
                  />
                </Field>
                <Field label="Ensemble" htmlFor="ensemble">
                  <select
                    id="ensemble"
                    value={params.ensemble}
                    onChange={(e) => setParam("ensemble", e.target.value)}
                  >
                    <option value="nve">NVE</option>
                    <option value="nvt">NVT</option>
                  </select>
                </Field>
                <Field label="Thermostat damping" unit="ps" htmlFor="damp">
                  <input
                    id="damp"
                    type="number"
                    step="0.01"
                    value={params.damp_ps}
                    onChange={(e) => setParam("damp_ps", Number(e.target.value))}
                  />
                </Field>
                <Field label="Seed" htmlFor="seed">
                  <input
                    id="seed"
                    type="number"
                    inputMode="numeric"
                    value={params.seed}
                    onChange={(e) => setParam("seed", Number(e.target.value))}
                  />
                </Field>
              </div>
            </fieldset>
            <fieldset className="fieldset">
              <legend>System</legend>
              <div className="row">
                {(["nx", "ny", "nz"] as const).map((k) => (
                  <Field key={k} label={k} unit="unit cells" htmlFor={k}>
                    <input
                      id={k}
                      type="number"
                      inputMode="numeric"
                      value={params[k]}
                      onChange={(e) => setParam(k, Number(e.target.value))}
                    />
                  </Field>
                ))}
                <Field label="Boundary" htmlFor="boundary">
                  <input
                    id="boundary"
                    value={params.boundary}
                    onChange={(e) => setParam("boundary", e.target.value)}
                  />
                </Field>
                <Field label="Crystal orientation" unit="x-axis" htmlFor="orient">
                  <select
                    id="orient"
                    value={params.crystal_orient}
                    onChange={(e) => setParam("crystal_orient", e.target.value)}
                  >
                    <option value="100">[100]</option>
                    <option value="110">[110]</option>
                    <option value="111">[111]</option>
                  </select>
                </Field>
              </div>
            </fieldset>
            <fieldset className="fieldset">
              <legend>Cascade / PKA</legend>
              <div className="row">
                <Field label="PKA species" htmlFor="pka-sp">
                  <input
                    id="pka-sp"
                    value={params.pka_species}
                    onChange={(e) => setParam("pka_species", e.target.value)}
                  />
                </Field>
                <Field label="Energy" unit="eV" htmlFor="pka-e">
                  <>
                    <input
                      id="pka-e"
                      type="number"
                      inputMode="decimal"
                      value={params.pka_energy_eV}
                      onChange={(e) => setParam("pka_energy_eV", Number(e.target.value))}
                    />
                    <span className="field-helper">{(params.pka_energy_eV / 1000).toLocaleString()} keV</span>
                  </>
                </Field>
                <Field label="Direction" unit="random | h k l" htmlFor="pka-d">
                  <input
                    id="pka-d"
                    value={params.pka_direction}
                    onChange={(e) => setParam("pka_direction", e.target.value)}
                  />
                </Field>
                <Field label="# PKAs" htmlFor="n-pka">
                  <input
                    id="n-pka"
                    type="number"
                    inputMode="numeric"
                    value={params.n_pkas}
                    onChange={(e) => setParam("n_pkas", Number(e.target.value))}
                  />
                </Field>
                <Field label="PKA delay" unit="steps" htmlFor="pka-delay">
                  <input
                    id="pka-delay"
                    type="number"
                    value={params.pka_delay_steps}
                    onChange={(e) => setParam("pka_delay_steps", Number(e.target.value))}
                  />
                </Field>
              </div>
            </fieldset>
            <fieldset className="fieldset">
              <legend>Implant</legend>
              <div className="row">
                <Field label="Ion" htmlFor="ion">
                  <input id="ion" value={params.ion_type} onChange={(e) => setParam("ion_type", e.target.value)} />
                </Field>
                <Field label="Ion energy" unit="eV" htmlFor="ion-e">
                  <input
                    id="ion-e"
                    type="number"
                    inputMode="decimal"
                    value={params.ion_energy_eV}
                    onChange={(e) => setParam("ion_energy_eV", Number(e.target.value))}
                  />
                </Field>
                <Field label="Ion count" htmlFor="ion-n">
                  <input
                    id="ion-n"
                    type="number"
                    inputMode="numeric"
                    value={params.ion_count}
                    onChange={(e) => setParam("ion_count", Number(e.target.value))}
                  />
                </Field>
                <Field label="Incidence angle" unit="deg" htmlFor="ion-angle">
                  <input
                    id="ion-angle"
                    type="number"
                    step="0.1"
                    value={params.ion_angle_deg}
                    onChange={(e) => setParam("ion_angle_deg", Number(e.target.value))}
                  />
                </Field>
              </div>
            </fieldset>
            {params.mode === "surface" && (
              <fieldset className="fieldset">
                <legend>Surface MD (Phase-3)</legend>
                <p className="hint">
                  Free-surface slab with vacuum; low-E He/D fluence is a discrete ion-count proxy — not a plasma sheath.
                </p>
                <div className="row">
                  <Field label="Vacuum layers" unit="lattice" htmlFor="vac-layers">
                    <input
                      id="vac-layers"
                      type="number"
                      value={params.vacuum_layers}
                      onChange={(e) => setParam("vacuum_layers", Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Surface fluence" unit="ions" htmlFor="surf-flu">
                    <input
                      id="surf-flu"
                      type="number"
                      value={params.surface_fluence_ions}
                      onChange={(e) => setParam("surface_fluence_ions", Number(e.target.value))}
                    />
                  </Field>
                </div>
              </fieldset>
            )}
            <details className="advanced">
              <summary>Advanced dynamics & output</summary>
              <div className="row" style={{ marginTop: "0.75rem" }}>
                <Field label="Timestep" unit="fs" htmlFor="dt">
                  <input
                    id="dt"
                    type="number"
                    step="0.0001"
                    value={params.timestep_fs}
                    onChange={(e) => setParam("timestep_fs", Number(e.target.value))}
                  />
                </Field>
                <Field label="Max steps" htmlFor="steps">
                  <input
                    id="steps"
                    type="number"
                    value={params.max_steps}
                    onChange={(e) => setParam("max_steps", Number(e.target.value))}
                  />
                </Field>
                <Field label="Thermo every" htmlFor="thermo">
                  <input
                    id="thermo"
                    type="number"
                    value={params.thermo_every}
                    onChange={(e) => setParam("thermo_every", Number(e.target.value))}
                  />
                </Field>
                <Field label="Dump every" htmlFor="dump">
                  <input
                    id="dump"
                    type="number"
                    value={params.dump_every}
                    onChange={(e) => setParam("dump_every", Number(e.target.value))}
                  />
                </Field>
                <Field label="Neighbor skin" unit="Å" htmlFor="skin">
                  <input
                    id="skin"
                    type="number"
                    step="0.1"
                    value={params.neighbor_skin}
                    onChange={(e) => setParam("neighbor_skin", Number(e.target.value))}
                  />
                </Field>
                <Field label="Dump style" htmlFor="dump-style">
                  <input
                    id="dump-style"
                    value={params.dump_style}
                    onChange={(e) => setParam("dump_style", e.target.value)}
                  />
                </Field>
                <Field label="Restart every" unit="steps · 0 disables" htmlFor="restart">
                  <input
                    id="restart"
                    type="number"
                    value={params.restart_every}
                    onChange={(e) => setParam("restart_every", Number(e.target.value))}
                  />
                </Field>
                <Field label="Wigner–Seitz lattice" unit="Å · blank = material" htmlFor="ws-lattice">
                  <input
                    id="ws-lattice"
                    type="number"
                    step="0.001"
                    value={params.ws_lattice_A ?? ""}
                    onChange={(e) =>
                      setParam("ws_lattice_A", e.target.value === "" ? null : Number(e.target.value))
                    }
                  />
                </Field>
                <Field label="Cluster cutoff" unit="Å" htmlFor="cut">
                  <input
                    id="cut"
                    type="number"
                    step="0.1"
                    value={params.cluster_cutoff_A}
                    onChange={(e) => setParam("cluster_cutoff_A", Number(e.target.value))}
                  />
                </Field>
              </div>
            </details>
            <label className="check-row">
              <input
                type="checkbox"
                checked={params.confirm_large}
                onChange={(e) => setParam("confirm_large", e.target.checked)}
              />
              Confirm large cell (&gt;20³ unit cells)
            </label>
            <label className="check-row">
              <input type="checkbox" checked={runKart} onChange={(e) => setRunKart(e.target.checked)} />
              Queue KART anneal after MD
              {!engines?.kart_found && <span className="unit"> · will stub if binary missing</span>}
            </label>
            <label className="check-row">
              <input type="checkbox" checked={runMmonca} onChange={(e) => setRunMmonca(e.target.checked)} />
              Queue MMonCa OKMC (optional comparison)
              {!engines?.mmonca_found && <span className="unit"> · stubs if binary missing</span>}
            </label>
            {runKart && (
              <fieldset className="fieldset">
                <legend>k-ART anneal (Phase-2)</legend>
                <div className="row">
                  <Field label="Anneal temperature" unit="K" htmlFor="kart-temperature">
                    <input
                      id="kart-temperature"
                      type="number"
                      value={kartTemperatureK}
                      onChange={(e) => setKartTemperatureK(Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Maximum events" htmlFor="kart-events">
                    <input
                      id="kart-events"
                      type="number"
                      value={kartMaxEvents}
                      onChange={(e) => setKartMaxEvents(Number(e.target.value))}
                    />
                  </Field>
                </div>
                <div className="row">
                  <Field label="Wall-clock limit" unit="s" htmlFor="kart-wall">
                    <input
                      id="kart-wall"
                      type="number"
                      value={kartMaxWallS}
                      onChange={(e) => setKartMaxWallS(Number(e.target.value))}
                    />
                  </Field>
                  <Field label="Max KMC time" unit="s" htmlFor="kart-kmc-t">
                    <input
                      id="kart-kmc-t"
                      type="number"
                      step="0.001"
                      value={kartMaxKmcTimeS}
                      onChange={(e) => setKartMaxKmcTimeS(Number(e.target.value))}
                    />
                  </Field>
                </div>
                <Field label="DOE temperatures" unit="optional, comma-separated K" htmlFor="kart-doe">
                  <input
                    id="kart-doe"
                    placeholder="e.g. 400, 600, 800"
                    value={kartDoeTemps}
                    onChange={(e) => setKartDoeTemps(e.target.value)}
                  />
                </Field>
                <p className="hint">
                  DOE runs multiple anneals on the same cascade. Aegis writes a kart_work/T* handoff package per
                  temperature (initial.conf, conf.lammps, KMC.sh.aegis).
                </p>
              </fieldset>
            )}
            <button type="button" disabled={busy || blockers.length > 0} onClick={runJob}>
              Run job
            </button>
          </section>
        )}

        {tab === "run" && (
          <section className="panel stack">
            <div className="panel-head">
              <h2>Run console</h2>
              <Field label="Job history" htmlFor="job-history">
                <select
                  id="job-history"
                  value={job?.id || ""}
                  onChange={(e) => void loadJob(e.target.value)}
                >
                  <option value="">Select past job…</option>
                  {jobs.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.project_name} · {item.status} · {item.id.slice(0, 8)}
                    </option>
                  ))}
                </select>
              </Field>
            </div>
            {job ? (
              <>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">id</span>
                    <span className="chip-v">{job.id}</span>
                  </span>
                  <span className="chip">
                    <span className="chip-k">status</span>
                    <span className="chip-v">{job.status}</span>
                  </span>
                  <span className="chip">
                    <span className="chip-k">msg</span>
                    <span className="chip-v">{job.message}</span>
                  </span>
                </div>
                <div className="log" aria-live="polite">
                  {log || "Waiting for log…"}
                </div>
                <button
                  className="secondary"
                  type="button"
                  disabled={busy || ["completed", "failed", "cancelled"].includes(job.status)}
                  onClick={() => void cancelJob()}
                >
                  Cancel job
                </button>
              </>
            ) : (
              <div className="empty">
                <div className="empty-kicker">No active job</div>
                <h3>Queue a cascade or implant</h3>
                <p className="hint">Configure material → potential → scenario → LAMMPS, then Run.</p>
                <ol>
                  <li>Pick a potential with a file on disk</li>
                  <li>Review cell size and PKA/He energy</li>
                  <li>Use the top-bar Run job control</li>
                </ol>
              </div>
            )}
          </section>
        )}

        {tab === "results" && (
          <div className="stack">
            <section className="panel">
              <StructureViewer jobId={job?.id || null} refreshKey={job?.updated_at || job?.status} />
            </section>
          <div className="grid-2">
            <section className="panel stack">
              <div className="panel-head">
                <h2>Defect summary</h2>
                <button type="button" className="secondary" disabled={!defects} onClick={exportDefects}>
                  Export defects JSON
                </button>
              </div>
              <div className="alert alert-warn">
                SIA/vacancy counts use a Wigner–Seitz proxy. Validate production conclusions against the trajectory,
                reference lattice, and a domain-standard analysis workflow.
              </div>
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
                <div className="empty">
                  <div className="empty-kicker">Awaiting analysis</div>
                  <h3>No defect products yet</h3>
                  <p className="hint">Complete a run to populate Wigner–Seitz proxy metrics.</p>
                </div>
              )}
              {job?.surface_summary && (
                <>
                  <h3>Surface / fuzz proxies</h3>
                  <p className="hint">Phase-3 engineering metrics — not calibrated sputtering yields.</p>
                  <div className="chip-row">
                    {Object.entries(job.surface_summary).map(([k, v]) => (
                      <span className="chip" key={k}>
                        <span className="chip-k">{k.replace(/_/g, " ")}</span>
                        <span className="chip-v">{String(v)}</span>
                      </span>
                    ))}
                  </div>
                </>
              )}
              <h3>Cluster sizes</h3>
              <div className="chart" aria-hidden={clusterSizes.length === 0}>
                {clusterSizes.length === 0 && <span className="hint">—</span>}
                {clusterSizes.map((s, i) => (
                  <div
                    key={i}
                    className="bar"
                    style={{ height: `${(s / maxCluster) * 100}%` }}
                    title={`size ${s}`}
                  />
                ))}
              </div>
              {(kartSummary || job?.kart_summary) && (
                <>
                  <h3>KART anneal</h3>
                  {(() => {
                    const ks = kartSummary || (job?.kart_summary as KartSummary);
                    const runs = ks?.runs?.length ? ks.runs : null;
                    return (
                      <div className="stack">
                        <div className="chip-row">
                          <span className="chip">
                            <span className="chip-k">status</span>
                            <span className="chip-v">{ks?.status || "—"}</span>
                          </span>
                          {ks?.doe && (
                            <span className="chip">
                              <span className="chip-k">DOE</span>
                              <span className="chip-v">{ks.temperatures_K?.join(", ")} K</span>
                            </span>
                          )}
                          {ks?.handoff && (
                            <span className="chip">
                              <span className="chip-k">handoff</span>
                              <span className="chip-v">{ks.handoff}</span>
                            </span>
                          )}
                        </div>
                        <p className="hint">{ks?.message}</p>
                        {runs ? (
                          runs.map((r) => (
                            <div key={r.temperature_K} className="stack">
                              <h4>
                                T = {r.temperature_K} K · {r.status}
                              </h4>
                              <KartTimeline
                                events={r.events || []}
                                label={`Barrier timeline (${r.events?.[0]?.source || "events"})`}
                              />
                            </div>
                          ))
                        ) : (
                          <KartTimeline
                            events={(ks?.events as KartEvent[]) || []}
                            label="Barrier timeline"
                          />
                        )}
                        {job?.status === "completed" && (
                          <button
                            type="button"
                            className="secondary"
                            disabled={busy}
                            onClick={() => void reannealDoe()}
                          >
                            Re-anneal DOE on this cascade
                          </button>
                        )}
                      </div>
                    );
                  })()}
                </>
              )}
              {job?.mmonca_summary && (
                <>
                  <h3>MMonCa OKMC</h3>
                  <div className="chip-row">
                    <span className="chip">
                      <span className="chip-k">status</span>
                      <span className="chip-v">{String((job.mmonca_summary as { status?: string }).status || "—")}</span>
                    </span>
                  </div>
                  <p className="hint">{String((job.mmonca_summary as { message?: string }).message || "")}</p>
                  <pre className="log" style={{ height: "auto", maxHeight: 160 }}>
                    {JSON.stringify((job.mmonca_summary as { final_objects?: unknown }).final_objects || job.mmonca_summary, null, 2)}
                  </pre>
                </>
              )}
            </section>
            <section className="panel stack">
              <h2>Defect markers</h2>
              <DefectViz points={defects?.points || []} />
              <p className="hint">Vacancy = red · interstitial = copper · other = green. WS proxy markers (not full atoms).</p>
            </section>
          </div>
          </div>
        )}

        {tab === "engines" && (
          <section className="panel stack">
            <h2>Engines</h2>
            <div className="grid-2">
              <div className="stack">
                <h3>LAMMPS</h3>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">status</span>
                    <span className={`chip-v ${engines?.lammps_found ? "tone-ok" : "tone-warn"}`}>
                      {engines?.lammps_found ? "found" : "missing"}
                    </span>
                  </span>
                </div>
                <p className="hint">{engines?.lammps_path || "Set AEGIS_LAMMPS_BIN or run setup_and_run.cmd"}</p>
                <p className="hint">{engines?.lammps_version}</p>
              </div>
              <div className="stack">
                <h3>KART (k-ART)</h3>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">status</span>
                    <span className={`chip-v ${engines?.kart_found ? "tone-ok" : "tone-warn"}`}>
                      {engines?.kart_found ? "found" : "not built"}
                    </span>
                  </span>
                  <span className="chip">
                    <span className="chip-k">pin</span>
                    <span className="chip-v">{engines?.kart_commit_expected}</span>
                  </span>
                </div>
                <p className="hint">{engines?.kart_root || "third_party/kart not present"}</p>
                <p className="hint">{engines?.kart_message}</p>
                <p className="hint">
                  Phase-2 writes <span className="mono">kart_work/T*/</span> handoff packages (initial.conf,
                  conf.lammps, KMC.sh.aegis). Full catalogue anneals still launch via KART on WSL/Linux; Aegis
                  stubs events until Energy.dat appears.
                </p>
              </div>
              <div className="stack">
                <h3>MMonCa (optional OKMC)</h3>
                <div className="chip-row">
                  <span className="chip">
                    <span className="chip-k">status</span>
                    <span className={`chip-v ${engines?.mmonca_found ? "tone-ok" : "tone-warn"}`}>
                      {engines?.mmonca_found ? "found" : "optional"}
                    </span>
                  </span>
                </div>
                <p className="hint">{engines?.mmonca_path || "Not required — KART is the primary KMC path"}</p>
                <p className="hint">{engines?.mmonca_message}</p>
                <p className="hint">
                  See <span className="mono">engines/mmonca/SETUP.md</span>. Comparison object-KMC only.
                </p>
              </div>
            </div>
            <pre className="log" style={{ height: "auto" }}>
{`# Prefer setup_and_run.cmd (installs LAMMPS + clones KART if missing)

# Manual KART (PAT or SSH — never commit tokens)
git clone git@gitlab.com:groupe_mousseau/kart.git third_party/kart
cd third_party/kart
git checkout 62d66adf
# build per https://kart-doc.readthedocs.io/  (WSL recommended on Windows)
# set AEGIS_KART_ROOT / AEGIS_KART_BIN
# After a cascade, open runs/<job>/kart_work/T*/ and adapt KMC.sh.aegis

# Optional MMonCa: set AEGIS_MMONCA_BIN (see engines/mmonca/SETUP.md)`}
            </pre>
          </section>
        )}
      </main>
      <aside className="recipe" aria-label="Run recipe summary">
        <p className="eyebrow">Selected recipe</p>
        <h2>{projectName || "Untitled study"}</h2>
        <dl>
          <div>
            <dt>Material</dt>
            <dd>{material?.name || "Not selected"}</dd>
          </div>
          <div>
            <dt>Potential</dt>
            <dd className={!selectedPot?.available && !selectedPot?.is_placeholder ? "tone-fail" : selectedPot?.is_placeholder ? "tone-warn" : ""}>
              {selectedPot?.name || "Not selected"}
            </dd>
          </div>
          <div>
            <dt>Scenario</dt>
            <dd>{scenario?.fuel || "Custom"} · {params.mode}</dd>
          </div>
          <div>
            <dt>E<sub>PKA</sub></dt>
            <dd>{params.pka_energy_eV.toLocaleString()} eV · {(params.pka_energy_eV / 1000).toLocaleString()} keV</dd>
          </div>
          <div>
            <dt>Temperature</dt>
            <dd>{params.temperature_K.toLocaleString()} K</dd>
          </div>
          <div>
            <dt>Cell</dt>
            <dd>{params.nx} × {params.ny} × {params.nz} unit cells</dd>
          </div>
        </dl>
        <p className="recipe-note">
          D–D and D–T are irradiation scenario presets for cascade or implantation studies, not plasma-scale predictions.
        </p>
      </aside>
    </div>
  );
}
