"""Ingest raw sources: check the publisher's version, download if new, validate, store."""

import logging
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
import requests

from hri.ingest.fetch import download, make_session, read_raw_table, resolve_release
from hri.ingest.sources import Source
from hri.ingest.store import RawStore

log = logging.getLogger(__name__)


class SchemaError(Exception):
    """The downloaded file does not look like the source we expect."""


@dataclass(frozen=True)
class Result:
    source: str
    status: str  # "ingested", "skipped" or "failed"
    release: str | None = None
    rows: int | None = None
    error: str | None = None


def validate(df: pd.DataFrame, source: Source) -> None:
    missing = [c for c in source.required_columns if c not in df.columns]
    if missing:
        raise SchemaError(f"{source.name}: required columns missing: {missing}")
    if len(df) < source.min_rows:
        raise SchemaError(f"{source.name}: only {len(df):,} rows, expected at least {source.min_rows:,}")


def ingest_source(source: Source, store: RawStore, session: requests.Session, force: bool = False) -> Result:
    release = resolve_release(source, session)
    if not force and store.has_release(source.name, release.label):
        log.info("%-18s release %s already stored, skipping", source.name, release.label)
        return Result(source.name, "skipped", release.label)

    log.info("%-18s downloading release %s", source.name, release.label)
    with tempfile.TemporaryDirectory(dir=store.raw_dir) as tmp:
        downloaded = Path(tmp) / "download"
        sha256 = download(session, release.url, downloaded)
        df = read_raw_table(downloaded, source)

    validate(df, source)
    ingested_at = datetime.now(UTC).isoformat(timespec="seconds")
    # Lineage columns: every raw row says where and when it came from.
    df = df.assign(_source=source.name, _release=release.label, _ingested_at=ingested_at)
    path = store.write(
        df,
        source.name,
        release.label,
        {"url": release.url, "sha256": sha256, "rows": len(df), "ingested_at": ingested_at},
    )
    log.info("%-18s stored %s rows -> %s", source.name, f"{len(df):,}", path.relative_to(store.raw_dir))
    return Result(source.name, "ingested", release.label, len(df))


def ingest(sources: list[Source], store: RawStore | None = None, force: bool = False) -> list[Result]:
    """Ingest each source independently: one failing source does not stop the others."""
    store = store or RawStore()
    session = make_session()
    results = []
    for source in sources:
        try:
            results.append(ingest_source(source, store, session, force))
        except (requests.RequestException, SchemaError, OSError, KeyError, ValueError) as exc:
            log.error("%-18s FAILED: %s", source.name, exc)
            results.append(Result(source.name, "failed", error=str(exc)))
    return results
