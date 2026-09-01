"""Base classes shared by all CAD history features."""

from __future__ import annotations

from dataclasses import dataclass, field
from uuid import uuid4


def new_uuid() -> str:
    """Return a stable identifier for a persistent CAD element."""

    return str(uuid4())


@dataclass
class Feature:
    """Base entry in a Part's ordered feature history."""

    id: str = field(default_factory=new_uuid)
    name: str = "Feature"
    feature_type: str = field(default="FEATURE", init=False)
    suppressed: bool = False
    status: str = "NOT_EVALUATED"
    error_message: str = ""
    dependencies: list[str] = field(default_factory=list)
