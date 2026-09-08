"""Constant-radius fillet feature definition."""

from __future__ import annotations

from dataclasses import dataclass, field

from ..core.feature import Feature
from ..core.references import EdgeReference


@dataclass
class FilletFeature(Feature):
    feature_type: str = field(default="FILLET", init=False)
    edge_references: list[EdgeReference] = field(default_factory=list)
    radius: float = 0.002

    def __post_init__(self) -> None:
        references = list(self.edge_references)
        self.edge_references = references
        for reference in references:
            if reference.producer_feature_id not in self.dependencies:
                self.dependencies.append(reference.producer_feature_id)

