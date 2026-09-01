"""Top-level serializable CAD document."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from .part import Part


@dataclass
class CadDocument:
    """Persistent source of truth for all parametric CAD data."""

    parts: list[Part] = field(default_factory=list)
    active_part_id: str | None = None
    schema_version: int = 2

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
