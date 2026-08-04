from __future__ import annotations

import json
from pathlib import Path

from aegis_schema import Material, Potential, Scenario


class DataStore:
    def __init__(self, data_root: Path) -> None:
        self.data_root = data_root
        self.materials_path = data_root / "materials" / "presets.json"
        self.user_materials_path = data_root / "materials" / "user.json"
        self.scenarios_path = data_root / "scenarios" / "presets.json"
        self.catalog_path = data_root / "potentials" / "catalog.json"
        self.user_pots_path = data_root / "potentials" / "user_index.json"
        self.user_materials_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.user_materials_path.exists():
            self.user_materials_path.write_text("[]", encoding="utf-8")
        if not self.user_pots_path.exists():
            self.user_pots_path.write_text("[]", encoding="utf-8")

    def _load_json(self, path: Path) -> list | dict:
        return json.loads(path.read_text(encoding="utf-8"))

    def list_materials(self) -> list[Material]:
        items = self._load_json(self.materials_path)
        user = self._load_json(self.user_materials_path)
        by_id = {m["id"]: Material(**m) for m in items}
        for m in user:
            by_id[m["id"]] = Material(**m)
        return list(by_id.values())

    def get_material(self, material_id: str) -> Material | None:
        for m in self.list_materials():
            if m.id == material_id:
                return m
        return None

    def save_material(self, material: Material) -> Material:
        user: list = self._load_json(self.user_materials_path)
        user = [m for m in user if m.get("id") != material.id]
        user.append(material.model_dump())
        self.user_materials_path.write_text(json.dumps(user, indent=2), encoding="utf-8")
        return material

    def list_scenarios(self) -> list[Scenario]:
        return [Scenario(**s) for s in self._load_json(self.scenarios_path)]

    def _refresh_available(self, pot: Potential) -> Potential:
        data = pot.model_dump()
        is_placeholder = bool(data.get("is_placeholder"))
        if pot.file_path:
            full = self.data_root / pot.file_path
            name = full.name.lower()
            if "placeholder" in name or full.suffix.lower() == ".placeholder":
                is_placeholder = True
            exists = full.exists()
            # Placeholder files exist for pipeline wiring but are not production-ready MD.
            data["available"] = exists and not is_placeholder
            data["is_placeholder"] = is_placeholder
            if is_placeholder and exists and "placeholder" not in " ".join(data.get("warnings") or []).lower():
                data.setdefault("warnings", []).append(
                    "Placeholder coefficients only — dry-run / demo path; upload a published potential for real MD."
                )
        else:
            data["available"] = False
            data["is_placeholder"] = is_placeholder
        return Potential(**data)

    def list_potentials(self) -> list[Potential]:
        curated = [self._refresh_available(Potential(**p)) for p in self._load_json(self.catalog_path)]
        user = [self._refresh_available(Potential(**p)) for p in self._load_json(self.user_pots_path)]
        return curated + user

    def get_potential(self, potential_id: str) -> Potential | None:
        for p in self.list_potentials():
            if p.id == potential_id:
                return p
        return None

    def add_user_potential(self, pot: Potential) -> Potential:
        user: list = self._load_json(self.user_pots_path)
        user.append(pot.model_dump())
        self.user_pots_path.write_text(json.dumps(user, indent=2), encoding="utf-8")
        return pot

    def resolve_potential_file(self, pot: Potential) -> Path | None:
        """Return on-disk potential path even for placeholders (dry-run wiring)."""
        if not pot.file_path:
            return None
        path = self.data_root / pot.file_path
        return path if path.exists() else None
