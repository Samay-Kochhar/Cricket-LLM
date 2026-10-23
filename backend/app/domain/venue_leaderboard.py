"""Validated, surface-independent options for the bowling venue explorer."""
from dataclasses import asdict, dataclass

# Public metric IDs follow the catalog; output fields retain the repository contract.
METRICS = {
    "wickets_taken": ("Wickets", "wickets", "desc"),
    "bowling_average": ("Bowling average", "bowling_average", "asc"),
    "economy_rate": ("Economy", "economy_rate", "asc"),
    "balls_per_wicket": ("Bowling strike rate", "bowling_strike_rate", "asc"),
    "bowler_dot_percentage": ("Dot-ball %", "dot_percentage", "desc"),
    "boundary_percentage_conceded": ("Boundary % conceded", "boundary_percentage", "asc"),
    "balls_bowled": ("Legal deliveries (most first)", "deliveries", "desc"),
    "runs_conceded": ("Runs conceded (highest total first)", "runs_conceded", "desc"),
}
PHASES = {"": "All phases", "first6": "First 6 overs", "powerplay": "Powerplay", "middle": "Middle", "death": "Death"}
SAMPLE_UNITS = {"legal_balls": "Legal balls bowled", "matches": "Distinct ODI matches"}

@dataclass(frozen=True)
class VenueBowlingOptions:
    metric: str = "wickets_taken"
    phase: str | None = None
    year_start: int | None = None
    year_end: int | None = None
    sample_unit: str = "legal_balls"
    minimum_sample: int = 24
    limit: int = 10

    def __post_init__(self):
        if self.metric not in METRICS:
            raise ValueError("Unknown venue bowling metric.")
        if self.phase is not None and self.phase not in PHASES.keys() - {""}:
            raise ValueError("Unknown ODI phase.")
        if self.sample_unit not in SAMPLE_UNITS:
            raise ValueError("Venue rankings support legal balls or distinct matches as a minimum sample.")
        for name, low, high in (("minimum_sample", 0, 1_000_000), ("limit", 1, 100), ("year_start", 1800, 2200), ("year_end", 1800, 2200)):
            value = getattr(self, name)
            if value is None and name.startswith("year_"):
                continue
            if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
                raise ValueError(f"{name} must be a whole number from {low} to {high}.")
        if (self.year_start is None) != (self.year_end is None):
            raise ValueError("Provide both year endpoints (equal endpoints select a single year).")
        if self.year_start is not None and self.year_start > self.year_end:
            raise ValueError("The start year must not exceed the end year.")

    def as_dict(self):
        return asdict(self)

    @property
    def ranking(self):
        label, field, direction = METRICS[self.metric]
        return {"metric": self.metric, "label": label, "field": field, "direction": direction}
