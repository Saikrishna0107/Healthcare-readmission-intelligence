"""Ingestion tests. HTTP is faked with `responses`, so no test calls the real CMS or CDC APIs."""

import io
import zipfile

import pandas as pd
import pytest
import responses

from hri.ingest import RawStore, SchemaError, Source, ingest, ingest_source, load_sources
from hri.ingest.fetch import CDC_VIEWS, CMS_ARCHIVE, CMS_METASTORE, Release, make_session, resolve_releases
from hri.ingest.run import validate
from hri.ingest.sources import FixedRelease

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

    [result] = ingest_source(cms_source(), store, make_session())

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

    [result] = ingest_source(cms_source(), store, make_session())

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
def test_read_latest_returns_the_newest_release(tmp_path):
    store = RawStore(tmp_path)
    mock_cms("2026-01-26")
    ingest_source(cms_source(), store, make_session())
    responses.reset()
    mock_cms("2026-07-22")
    ingest_source(cms_source(), store, make_session())

    assert set(store.read_latest("hrrp")["_release"]) == {"2026-07-22"}
    with pytest.raises(KeyError, match="hri ingest --only hcahps"):
        store.read_latest("hcahps")


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
def test_static_file_reads_pipe_delimited_text_with_byte_order_mark(tmp_path):
    url = "https://www2.census.gov/geo/rel/zcta_county.txt"
    body = "﻿GEOID_ZCTA5_20|GEOID_COUNTY_20|AREALAND_PART\n|01003|339765765\n02135|25025|9000\n"
    responses.get(url, body=body.encode("utf-8"))
    source = Source(
        name="census_zcta_county",
        kind="static_file",
        url=url,
        release="2020",
        read_options={"sep": "|", "encoding": "utf-8-sig"},
        description="test",
        required_columns=("GEOID_ZCTA5_20", "GEOID_COUNTY_20"),
        min_rows=2,
    )
    store = RawStore(tmp_path)

    [result] = ingest_source(source, store, make_session())

    assert (result.status, result.release) == ("ingested", "2020")
    df = pd.read_parquet(store.path_for("census_zcta_county", "2020"))
    # The byte-order mark is not glued to the first column name, and codes keep leading zeros.
    assert df.columns[0] == "GEOID_ZCTA5_20"
    assert df["GEOID_ZCTA5_20"].tolist() == ["", "02135"]
    assert df["GEOID_COUNTY_20"].tolist() == ["01003", "25025"]


def test_static_file_needs_url_and_release():
    with pytest.raises(ValueError, match="need url and release"):
        Source(
            name="x",
            kind="static_file",
            url="https://example.org/f.txt",
            description="",
            required_columns=(),
            min_rows=0,
        )


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
    [release] = resolve_releases(source, make_session())

    assert release.label == "2025-12-04"
    assert release.url == f"{CDC_VIEWS}/swc5-untb/rows.csv?accessType=DOWNLOAD"


def make_zip(files: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        for name, text in files.items():
            z.writestr(name, text)
    return buffer.getvalue()


def archive_source(name="hrrp_archive", members=("*Readmissions_Reduction_Program_Hospital.csv",)) -> Source:
    return Source(
        name=name,
        kind="cms_archive",
        archive_theme="hospitals",
        members=members,
        description="test",
        required_columns=(("Facility ID", "Provider ID"), "Excess Readmission Ratio"),
        min_rows=2,
    )


def mock_archive(snapshots: dict[str, bytes]):
    """Fake the CMS archive listing plus one zip per snapshot date."""
    listing = [{"type": "theme", "date": date, "url": f"/archive/hospitals_{date}.zip"} for date in snapshots]
    # Annual bundles repeat the quarterly snapshots and must be ignored.
    listing.append({"type": "annual_theme", "date": "2025-12-31", "url": "/archive/annual_2025.zip"})
    responses.get(f"{CMS_ARCHIVE}/hospitals/relative", json={"data": listing})
    for date, body in snapshots.items():
        responses.get(f"https://data.cms.gov/archive/hospitals_{date}.zip", body=body)


OLD_HRRP = "Hospital Name,Provider ID,Excess Readmission Ratio\nA,010001,1.02\nB,010005,N/A\n"
NEW_HRRP = "Facility Name,Facility ID,Excess Readmission Ratio\nA,010001,0.98\nB,010005,1.01\n"
HRRP_2025 = "FY_2025_Hospital_Readmissions_Reduction_Program_Hospital.csv"


@responses.activate
def test_archive_stores_one_release_per_snapshot_whatever_the_file_is_called(tmp_path):
    mock_archive(
        {
            "2019-04-04": make_zip({HRRP_2025.replace("2025", "2019"): OLD_HRRP}),
            # A folder inside the zip, plus the copy a Mac adds, which must be ignored.
            "2025-04-30": make_zip(
                {f"hospitals_04_2025/{HRRP_2025}": NEW_HRRP, f"__MACOSX/hospitals_04_2025/._{HRRP_2025}": "x"}
            ),
        }
    )
    store = RawStore(tmp_path)

    results = ingest_source(archive_source(), store, make_session())

    assert [(r.status, r.release) for r in results] == [
        ("ingested", "2019-04-04"),
        ("ingested", "2025-04-30"),
    ]
    old = pd.read_parquet(store.path_for("hrrp_archive", "2019-04-04"))
    # Raw keeps each release's own column names; staging maps "Provider ID" to "Facility ID".
    assert "Provider ID" in old.columns
    assert old["Excess Readmission Ratio"].tolist() == ["1.02", "N/A"]
    entry = store.load_manifest()["hrrp_archive"]
    assert entry["latest"] == "2025-04-30"
    assert entry["releases"]["2025-04-30"]["member"] == f"hospitals_04_2025/{HRRP_2025}"


@responses.activate
def test_snapshot_without_the_dataset_is_remembered_and_not_downloaded_again(tmp_path):
    mock_archive(
        {
            "2020-07-04": make_zip({"Something_Else.csv": "a\n1\n"}),
            "2025-04-30": make_zip({HRRP_2025: NEW_HRRP}),
        }
    )
    store = RawStore(tmp_path)

    first = ingest_source(archive_source(), store, make_session())
    second = ingest_source(archive_source(), store, make_session())

    assert [(r.status, r.release) for r in first] == [("absent", "2020-07-04"), ("ingested", "2025-04-30")]
    assert [r.status for r in second] == ["skipped"]
    zip_downloads = [c for c in responses.calls if c.request.url.endswith(".zip")]
    assert len(zip_downloads) == 2  # each snapshot once, in the first run only


@responses.activate
def test_one_snapshot_is_downloaded_once_for_all_sources_in_a_run(tmp_path):
    hcahps = "Facility ID,Excess Readmission Ratio\n010001,x\n010005,y\n"
    mock_archive({"2025-04-30": make_zip({HRRP_2025: NEW_HRRP, "HCAHPS-Hospital.csv": hcahps})})
    sources = [archive_source(), archive_source("hcahps_archive", members=("HCAHPS-Hospital.csv",))]

    results = ingest(sources, RawStore(tmp_path))

    assert [(r.source, r.status) for r in results] == [
        ("hrrp_archive", "ingested"),
        ("hcahps_archive", "ingested"),
    ]
    assert len([c for c in responses.calls if c.request.url.endswith(".zip")]) == 1


@responses.activate
def test_ambiguous_member_patterns_fail(tmp_path):
    mock_archive({"2025-04-30": make_zip({"a_HCAHPS.csv": NEW_HRRP, "b_HCAHPS.csv": NEW_HRRP})})

    results = ingest([archive_source(members=("*HCAHPS.csv",))], RawStore(tmp_path))

    assert results[0].status == "failed" and "several files match" in results[0].error


def supplemental_source() -> Source:
    return Source(
        name="hrrp_supplemental",
        kind="cms_zip",
        releases=(
            FixedRelease(
                "FY2020",
                "https://www.cms.gov/files/zip/fy2020.zip",
                "tab2.txt",
                title="FY 2020 IPPS",
            ),
            FixedRelease(
                "FY2022",
                "https://www.cms.gov/files/zip/fy2022.zip",
                "FR FY 2022.csv",
                read_options={"sep": ",", "skiprows": 3},
                title="FY 2022 IPPS",
            ),
        ),
        read_options={"sep": "\t", "skiprows": 1},
        description="test",
        required_columns=("Hospital CCN", "Dual proportion"),
        min_rows=2,
    )


def mock_supplemental(fy2022_title="FY 2022 IPPS Final Rule: HRRP Supplemental Data"):
    fy2020 = "FY 2020 IPPS Final Rule: HRRP\nHospital CCN\tDual Proportion\n010001\t0.16\n010005\t0.20\n"
    fy2022 = f"{fy2022_title},\nblank row,\nTable,\nHospital CCN,Dual proportion\n010001,0.17\n010005,0.21\n"
    responses.get("https://www.cms.gov/files/zip/fy2020.zip", body=make_zip({"tab2.txt": fy2020}))
    responses.get("https://www.cms.gov/files/zip/fy2022.zip", body=make_zip({"FR FY 2022.csv": fy2022}))


@responses.activate
def test_each_fiscal_year_is_read_with_its_own_layout(tmp_path):
    mock_supplemental()
    store = RawStore(tmp_path)

    results = ingest_source(supplemental_source(), store, make_session())

    assert [(r.status, r.release, r.rows) for r in results] == [
        ("ingested", "FY2020", 2),
        ("ingested", "FY2022", 2),
    ]
    # Capitalization differs by year ("Dual Proportion" vs "Dual proportion"): both pass the check.
    assert "Dual Proportion" in pd.read_parquet(store.path_for("hrrp_supplemental", "FY2020")).columns
    fy2022 = pd.read_parquet(store.path_for("hrrp_supplemental", "FY2022"))
    assert fy2022["Hospital CCN"].tolist() == ["010001", "010005"]


@responses.activate
def test_file_for_the_wrong_fiscal_year_is_rejected(tmp_path):
    # The real trap: CMS's FY 2023 page links a copy of the FY 2024 file.
    mock_supplemental(fy2022_title="FY 2024 IPPS Final Rule: HRRP Supplemental Data")
    store = RawStore(tmp_path)

    with pytest.raises(SchemaError, match="should contain 'FY 2022 IPPS'"):
        ingest_source(supplemental_source(), store, make_session())

    assert set(store.load_manifest()["hrrp_supplemental"]["releases"]) == {"FY2020"}


def test_renamed_required_column_accepts_either_name():
    source = archive_source()
    release = Release("2019-04-04", "https://example.org")
    old_names = pd.DataFrame({"Provider ID": ["1", "2"], "Excess Readmission Ratio": ["1", "2"]})
    unknown_names = pd.DataFrame({"CCN": ["1", "2"], "Excess Readmission Ratio": ["1", "2"]})

    validate(old_names, source, release)
    with pytest.raises(SchemaError, match="Facility ID or Provider ID"):
        validate(unknown_names, source, release)


def test_source_cannot_mix_single_release_and_releases_list():
    with pytest.raises(ValueError, match="not both"):
        Source(
            name="x",
            kind="cms_zip",
            url="https://example.org/a.zip",
            release="FY2026",
            member="a.txt",
            releases=(FixedRelease("FY2025", "https://example.org/b.zip", "b.txt"),),
            description="",
            required_columns=(),
            min_rows=0,
        )


def test_project_sources_config_is_valid():
    sources = load_sources()
    assert {"hrrp", "hrrp_supplemental", "hospital_info", "hcahps", "places_county"} <= set(sources)
    assert all(s.required_columns for s in sources.values())
    # One supplemental file per fiscal year, each with a title check against the wrong-year trap.
    supplemental = sources["hrrp_supplemental"].releases
    assert [r.release for r in supplemental] == [f"FY{y}" for y in range(2020, 2027)]
    assert all(r.title for r in supplemental)
