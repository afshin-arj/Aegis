from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, Field, field_validator


class FuelScenario(str, Enum):
    DD = "D-D"
    DT = "D-T"
    CUSTOM = "custom"


class Ensemble(str, Enum):
    NVE = "nve"
    NVT = "nvt"


class RunMode(str, Enum):
    CASCADE = "cascade"
    IMPLANT = "implant"


class ElementFraction(BaseModel):
    symbol: str = Field(..., min_length=1, max_length=3)
    atomic_percent: float = Field(..., ge=0, le=100)


class Material(BaseModel):
    id: str
    name: str
    description: str = ""
    crystal: str = "bcc"
    lattice_constant_A: float = 3.165
    composition: list[ElementFraction]
    tags: list[str] = Field(default_factory=list)
    metadata_only: bool = False

    @field_validator("composition")
    @classmethod
    def composition_sums(cls, v: list[ElementFraction]) -> list[ElementFraction]:
        total = sum(e.atomic_percent for e in v)
        if v and abs(total - 100.0) > 0.05:
            raise ValueError(f"composition must sum to 100 at%, got {total}")
        return v


class MaterialUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    crystal: str | None = None
    lattice_constant_A: float | None = None
    composition: list[ElementFraction] | None = None
    tags: list[str] | None = None


class PotentialFormalism(str, Enum):
    EAM = "eam"
    EAM_ALLOY = "eam/alloy"
    EAM_FS = "eam/fs"
    MEAM = "meam"
    SNAP = "snap"
    TABLE = "table"
    OTHER = "other"


class Potential(BaseModel):
    id: str
    name: str
    formalism: PotentialFormalism
    elements: list[str]
    recommended_for: list[str] = Field(default_factory=list)
    citation: str = ""
    doi: str = ""
    source_url: str = ""
    warnings: list[str] = Field(default_factory=list)
    lammps_pair_style: str
    pair_coeff_template: str
    file_path: str | None = None
    source: str = "curated"  # curated | user
    available: bool = False
    is_placeholder: bool = False


class PotentialUploadMeta(BaseModel):
    name: str
    formalism: PotentialFormalism = PotentialFormalism.EAM_ALLOY
    elements: list[str]
    lammps_pair_style: str = "eam/alloy"
    pair_coeff_template: str = "pair_coeff * * {file} {elements}"
    notes: str = ""
    recommended_for: list[str] = Field(default_factory=lambda: ["cascade"])


class Scenario(BaseModel):
    id: str
    fuel: FuelScenario
    label: str
    description: str = ""
    defaults: dict[str, Any] = Field(default_factory=dict)


class LammpsRunParams(BaseModel):
    mode: RunMode = RunMode.CASCADE
    nx: int = Field(8, ge=2, le=64)
    ny: int = Field(8, ge=2, le=64)
    nz: int = Field(8, ge=2, le=64)
    boundary: str = "p p p"
    crystal_orient: str = "100"  # box x-axis: 100 | 110 | 111
    seed: int = 592856
    ensemble: Ensemble = Ensemble.NVE
    temperature_K: float = 300.0
    damp_ps: float = 0.1
    pka_species: str = "W"
    pka_energy_eV: float = 10000.0
    pka_direction: str = "random"  # random | h k l e.g. "1 1 0"
    n_pkas: int = Field(1, ge=1, le=20)
    pka_delay_steps: int = 0
    ion_type: str = "He"
    ion_energy_eV: float = 500.0
    ion_count: int = 1
    ion_angle_deg: float = 0.0
    timestep_fs: float = 0.001
    max_steps: int = 20000
    neighbor_skin: float = 2.0
    thermo_every: int = 100
    dump_every: int = 1000
    dump_style: str = "custom"
    restart_every: int = 0
    ws_lattice_A: float | None = None
    cluster_cutoff_A: float = 3.5
    confirm_large: bool = False


class JobCreate(BaseModel):
    project_name: str = "untitled"
    material_id: str
    material_override: Material | None = None
    potential_id: str
    scenario_id: str = "dt-divertor"
    run_params: LammpsRunParams
    run_kart_anneal: bool = False
    kart_temperature_K: float = 600.0
    kart_max_events: int = 1000
    kart_max_wall_s: float = Field(600.0, ge=1.0, le=86400.0)
    kart_max_kmc_time_s: float = Field(1.0, ge=0.0)
    # DOE: multiple anneal temperatures after the same cascade (overrides single T when set)
    kart_anneal_temperatures: list[float] | None = None


class KartAnnealRequest(BaseModel):
    """Re-anneal an existing cascade at one or more temperatures (Phase-2 DOE)."""

    temperature_K: float = 600.0
    max_events: int = Field(1000, ge=1, le=1_000_000)
    max_wall_s: float = Field(600.0, ge=1.0, le=86400.0)
    max_kmc_time_s: float = Field(1.0, ge=0.0)
    temperatures: list[float] | None = None


class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    ANALYZING = "analyzing"
    ANNEALING = "annealing"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobInfo(BaseModel):
    id: str
    status: JobStatus
    project_name: str
    material_id: str
    potential_id: str
    scenario_id: str
    created_at: str
    updated_at: str
    message: str = ""
    run_params: LammpsRunParams
    run_kart_anneal: bool = False
    defect_summary: dict[str, Any] | None = None
    kart_summary: dict[str, Any] | None = None


class EngineStatus(BaseModel):
    lammps_found: bool
    lammps_path: str | None = None
    lammps_version: str | None = None
    kart_root: str | None = None
    kart_found: bool
    kart_binary: str | None = None
    kart_commit_expected: str = "62d66adf"
    kart_message: str = ""
