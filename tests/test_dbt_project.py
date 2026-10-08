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


ROLES = {"key", "split", "target", "target_view", "feature", "variant_feature"}


def test_every_ml_column_has_a_role_and_every_feature_a_leakage_review():
    assert run_dbt(["parse", "--quiet"]) == 0

    manifest = json.loads((DBT_DIR / "target" / "manifest.json").read_text())
    nodes = manifest["nodes"].values()
    ml_models = [n for n in nodes if n["resource_type"] == "model" and n["fqn"][1] == "ml"]
    assert ml_models, "no models in dbt/models/ml"
    for model in ml_models:
        # The contract makes dbt fail if the table's columns differ from the YAML, so checking the
        # YAML here covers every column the training code can see.
        assert model["config"]["contract"]["enforced"], f"{model['name']}: contract not enforced"
        for name, column in model["columns"].items():
            meta = column["meta"]
            assert meta.get("role") in ROLES, f"{model['name']}.{name}: role {meta.get('role')!r}"
            if meta["role"] in {"feature", "variant_feature"}:
                assert meta.get("leakage", "").strip(), f"{model['name']}.{name}: no leakage review"
                assert meta.get("group"), f"{model['name']}.{name}: no feature group"
        roles = [c["meta"]["role"] for c in model["columns"].values()]
        assert roles.count("target") == 1 and roles.count("split") == 1, model["name"]
