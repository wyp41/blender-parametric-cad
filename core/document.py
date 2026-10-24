"""Top-level serializable CAD document."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .part import Part
from .assembly import Assembly, AssemblyInstance, PartInUseError


@dataclass
class CadDocument:
    """Persistent source of truth for all parametric CAD data."""

    parts: list[Part] = field(default_factory=list)
    active_part_id: str | None = None
    schema_version: int = 3
    assemblies: list[Assembly] = field(default_factory=list)

    def get_assembly(self, assembly_id: str) -> Assembly | None:
        return next((item for item in self.assemblies if item.id == assembly_id), None)

    def add_assembly(self, assembly: Assembly) -> Assembly:
        if self.get_assembly(assembly.id):
            raise ValueError(f"Duplicate Assembly UUID: {assembly.id}")
        self.assemblies.append(assembly)
        return assembly

    def remove_assembly(self, assembly_id: str) -> Assembly | None:
        assembly = self.get_assembly(assembly_id)
        if assembly is not None:
            self.assemblies.remove(assembly)
        return assembly

    def get_instance(self, assembly_id: str, instance_id: str) -> AssemblyInstance | None:
        assembly = self.get_assembly(assembly_id)
        return next((item for item in assembly.instances if item.id == instance_id), None) if assembly else None

    def add_instance(self, assembly_id: str, instance: AssemblyInstance) -> AssemblyInstance:
        assembly = self.get_assembly(assembly_id)
        if assembly is None:
            raise ValueError(f"Unknown Assembly: {assembly_id}")
        if self.get_part(instance.part_studio_id) is None:
            raise ValueError(f"Unknown source Part Studio: {instance.part_studio_id}")
        if any(item.id == instance.id for group in self.assemblies for item in group.instances):
            raise ValueError(f"Duplicate Instance UUID: {instance.id}")
        assembly.instances.append(instance)
        return instance

    def remove_instance(self, assembly_id: str, instance_id: str) -> AssemblyInstance | None:
        instance = self.get_instance(assembly_id, instance_id)
        if instance is not None:
            self.get_assembly(assembly_id).instances.remove(instance)
        return instance

    def get_part(self, part_id: str) -> Part | None:
        return next((part for part in self.parts if part.id == part_id), None)

    def get_active_part(self) -> Part | None:
        return self.get_part(self.active_part_id) if self.active_part_id else None

    def set_active_part(self, part_id: str | None) -> Part | None:
        if part_id is None:
            self.active_part_id = None
            return None
        part = self.get_part(part_id)
        if part is None:
            raise ValueError(f"Unknown Part Studio: {part_id}")
        self.active_part_id = part.id
        return part

    def add_part(self, part: Part) -> None:
        self.parts.append(part)
        self.active_part_id = part.id

    def remove_part(self, part_id: str) -> Part | None:
        references = [
            {"assembly_id": assembly.id, "instance_id": instance.id}
            for assembly in self.assemblies for instance in assembly.instances
            if instance.part_studio_id == part_id
        ]
        if references:
            raise PartInUseError(part_id, references)
        index = next(
            (index for index, part in enumerate(self.parts) if part.id == part_id),
            None,
        )
        if index is None:
            return None
        removed = self.parts.pop(index)
        if self.active_part_id == part_id:
            if index > 0:
                self.active_part_id = self.parts[index - 1].id
            elif self.parts:
                self.active_part_id = self.parts[0].id
            else:
                self.active_part_id = None
        return removed

    @property
    def active_part(self) -> Part | None:
        return self.get_active_part()

    def to_dict(self) -> dict[str, Any]:
        from .serialization import document_to_dict

        return document_to_dict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CadDocument":
        from .serialization import document_from_dict

        return document_from_dict(data)
