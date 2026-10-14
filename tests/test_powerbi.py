"""The Power BI semantic model (step 9b): one measure per semantic-layer metric, tagged with the
metric's name, and tables that read the exported files. Runs on the TMDL text in git, so it
also checks the model after Power BI Desktop has rewritten it."""

import json
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


PAGES_DIR = MODEL_DIR.parents[1] / "HRI.Report" / "definition" / "pages"
needs_report = pytest.mark.skipif(not PAGES_DIR.exists(), reason="no report pages yet")


def report_pages() -> dict[str, dict]:
    pages = {}
    for path in PAGES_DIR.glob("*/page.json"):
        page = json.loads(path.read_text(encoding="utf-8"))
        files = path.parent.glob("visuals/*/visual.json")
        visuals = [json.loads(v.read_text(encoding="utf-8")) for v in files]
        pages[page["displayName"]] = {"page": page, "visuals": visuals,
                                      "types": {v["name"]: v["visual"]["visualType"] for v in visuals}}
    return pages


@needs_report
def test_the_report_has_its_pages_and_the_checks_card():
    pages = report_pages()
    assert {"Penalty Overview", "Conditions", "Hospital Detail", "Model Risk", "Checks"} <= set(pages)
    checks = json.dumps(pages["Checks"]["visuals"])
    assert '"Property": "Check: mismatches"' in checks


@needs_report
def test_hospital_detail_is_a_drill_through_on_the_hospital_id():
    binding = report_pages()["Hospital Detail"]["page"]["pageBinding"]
    assert binding["type"] == "Drillthrough"
    assert binding["acceptsFilterContext"] == "None"  # every year, not only the slicer's
    fields = [p["fieldExpr"]["Column"] for p in binding["parameters"]]
    bound = [(f["Expression"]["SourceRef"]["Entity"], f["Property"]) for f in fields]
    assert bound == [("Hospital", "facility_id")]


@needs_report
def test_trend_visuals_ignore_the_year_slicer():
    """A trend over years filtered to one year shows a single dot."""
    for name, target in (("Penalty Overview", "lineChart"), ("Conditions", "pivotTable")):
        page = report_pages()[name]
        types = page["types"]
        ignored = {(types.get(i["source"]), types.get(i["target"]))
                   for i in page["page"].get("visualInteractions", []) if i["type"] == "NoFilter"}
        assert ("slicer", target) in ignored, name
