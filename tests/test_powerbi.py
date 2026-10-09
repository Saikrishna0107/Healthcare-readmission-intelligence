"""The Power BI semantic model (step 9b): one measure per semantic-layer metric, tagged with the
metric's name, and tables that read the exported files. Runs on the TMDL text in git, so it
also checks the model after Power BI Desktop has rewritten it."""

import re

import pytest
import yaml

from hri import PROJECT_ROOT
from hri.powerbi import METRIC_MEASURES, MODEL_DIR, TABLES, relationships_tmdl

METRICS_YAML = PROJECT_ROOT / "dbt" / "models" / "semantic" / "_metrics.yml"


def offered_metrics() -> set[str]:
    """The metrics the semantic layer offers (building blocks marked meta.agent: hidden left out)."""
    metrics = yaml.safe_load(METRICS_YAML.read_text(encoding="utf-8"))["metrics"]
    return {m["name"] for m in metrics if (m.get("config") or {}).get("meta", {}).get("agent") != "hidden"}


def test_the_generator_has_one_measure_per_metric():
    tagged = [m.metric for m in METRIC_MEASURES]
    assert sorted(tagged) == sorted(offered_metrics())


def test_every_relationship_joins_existing_tables():
    for line in relationships_tmdl().splitlines():
        if "Column:" in line:
            table = line.split(": ", 1)[1].rsplit(".", 1)[0].strip("'")
            assert table in TABLES, line


needs_project = pytest.mark.skipif(not (MODEL_DIR / "tables").exists(), reason="no Power BI project yet")


@needs_project
def test_the_saved_model_tags_every_metric_once():
    text = "".join(p.read_text(encoding="utf-8") for p in (MODEL_DIR / "tables").glob("*.tmdl"))
    tagged = re.findall(r"annotation MetricFlowMetric = (\w+)", text)
    assert sorted(tagged) == sorted(offered_metrics())
    for metric in offered_metrics():  # the Checks page covers every metric
        assert f'"{metric}", [' in text, metric


@needs_project
def test_the_saved_model_reads_every_exported_table():
    for table, (file, _) in TABLES.items():
        text = (MODEL_DIR / "tables" / f"{table}.tmdl").read_text(encoding="utf-8")
        assert f'DataFolder & "{file}.parquet"' in text, table
