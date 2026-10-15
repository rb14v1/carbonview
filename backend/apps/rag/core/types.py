from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class SearchScope:
    """Optional legacy scope filters retained for backward compatibility."""

    organization_id: int | None = None
    facility_id: int | None = None
    reporting_period_id: int | None = None

    def to_domain_filters(self) -> dict[str, object]:
        return {
            "entities": {
                "organization": self.organization_id,
                "facility": self.facility_id,
                "reporting_period": self.reporting_period_id,
            },
            "dimensions": {},
            "time_range": {},
        }


@dataclass(frozen=True)
class ChatTurn:
    """Single chat message used for lightweight conversation continuity."""

    role: str
    content: str


@dataclass
class RetrievedDocument:
    """Normalized retrieved document returned by the search layer."""

    source: str
    content: str
    metadata: dict[str, Any]
    score: float

    @property
    def snippet(self) -> str:
        text = " ".join(str(self.content or "").split())
        if len(text) <= 180:
            return text
        return f"{text[:177].rstrip()}..."


@dataclass(frozen=True)
class GenericQueryFilters:
    """Generic filter model used by reusable domain-specific SQL handlers."""

    entities: dict[str, Any] = field(default_factory=dict)
    dimensions: dict[str, Any] = field(default_factory=dict)
    time_range: dict[str, Any] = field(default_factory=dict)

    @property
    def organization_id(self) -> int | None:
        value = self.entities.get("organization")
        return int(value) if value is not None else None

    @property
    def facility_id(self) -> int | None:
        value = self.entities.get("facility")
        return int(value) if value is not None else None

    @property
    def reporting_period_id(self) -> int | None:
        value = self.entities.get("reporting_period")
        return int(value) if value is not None else None

    @property
    def scopes(self) -> tuple[str, ...]:
        values = self.dimensions.get("scopes") or ()
        return tuple(str(value) for value in values)

    @property
    def years(self) -> tuple[int, ...]:
        values = self.time_range.get("years") or ()
        return tuple(int(value) for value in values)

    @property
    def month_year_pairs(self) -> tuple[tuple[int, int], ...]:
        values = self.time_range.get("month_year_pairs") or ()
        return tuple((int(year), int(month)) for year, month in values)

    @property
    def months(self) -> tuple[int, ...]:
        values = self.time_range.get("months") or ()
        return tuple(int(value) for value in values)

    def to_metadata(self) -> dict[str, object]:
        return {
            "entities": dict(self.entities),
            "dimensions": dict(self.dimensions),
            "time_range": dict(self.time_range),
            "organization_id": self.organization_id,
            "facility_id": self.facility_id,
            "reporting_period_id": self.reporting_period_id,
            "scopes": list(self.scopes),
            "years": list(self.years),
            "month_year_pairs": [list(pair) for pair in self.month_year_pairs],
            "months": list(self.months),
        }
