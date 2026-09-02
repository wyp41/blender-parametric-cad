"""Linear parametric Part history."""

from __future__ import annotations

from dataclasses import dataclass, field

from .feature import Feature, new_uuid


BODY_FEATURE_TYPES = {"EXTRUDE", "REVOLVE", "TRANSFORM", "MIRROR"}


@dataclass
class Part:
    """A single CAD part with an ordered feature list."""

    id: str = field(default_factory=new_uuid)
    name: str = "Part001"
    features: list[Feature] = field(default_factory=list)
    rollback_index: int | None = None

    def add_feature(self, feature: Feature) -> None:
        self.features.append(feature)

    def remove_feature(self, feature_id: str) -> Feature | None:
        index = self.get_feature_index(feature_id)
        return self.features.pop(index) if index is not None else None

    def get_feature(self, feature_id: str) -> Feature | None:
        return next((item for item in self.features if item.id == feature_id), None)

    def get_feature_index(self, feature_id: str) -> int | None:
        return next(
            (index for index, item in enumerate(self.features) if item.id == feature_id),
            None,
        )

    def next_feature_name(self, prefix: str) -> str:
        count = sum(item.name.startswith(prefix) for item in self.features) + 1
        return f"{prefix}{count:03d}"


def previous_body_feature(part: Part, before_index: int | None = None) -> Feature | None:
    """Return the nearest feature that produces or changes the Part body."""

    limit = len(part.features) if before_index is None else before_index
    return next(
        (
            feature
            for feature in reversed(part.features[:limit])
            if feature.feature_type in BODY_FEATURE_TYPES and not feature.suppressed
        ),
        None,
    )


def get_recursive_dependents(part: Part, feature_id: str) -> list[str]:
    """Return structural dependents in feature-history order."""

    dependent_ids: set[str] = set()
    changed = True
    while changed:
        changed = False
        sources = dependent_ids | {feature_id}
        for feature in part.features:
            if feature.id not in dependent_ids and any(
                dependency in sources for dependency in feature.dependencies
            ):
                dependent_ids.add(feature.id)
                changed = True
    return [feature.id for feature in part.features if feature.id in dependent_ids]


def delete_feature(part: Part, feature_id: str) -> list[Feature]:
    """Delete a feature and every UUID-dependent downstream feature."""

    if part.get_feature(feature_id) is None:
        return []
    deleted_ids = {feature_id, *get_recursive_dependents(part, feature_id)}
    deleted = [feature for feature in part.features if feature.id in deleted_ids]
    part.features = [feature for feature in part.features if feature.id not in deleted_ids]
    part.rollback_index = None
    return deleted
