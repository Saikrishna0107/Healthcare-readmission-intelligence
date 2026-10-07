"""Find the releases of a source, download them safely and read them as text."""

import fnmatch
import hashlib
import logging
import zipfile
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from hri import __version__
from hri.ingest.sources import Source

log = logging.getLogger(__name__)

CMS_METASTORE = "https://data.cms.gov/provider-data/api/1/metastore/schemas/dataset/items"
CDC_VIEWS = "https://data.cdc.gov/api/views"
CMS_SITE = "https://data.cms.gov"
CMS_ARCHIVE = f"{CMS_SITE}/provider-data/api/1/archive/aggregate/theme"
USER_AGENT = (
    f"hri-pipeline/{__version__} (+https://github.com/Saikrishna0107/Healthcare-readmission-intelligence)"
)


@dataclass(frozen=True)
class Release:
    label: str  # the publisher's version, e.g. "2026-07-22" or "FY2026"
    url: str  # where to download this version
    member: str | None = None  # the file to read inside a zip; None when the download is the table
    read_options: dict = field(default_factory=dict)  # per-release additions to the source's options
    title: str | None = None  # text the file's first line must contain


def make_session() -> requests.Session:
    # Retry busy or briefly unavailable servers, waiting longer each time (2s, 4s, 8s, 16s).
    retry = Retry(
        total=4,
        backoff_factor=2,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    session.headers["User-Agent"] = USER_AGENT
    return session


def resolve_releases(source: Source, session: requests.Session) -> list[Release]:
    """Ask the publisher which versions exist, without downloading the data. Oldest first."""
    if source.kind == "cms_provider_data":
        # The download URL contains a code that changes with every refresh, so it is looked up
        # from the permanent dataset ID each time instead of being hard-coded.
        meta = _get_json(session, f"{CMS_METASTORE}/{source.dataset_id}")
        return [Release(label=meta["modified"], url=meta["distribution"][0]["downloadURL"])]

    if source.kind == "cdc_socrata":
        meta = _get_json(session, f"{CDC_VIEWS}/{source.dataset_id}.json")
        updated = datetime.fromtimestamp(meta["rowsUpdatedAt"], tz=UTC)
        return [
            Release(
                label=updated.strftime("%Y-%m-%d"),
                url=f"{CDC_VIEWS}/{source.dataset_id}/rows.csv?accessType=DOWNLOAD",
            )
        ]

    if source.kind == "cms_archive":
        # CMS keeps a zip of every dataset in a theme about once a quarter (D-023). Each snapshot
        # is one release, labelled with its date. Annual bundles repeat the quarterly ones.
        listing = _get_json(session, f"{CMS_ARCHIVE}/{source.archive_theme}/relative")
        snapshots = [s for s in listing["data"] if s["type"] == "theme"]
        return sorted(
            (Release(label=s["date"], url=CMS_SITE + s["url"]) for s in snapshots),
            key=lambda r: r.label,
        )

    # cms_zip and static_file: a fixed file per release (a fiscal year, a census vintage),
    # so the releases are set in the config.
    return [
        Release(label=r.release, url=r.url, member=r.member, read_options=r.read_options, title=r.title)
        for r in source.releases
    ]


def find_member(path: Path, patterns: tuple[str, ...]) -> str | None:
    """The one file in the zip whose name matches a pattern (case-insensitive), or None.

    Folders inside the zip are ignored, and so are the `__MACOSX/` copies that zips made on a Mac
    carry. More than one match means the patterns are ambiguous, which is an error.
    """
    with zipfile.ZipFile(path) as archive:
        matches = [
            name
            for name in archive.namelist()
            if not name.startswith("__MACOSX/")
            and any(fnmatch.fnmatch(name.rsplit("/", 1)[-1].lower(), p.lower()) for p in patterns)
        ]
    if len(matches) > 1:
        raise ValueError(f"several files match {list(patterns)}: {matches}")
    return matches[0] if matches else None


def download(session: requests.Session, url: str, dest: Path) -> str:
    """Stream `url` to `dest` and return its SHA-256 fingerprint.

    The file is written under a temporary name and renamed only when complete, so an
    interrupted download can never be mistaken for a finished one.
    """
    partial = dest.with_name(dest.name + ".part")
    digest = hashlib.sha256()
    with session.get(url, stream=True, timeout=(30, 300)) as response:
        response.raise_for_status()
        with open(partial, "wb") as f:
            for chunk in response.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                digest.update(chunk)
    partial.replace(dest)
    return digest.hexdigest()


def read_raw_table(path: Path, source: Source, release: Release) -> pd.DataFrame:
    """Read a downloaded file exactly as published: every value stays text.

    `na_filter=False` keeps markers such as "N/A" or "Not Available" as literal text instead of
    turning them into missing values. Deciding what counts as missing is a cleaning decision,
    made visibly in the staging models, not silently here.
    """
    options = {"dtype": str, "na_filter": False, **source.read_options, **release.read_options}
    if release.member:
        with zipfile.ZipFile(path) as archive, archive.open(release.member) as member:
            df = pd.read_csv(member, **options)
    else:
        df = pd.read_csv(path, **options)

    df.columns = df.columns.str.strip()
    # Lines that end with a delimiter create an empty, unnamed last column; drop only those.
    empty_unnamed = [c for c in df.columns if c.startswith("Unnamed:") and (df[c] == "").all()]
    if empty_unnamed:
        log.debug("%s: dropping empty unnamed columns %s", source.name, empty_unnamed)
        df = df.drop(columns=empty_unnamed)
    return df


def read_first_line(path: Path, source: Source, release: Release) -> str:
    """The file's first line, e.g. a title such as "FY 2023 IPPS Final Rule: ..."."""
    encoding = {**source.read_options, **release.read_options}.get("encoding", "utf-8")
    if release.member:
        with zipfile.ZipFile(path) as archive, archive.open(release.member) as member:
            raw = member.readline()
    else:
        with open(path, "rb") as f:
            raw = f.readline()
    return raw.decode(encoding, errors="replace").strip()


def _get_json(session: requests.Session, url: str) -> dict:
    response = session.get(url, timeout=(30, 60))
    response.raise_for_status()
    return response.json()
