"""Find the current release of a source, download it safely and read it as text."""

import hashlib
import io
import logging
import zipfile
from dataclasses import dataclass
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
USER_AGENT = (
    f"hri-pipeline/{__version__} (+https://github.com/Saikrishna0107/Healthcare-readmission-intelligence)"
)


@dataclass(frozen=True)
class Release:
    label: str  # the publisher's version, e.g. "2026-07-22" or "FY2026"
    url: str  # where to download this version


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


def resolve_release(source: Source, session: requests.Session) -> Release:
    """Ask the publisher which version is current, without downloading the data."""
    if source.kind == "cms_provider_data":
        # The download URL contains a code that changes with every refresh, so it is looked up
        # from the permanent dataset ID each time instead of being hard-coded.
        meta = _get_json(session, f"{CMS_METASTORE}/{source.dataset_id}")
        return Release(label=meta["modified"], url=meta["distribution"][0]["downloadURL"])

    if source.kind == "cdc_socrata":
        meta = _get_json(session, f"{CDC_VIEWS}/{source.dataset_id}.json")
        updated = datetime.fromtimestamp(meta["rowsUpdatedAt"], tz=UTC)
        return Release(
            label=updated.strftime("%Y-%m-%d"),
            url=f"{CDC_VIEWS}/{source.dataset_id}/rows.csv?accessType=DOWNLOAD",
        )

    # cms_zip: one fixed file per fiscal year, so the release is set in the config.
    return Release(label=source.release, url=source.url)


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


def read_raw_table(path: Path, source: Source) -> pd.DataFrame:
    """Read a downloaded file exactly as published: every value stays text.

    `na_filter=False` keeps markers such as "N/A" or "Not Available" as literal text instead of
    turning them into missing values. Deciding what counts as missing is a cleaning decision,
    made visibly in the staging models, not silently here.
    """
    options = {"dtype": str, "na_filter": False, **source.read_options}
    if source.kind == "cms_zip":
        with zipfile.ZipFile(path) as archive, archive.open(source.member) as member:
            df = pd.read_csv(io.BytesIO(member.read()), **options)
    else:
        df = pd.read_csv(path, **options)

    df.columns = df.columns.str.strip()
    # Lines that end with a delimiter create an empty, unnamed last column; drop only those.
    empty_unnamed = [c for c in df.columns if c.startswith("Unnamed:") and (df[c] == "").all()]
    if empty_unnamed:
        log.debug("%s: dropping empty unnamed columns %s", source.name, empty_unnamed)
        df = df.drop(columns=empty_unnamed)
    return df


def _get_json(session: requests.Session, url: str) -> dict:
    response = session.get(url, timeout=(30, 60))
    response.raise_for_status()
    return response.json()
