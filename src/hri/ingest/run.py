"""Ingest raw sources: check the publisher's versions, download new ones, validate, store."""

import logging
import tempfile
import zipfile
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from hri.ingest.fetch import (
    Release,
    download,
    find_member,
    make_session,
    read_first_line,
    read_raw_table,
    resolve_releases,
)
from hri.ingest.sources import Source
from hri.ingest.store import RawStore

log = logging.getLogger(__name__)


class SchemaError(Exception):
    """The downloaded file does not look like the source we expect."""


# Errors that fail one source without stopping the run.
INGEST_ERRORS = (requests.RequestException, SchemaError, OSError, KeyError, ValueError, zipfile.BadZipFile)


@dataclass(frozen=True)
class Result:
    source: str
    status: str  # "ingested", "skipped", "absent" or "failed"
    release: str | None = None
    rows: int | None = None
    error: str | None = None


class Downloads:
    """Files downloaded during one run, shared by all sources.

    One CMS archive snapshot holds several datasets (readmissions, survey, hospital profile), so
    the first source to need a snapshot downloads it and the others reuse it. The files live in a
    temporary folder that is deleted when the run ends.
    """

    def __init__(self, session: requests.Session, folder: Path):
        self.session = session
        self.folder = folder
        self._files: dict[str, tuple[Path, str]] = {}

    def get(self, url: str) -> tuple[Path, str]:
        """Local path and SHA-256 fingerprint of `url`, downloading it the first time."""
        if url not in self._files:
            log.debug("downloading %s", url)
            path = self.folder / f"download-{len(self._files)}"
            self._files[url] = (path, download(self.session, url, path))
        else:
            log.debug("reusing %s, downloaded earlier in this run", url)
        return self._files[url]


def _normalize(column: str) -> str:
    # CMS changes capitalization and spacing between releases ("Dual Proportion" in FY 2020,
    # "Dual proportion" later, "  Payment adjustment factor "). Staging maps the exact names.
    return " ".join(column.split()).lower()


def validate(df: pd.DataFrame, source: Source, release: Release, first_line: str | None = None) -> None:
    present = {_normalize(c) for c in df.columns}
    missing = [
        " or ".join(names)
        for required in source.required_columns
        for names in [(required,) if isinstance(required, str) else required]
        if not any(_normalize(n) in present for n in names)
    ]
    if missing:
        raise SchemaError(f"{source.name} {release.label}: required columns missing: {missing}")
    if len(df) < source.min_rows:
        raise SchemaError(
            f"{source.name} {release.label}: only {len(df):,} rows, expected at least {source.min_rows:,}"
        )
    # A file can be the wrong one even with the right columns: CMS's FY 2023 page links a copy of
    # the FY 2024 supplemental file. The title line says which year a file really is.
    if release.title and release.title not in (first_line or ""):
        raise SchemaError(
            f"{source.name} {release.label}: first line should contain {release.title!r}, got {first_line!r}"
        )


def ingest_source(
    source: Source,
    store: RawStore,
    session: requests.Session,
    force: bool = False,
    downloads: Downloads | None = None,
) -> list[Result]:
    """Store every release of `source` that is not stored yet. Returns one Result per release
    handled, or a single "skipped" Result when there was nothing new."""
    if downloads is None:
        with tempfile.TemporaryDirectory(dir=store.raw_dir) as tmp:
            return ingest_source(source, store, session, force, Downloads(session, Path(tmp)))

    releases = resolve_releases(source, session)
    new = [r for r in releases if force or not store.is_known(source.name, r.label)]
    if not new:
        latest = releases[-1].label if releases else None
        log.info("%-22s all %d release(s) already stored or checked, skipping", source.name, len(releases))
        return [Result(source.name, "skipped", latest)]
    return [_ingest_release(source, release, store, downloads) for release in new]


def _ingest_release(source: Source, release: Release, store: RawStore, downloads: Downloads) -> Result:
    log.info("%-22s release %s", source.name, release.label)
    path, sha256 = downloads.get(release.url)

    if source.kind == "cms_archive":
        member = find_member(path, source.members)
        if member is None:
            # Some snapshots hold only the datasets that changed (or none of ours).
            log.info("%-22s release %s does not contain this dataset", source.name, release.label)
            store.mark_absent(source.name, release.label, {"url": release.url, "sha256": sha256})
            return Result(source.name, "absent", release.label)
        release = replace(release, member=member)

    df = read_raw_table(path, source, release)
    validate(df, source, release, read_first_line(path, source, release) if release.title else None)

    ingested_at = datetime.now(UTC).isoformat(timespec="seconds")
    # Lineage columns: every raw row says where and when it came from.
    df = df.assign(_source=source.name, _release=release.label, _ingested_at=ingested_at)
    record = {"url": release.url, "sha256": sha256, "rows": len(df), "ingested_at": ingested_at}
    if release.member:
        record["member"] = release.member
    stored = store.write(df, source.name, release.label, record)
    log.info("%-22s stored %s rows -> %s", source.name, f"{len(df):,}", stored.relative_to(store.raw_dir))
    return Result(source.name, "ingested", release.label, len(df))


def ingest(sources: list[Source], store: RawStore | None = None, force: bool = False) -> list[Result]:
    """Ingest each source independently: one failing source does not stop the others.

    Releases already stored before a failure stay stored; the next run continues from there.
    """
    store = store or RawStore()
    session = make_session()
    results = []
    with tempfile.TemporaryDirectory(dir=store.raw_dir) as tmp:
        downloads = Downloads(session, Path(tmp))
        for source in sources:
            try:
                results.extend(ingest_source(source, store, session, force, downloads))
            except INGEST_ERRORS as exc:
                log.error("%-22s FAILED: %s", source.name, exc)
                results.append(Result(source.name, "failed", error=str(exc)))
    return results
