"""Ingestion tests. HTTP is faked with `responses`, so no test calls the real CMS or CDC APIs."""

import io
import zipfile

import pandas as pd
import pytest
import responses

from hri.ingest import RawStore, SchemaError, Source, ingest, ingest_source, load_sources
from hri.ingest.fetch import CDC_VIEWS, CMS_METASTORE, make_session, resolve_release

CSV = (
    "Facility ID,Measure Name,Excess Readmission Ratio\n"
    "010001,READM-30-HF-HRRP,1.0233\n"
    "010005,READM-30-HF-HRRP,N/A\n"
)


def cms_source(**overrides) -> Source:
    spec = dict(
        name="hrrp",
        kind="cms_provider_data",
        dataset_id="9n3s-kdb3",
        description="test",
        required_columns=("Facility ID", "Excess Readmission Ratio"),
        min_rows=2,
    )
    return Source(**{**spec, **overrides})


def mock_cms(release="2026-01-26", body=CSV):
    file_url = f"https://data.cms.gov/files/{release}/hrrp.csv"
    responses.get(
        f"{CMS_METASTORE}/9n3s-kdb3",
        json={"title": "HRRP", "modified": release, "distribution": [{"downloadURL": file_url}]},
    )
    responses.get(file_url, body=body)


@responses.activate
def test_stores_raw_values_as_text_with_lineage(tmp_path):
    mock_cms()
    store = RawStore(tmp_path)

    result = ingest_source(cms_source(), store, make_session())

    assert result.status == "ingested" and result.rows == 2
    df = pd.read_parquet(store.path_for("hrrp", "2026-01-26"))
    # Leading zeros survive and "N/A" stays literal text: the raw layer does not interpret values.
    assert df["Facility ID"].tolist() == ["010001", "010005"]
    assert df["Excess Readmission Ratio"].tolist() == ["1.0233", "N/A"]
    assert set(df["_release"]) == {"2026-01-26"} and set(df["_source"]) == {"hrrp"}

    entry = store.load_manifest()["hrrp"]
    assert entry["latest"] == "2026-01-26"
    assert entry["releases"]["2026-01-26"]["rows"] == 2
    assert len(entry["releases"]["2026-01-26"]["sha256"]) == 64


@responses.activate
def test_skips_download_when_release_unchanged(tmp_path):
    mock_cms()
    store = RawStore(tmp_path)
    ingest_source(cms_source(), store, make_session())

    result = ingest_source(cms_source(), store, make_session())

    assert result.status == "skipped"
    downloads = [c for c in responses.calls if c.request.url.endswith(".csv")]
    assert len(downloads) == 1  # the second run only asked for the version, not the file


@responses.activate
def test_new_release_is_stored_next_to_the_old_one(tmp_path):
    store = RawStore(tmp_path)
    mock_cms("2026-01-26")
    ingest_source(cms_source(), store, make_session())
    responses.reset()
    mock_cms("2026-07-22")

    ingest_source(cms_source(), store, make_session())

    entry = store.load_manifest()["hrrp"]
    assert entry["latest"] == "2026-07-22"
    assert set(entry["releases"]) == {"2026-01-26", "2026-07-22"}
    assert store.path_for("hrrp", "2026-01-26").exists()


@responses.activate
def test_missing_required_column_stops_and_stores_nothing(tmp_path):
    mock_cms(body="Facility ID,Renamed Column\n010001,1.02\n010005,0.98\n")
    store = RawStore(tmp_path)

    with pytest.raises(SchemaError, match="Excess Readmission Ratio"):
        ingest_source(cms_source(), store, make_session())

    assert store.load_manifest() == {}
    assert not store.path_for("hrrp", "2026-01-26").exists()


@responses.activate
def test_too_few_rows_is_rejected(tmp_path):
    mock_cms()
    with pytest.raises(SchemaError, match="only 2 rows"):
        ingest_source(cms_source(min_rows=1000), RawStore(tmp_path), make_session())


@responses.activate
def test_one_failing_source_does_not_stop_the_others(tmp_path):
    mock_cms()
    responses.get(f"{CMS_METASTORE}/broken-id", status=404)
    broken = cms_source(name="broken", dataset_id="broken-id")

    results = ingest([broken, cms_source()], RawStore(tmp_path))

    assert [(r.source, r.status) for r in results] == [("broken", "failed"), ("hrrp", "ingested")]


@responses.activate
def test_cms_zip_reads_member_skips_title_line_and_drops_trailing_empty_column(tmp_path):
    text = "A title line\n  Hospital CCN\tPeer group assignment\t\n010001\t2\t\n010005\t5\t\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("FR FY 2026.txt", text.encode("cp1252"))
    responses.get("https://www.cms.gov/files/zip/supp.zip", body=buffer.getvalue())
    source = Source(
        name="hrrp_supplemental",
        kind="cms_zip",
        url="https://www.cms.gov/files/zip/supp.zip",
        release="FY2026",
        member="FR FY 2026.txt",
        read_options={"sep": "\t", "skiprows": 1, "encoding": "cp1252"},
        description="test",
        required_columns=("Hospital CCN", "Peer group assignment"),
        min_rows=2,
    )
    store = RawStore(tmp_path)

    ingest_source(source, store, make_session())

    df = pd.read_parquet(store.path_for("hrrp_supplemental", "FY2026"))
    lineage = ["_source", "_release", "_ingested_at"]
    assert list(df.columns) == ["Hospital CCN", "Peer group assignment", *lineage]
    assert df["Hospital CCN"].tolist() == ["010001", "010005"]


@responses.activate
def test_cdc_release_label_is_the_rows_updated_date(tmp_path):
    responses.get(f"{CDC_VIEWS}/swc5-untb.json", json={"rowsUpdatedAt": 1764844506})
    source = Source(
        name="places_county",
        kind="cdc_socrata",
        dataset_id="swc5-untb",
        description="test",
        required_columns=(),
        min_rows=0,
    )
    release = resolve_release(source, make_session())

    assert release.label == "2025-12-04"
    assert release.url == f"{CDC_VIEWS}/swc5-untb/rows.csv?accessType=DOWNLOAD"


def test_project_sources_config_is_valid():
    sources = load_sources()
    assert {"hrrp", "hrrp_supplemental", "hospital_info", "hcahps", "places_county"} <= set(sources)
    assert all(s.required_columns for s in sources.values())
