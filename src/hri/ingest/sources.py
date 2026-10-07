"""Load the list of raw data sources from config/sources.yaml."""

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from hri import PROJECT_ROOT

SOURCES_FILE = PROJECT_ROOT / "config" / "sources.yaml"
KINDS = {"cms_provider_data", "cdc_socrata", "cms_zip", "static_file", "cms_archive"}
# Kinds whose version cannot be looked up from an API: the release labels are set in the config.
FIXED_RELEASE_KINDS = {"cms_zip", "static_file"}

# A required column is one name, or a list of names that mean the same column in different
# releases (CMS renamed "Provider ID" to "Facility ID" in 2019).
RequiredColumn = str | tuple[str, ...]


@dataclass(frozen=True)
class FixedRelease:
    """One release of a cms_zip or static_file source: a file that never changes once published."""

    release: str  # label, e.g. "FY2026" or "2020"
    url: str
    member: str | None = None  # cms_zip: file to read inside the zip
    read_options: dict = field(default_factory=dict)  # added to (and overriding) the source's options
    title: str | None = None  # text the file's first line must contain, e.g. "FY 2023 IPPS"


@dataclass(frozen=True)
class Source:
    name: str
    kind: str
    description: str
    required_columns: tuple[RequiredColumn, ...]
    min_rows: int
    dataset_id: str | None = None  # cms_provider_data, cdc_socrata
    # cms_zip, static_file: either one release (url + release [+ member]) or a `releases` list
    url: str | None = None
    release: str | None = None
    member: str | None = None
    releases: tuple[FixedRelease, ...] = ()
    archive_theme: str | None = None  # cms_archive: CMS archive theme, e.g. "hospitals"
    members: tuple[str, ...] = ()  # cms_archive: file name patterns that identify the dataset
    read_options: dict = field(default_factory=dict)

    def __post_init__(self):
        if self.kind not in KINDS:
            raise ValueError(f"{self.name}: unknown kind {self.kind!r} (expected one of {sorted(KINDS)})")

        if self.kind in FIXED_RELEASE_KINDS:
            if (self.url or self.release) and self.releases:
                raise ValueError(f"{self.name}: give either url and release, or a releases list, not both")
            if not self.releases and not (self.url and self.release):
                raise ValueError(f"{self.name}: {self.kind} sources need url and release (or releases)")
            if not self.releases:
                # Store the single-release form as a one-item list, so the rest of the code has
                # only one shape to handle.
                object.__setattr__(self, "releases", (FixedRelease(self.release, self.url, self.member),))
            if self.kind == "cms_zip" and not all(r.member for r in self.releases):
                raise ValueError(f"{self.name}: cms_zip releases need member")
        elif self.kind == "cms_archive":
            if not (self.archive_theme and self.members):
                raise ValueError(f"{self.name}: cms_archive sources need archive_theme and members")
        elif not self.dataset_id:
            raise ValueError(f"{self.name}: {self.kind} sources need a dataset_id")


def load_sources(path: Path = SOURCES_FILE) -> dict[str, Source]:
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    return {name: _source_from_config(name, spec) for name, spec in config["sources"].items()}


def _source_from_config(name: str, spec: dict) -> Source:
    spec = dict(spec)
    required = tuple(tuple(c) if isinstance(c, list) else c for c in spec.pop("required_columns", []))
    releases = tuple(FixedRelease(**r) for r in spec.pop("releases", []))
    members = tuple(spec.pop("members", []))
    return Source(name=name, required_columns=required, releases=releases, members=members, **spec)
