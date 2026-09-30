"""The dbt project parses and declares every ingested source. Needs no data and no internet."""

import json

from hri.cli import DBT_DIR, run_dbt
from hri.ingest import load_sources


def test_dbt_project_parses_and_declares_every_ingested_source():
    assert run_dbt(["parse", "--quiet"]) == 0

    manifest = json.loads((DBT_DIR / "target" / "manifest.json").read_text())
    dbt_sources = {s["name"] for s in manifest["sources"].values() if s["source_name"] == "raw"}
    # A source added to config/sources.yaml but not to dbt (or the reverse) fails here.
    assert dbt_sources == set(load_sources())
