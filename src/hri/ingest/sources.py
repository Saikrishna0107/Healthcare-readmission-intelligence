"""Load the list of raw data sources from config/sources.yaml."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from hri import PROJECT_ROOT

SOURCES_FILE = PROJECT_ROOT / "config" / "sources.yaml"
KINDS = {"cms_provider_data", "cdc_socrata", "cms_zip"}


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    description: str
    required_columns: tuple[str, ...]
    min_rows: int
    dataset_id: str | None = None  # cms_provider_data, cdc_socrata
    url: str | None = None  # cms_zip
    release: str | None = None  # cms_zip: fixed release label, e.g. "FY2026"
    member: str | None = None  # cms_zip: file to read inside the zip
    read_options: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"{self.name}: unknown kind {self.kind!r} (expected one of {sorted(KINDS)})")
        if self.kind == "cms_zip" and not (self.url and self.release and self.member):
            raise ValueError(f"{self.name}: cms_zip sources need url, release and member")
        if self.kind != "cms_zip" and not self.dataset_id:
            raise ValueError(f"{self.name}: {self.kind} sources need a dataset_id")


def load_sources(path: Path = SOURCES_FILE) -> dict[str, Source]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {
        name: Source(
            name=name,
            **{k: v for k, v in spec.items() if k != "required_columns"},
            required_columns=tuple(spec.get("required_columns", [])),
        )
        for name, spec in config["sources"].items()
    }
