"""The Power BI semantic model as TMDL text (step 9b, D-011).

`hri powerbi init` writes the tables, relationships, measures and the DataFolder parameter into
the PBIP project in powerbi/ (created once from Power BI Desktop with File > Save as > .pbip).
Column lists come from the exported Parquet files, so the model matches the export.

This is a starting point, run once. After that Power BI Desktop rewrites these files whenever
the project is saved, and the files in git are the source of truth. tests/test_powerbi.py checks
them: every semantic-layer metric has exactly one measure, tagged with its MetricFlow name.

Measures repeat the MetricFlow definitions (dbt/models/semantic) in DAX. The Checks page in the
report compares them with MetricFlow's values (metric_checks) for every fiscal year.
"""

import uuid
from dataclasses import dataclass
from pathlib import Path

import pyarrow.parquet as pq

from hri import PROJECT_ROOT
from hri.export import EXPORT_DIR

PROJECT_DIR = PROJECT_ROOT / "powerbi"
MODEL_DIR = PROJECT_DIR / "HRI.SemanticModel" / "definition"

# Power BI table name -> (exported file, description)
TABLES = {
    "Fiscal year": ("dim_fiscal_year", "One row per HRRP fiscal year (FY2019-FY2026) with its "
                                       "readmission and survey periods."),
    "Hospital": ("dim_hospital", "One row per hospital in any CMS source, with its county link."),
    "County": ("dim_county", "One row per US county with CDC PLACES community health measures "
                             "(age-adjusted %)."),
    "Hospital year": ("fct_hospital_year", "One row per hospital and fiscal year: HRRP payment "
                                           "reduction, peer group and patient survey scores."),
    "Readmission results": ("fct_readmissions", "One row per hospital, condition and fiscal year: "
                                                "Excess Readmission Ratio and whether it counted "
                                                "toward the penalty."),
    "Model risk": ("model_risk", "FY2026 penalty-risk prediction of the chosen model (step 7) "
                                 "for each hospital."),
    "Model drivers": ("model_drivers", "Why the model predicts what it does: each hospital's SHAP "
                                       "contribution per feature family, in percentage points."),
    "Metric checks": ("metric_checks", "Every semantic-layer metric by fiscal year as MetricFlow "
                                       "computes it; the Checks page compares the measures with it."),
}

# (many side table, column, one side table, column); every filter flows from the one side.
RELATIONSHIPS = [
    ("Hospital year", "facility_id", "Hospital", "facility_id"),
    ("Hospital year", "fiscal_year", "Fiscal year", "fiscal_year"),
    ("Readmission results", "facility_id", "Hospital", "facility_id"),
    ("Readmission results", "fiscal_year", "Fiscal year", "fiscal_year"),
    ("Hospital", "county_fips", "County", "county_fips"),
    ("Model risk", "facility_id", "Hospital", "facility_id"),
    ("Model risk", "fiscal_year", "Fiscal year", "fiscal_year"),
    ("Model drivers", "facility_id", "Hospital", "facility_id"),
    ("Model drivers", "fiscal_year", "Fiscal year", "fiscal_year"),
    ("Metric checks", "fiscal_year", "Fiscal year", "fiscal_year"),
]

COUNT = "#,0"
SHARE = "0.0%"
PERCENT_POINTS = '0.00"%"'  # the value is already in percent: 0.34 means 0.34%
RATIO = "0.0000"
SCORE = "0.0"


@dataclass(frozen=True)
class Measure:
    table: str
    name: str
    dax: str
    format: str
    folder: str
    description: str
    metric: str | None = None  # the MetricFlow metric it repeats


def _true(table: str, column: str) -> str:
    return f"CALCULATE(COUNTROWS('{table}'), KEEPFILTERS('{table}'[{column}] = TRUE()))"


HY, RR = "Hospital year", "Readmission results"
METRIC_MEASURES = [
    Measure(HY, "Hospitals in the payment file", _true(HY, "in_payment_file"), COUNT, "Penalty",
            "Number of hospitals in the HRRP payment file of the fiscal year.", "hospitals_in_payment_file"),
    Measure(HY, "Penalized hospitals", _true(HY, "is_penalized"), COUNT, "Penalty",
            "Hospitals whose Medicare payments were reduced (reduction above 0%).", "penalized_hospitals"),
    Measure(HY, "Share of hospitals penalized",
            "DIVIDE([Penalized hospitals], [Hospitals in the payment file])", SHARE, "Penalty",
            "Penalized hospitals / hospitals in the payment file.", "share_penalized"),
    Measure(HY, "Average payment reduction (all hospitals in the file)",
            f"DIVIDE(SUM('{HY}'[payment_reduction_pct]), [Hospitals in the payment file])", PERCENT_POINTS,
            "Penalty", "Average reduction in % of Medicare base payments over ALL hospitals in the "
                       "payment file, unpenalized ones counted as 0%.", "avg_payment_reduction_pct"),
    Measure(HY, "Average payment reduction (penalized hospitals only)",
            f"DIVIDE(SUM('{HY}'[payment_reduction_pct]), [Penalized hospitals])", PERCENT_POINTS, "Penalty",
            "Average reduction in % over penalized hospitals only.",
            "avg_payment_reduction_among_penalized_pct"),
    Measure(HY, "Largest payment reduction", f"MAX('{HY}'[payment_reduction_pct])", PERCENT_POINTS,
            "Penalty", "Largest reduction in % (the program caps it at 3%).", "max_payment_reduction_pct"),
    Measure(HY, "Hospitals at the 3% cap",
            f"CALCULATE(COUNTROWS('{HY}'), KEEPFILTERS('{HY}'[payment_reduction_pct] >= 3))", COUNT,
            "Penalty", "Hospitals whose reduction reached the 3% maximum.", "hospitals_at_max_penalty"),
    Measure(RR, "Scored results", f"COUNT('{RR}'[excess_readmission_ratio])", COUNT, "Readmissions",
            "Hospital-condition results with a published Excess Readmission Ratio.", "scored_results"),
    Measure(RR, "Average Excess Readmission Ratio",
            f"DIVIDE(SUM('{RR}'[excess_readmission_ratio]), [Scored results])", RATIO, "Readmissions",
            "Simple average of published ratios; above 1.0 = more readmissions than expected.",
            "avg_excess_readmission_ratio"),
    Measure(RR, "Results worse than expected",
            f"CALCULATE(COUNTROWS('{RR}'), KEEPFILTERS('{RR}'[excess_readmission_ratio] > 1))", COUNT,
            "Readmissions", "Results with an Excess Readmission Ratio above 1.0.",
            "results_worse_than_expected"),
    Measure(RR, "Share of results worse than expected",
            "DIVIDE([Results worse than expected], [Scored results])", SHARE, "Readmissions",
            "Results above 1.0 / results with a published ratio.", "share_results_worse_than_expected"),
    Measure(RR, "Results counting toward the penalty", _true(RR, "counts_toward_penalty"), COUNT,
            "Readmissions", "Results above the peer group median with at least 25 eligible discharges.",
            "results_counting_toward_penalty"),
    Measure(RR, "Eligible discharges", f"SUM('{RR}'[eligible_discharges])", COUNT, "Readmissions",
            "Medicare discharges eligible for the readmission measures (payment file).",
            "eligible_discharges"),
    Measure(HY, "Average would-recommend score", f"AVERAGE('{HY}'[recommend_score])", SCORE,
            "Patient survey", "Average 'would recommend the hospital' linear mean score (0-100).",
            "avg_recommend_score"),
    Measure(HY, "Average overall rating score", f"AVERAGE('{HY}'[overall_rating_score])", SCORE,
            "Patient survey", "Average overall hospital rating linear mean score (0-100).",
            "avg_overall_rating_score"),
    Measure(HY, "Average care transition score", f"AVERAGE('{HY}'[care_transition_score])", SCORE,
            "Patient survey", "Average care transition linear mean score (0-100).",
            "avg_care_transition_score"),
    Measure(HY, "Average discharge information score", f"AVERAGE('{HY}'[discharge_information_score])",
            SCORE, "Patient survey", "Average discharge information linear mean score (0-100).",
            "avg_discharge_information_score"),
]

MR, MD, MC = "Model risk", "Model drivers", "Metric checks"
MODEL_MEASURES = [
    Measure(MR, "Hospitals flagged", _true(MR, "is_flagged"), COUNT, "Model",
            "Hospitals in the model's predicted top quarter of FY2026 penalties."),
    Measure(MR, "Flagged hospitals actually in the top quarter",
            f"DIVIDE(CALCULATE(COUNTROWS('{MR}'), KEEPFILTERS('{MR}'[is_flagged] = TRUE()), "
            f"KEEPFILTERS('{MR}'[is_actual_top_quarter] = TRUE())), [Hospitals flagged])", SHARE, "Model",
            "Of the flagged hospitals, the share whose real FY2026 penalty was in the top quarter "
            "(about 0.50; 0.25 would be chance)."),
    Measure(MR, "Predicted payment reduction", f"AVERAGE('{MR}'[predicted_reduction_pct])", PERCENT_POINTS,
            "Model", "Average predicted FY2026 payment reduction in %."),
    Measure(MR, "Actual payment reduction (model rows)", f"AVERAGE('{MR}'[actual_reduction_pct])",
            PERCENT_POINTS, "Model", "Average real FY2026 payment reduction in %, same hospitals."),
    Measure(MD, "Driver contribution", f"SUM('{MD}'[contribution_pp])", '+0.00;-0.00;0.00', "Model",
            "SHAP contribution in percentage points: how much a feature family raises (+) or lowers "
            "(-) the hospital's predicted reduction from the average."),
]


def _check_value() -> str:
    branches = "\n".join(f'    "{m.metric}", [{m.name}],' for m in METRIC_MEASURES)
    return (f"VAR metric = SELECTEDVALUE('{MC}'[metric])\n"
            "RETURN\n"
            f"CALCULATE(\n  SWITCH(metric,\n{branches}\n    BLANK()\n  ),\n"
            f"  TREATAS(VALUES('{MC}'[fiscal_year]), 'Fiscal year'[fiscal_year])\n)")


CHECK_MEASURES = [
    Measure(MC, "Check: MetricFlow value", f"SUM('{MC}'[expected_value])", "0.######", "Checks",
            "The metric as the semantic layer (MetricFlow) computes it."),
    Measure(MC, "Check: Power BI value", _check_value(), "0.######", "Checks",
            "The same metric from this report's DAX measure, for the same fiscal year."),
    Measure(MC, "Check: difference",
            "ABS(COALESCE([Check: Power BI value], 0) - COALESCE([Check: MetricFlow value], 0))",
            "0.##########", "Checks",
            "Absolute difference; a blank and 0 count as equal (Power BI shows a count of 0 as blank)."),
    Measure(MC, "Check: mismatches",
            f"SUMX('{MC}', IF([Check: difference] > 1E-6 * MAX(1, ABS([Check: MetricFlow value])), 1, 0))",
            COUNT, "Checks", "Metric-years where Power BI and MetricFlow disagree. Must be 0."),
]

MEASURES = METRIC_MEASURES + MODEL_MEASURES + CHECK_MEASURES

ARROW_TYPES = {"string": "string", "large_string": "string", "bool": "boolean", "double": "double",
               "float": "double", "int8": "int64", "int16": "int64", "int32": "int64", "int64": "int64",
               "date32[day]": "dateTime"}


def quote(name: str) -> str:
    """A TMDL object name, quoted when it has spaces or symbols."""
    return name if name.replace("_", "").isalnum() else "'" + name.replace("'", "''") + "'"


def _description(text: str, indent: str) -> str:
    return f"{indent}/// {text}\n"


def table_tmdl(table: str, data_folder: Path = EXPORT_DIR) -> str:
    file, description = TABLES[table]
    schema = pq.read_schema(data_folder / f"{file}.parquet")
    out = _description(description, "") + f"table {quote(table)}\n\n"
    for m in (m for m in MEASURES if m.table == table):
        dax = m.dax.splitlines()
        out += _description(m.description, "\t")
        if len(dax) == 1:
            out += f"\tmeasure {quote(m.name)} = {dax[0]}\n"
        else:
            out += f"\tmeasure {quote(m.name)} =\n" + "".join(f"\t\t\t{line}\n" for line in dax)
        out += f"\t\tformatString: {m.format}\n\t\tdisplayFolder: {m.folder}\n"
        if m.metric:
            out += f"\n\t\tannotation MetricFlowMetric = {m.metric}\n"
        out += "\n"
    for field in schema:
        kind = ARROW_TYPES.get(str(field.type))
        if kind is None and str(field.type).startswith("timestamp"):
            kind = "dateTime"
        if kind is None:
            raise TypeError(f"{file}.{field.name}: no Power BI type for {field.type}")
        out += f"\tcolumn {quote(field.name)}\n\t\tdataType: {kind}\n"
        if kind == "dateTime":
            out += "\t\tformatString: yyyy-mm-dd\n"
        # Nothing is summed by default: a sum of percentages or ratios is meaningless, so totals
        # come only from the measures above.
        out += f"\t\tsummarizeBy: none\n\t\tsourceColumn: {field.name}\n\n"
    out += (f"\tpartition {quote(table)} = m\n\t\tmode: import\n\t\tsource =\n"
            f"\t\t\t\tlet\n"
            f"\t\t\t\t    Source = Parquet.Document(File.Contents(DataFolder & \"{file}.parquet\"))\n"
            f"\t\t\t\tin\n\t\t\t\t    Source\n\n")
    return out


def relationships_tmdl() -> str:
    out = ""
    for many, many_col, one, one_col in RELATIONSHIPS:
        rid = uuid.uuid5(uuid.NAMESPACE_URL, f"hri/{many}.{many_col}->{one}.{one_col}")
        out += (f"relationship {rid}\n\tfromColumn: {quote(many)}.{quote(many_col)}\n"
                f"\ttoColumn: {quote(one)}.{quote(one_col)}\n\n")
    return out


def expressions_tmdl(data_folder: Path = EXPORT_DIR) -> str:
    folder = str(data_folder).rstrip("\\/") + "\\"
    return (_description("Folder with the Parquet files from `hri export powerbi` (ends with a backslash). "
                         "Change it in Transform data > Edit parameters.", "")
            + f'expression DataFolder = "{folder}" meta [IsParameterQuery=true, Type="Text", '
              'IsParameterQueryRequired=true]\n\n\tannotation PBI_ResultType = Text\n\n')


def write_model(model_dir: Path = MODEL_DIR, data_folder: Path = EXPORT_DIR) -> list[Path]:
    """Write the tables, relationships and parameter. model.tmdl gets a `ref table` line per table
    (Desktop keeps the table order from these)."""
    if not (model_dir / "model.tmdl").exists():
        raise FileNotFoundError(f"{model_dir / 'model.tmdl'} not found: create the project first "
                                "(Power BI Desktop: File > Save as > Power BI project)")
    written: list[Path] = []

    def write(path: Path, text: str) -> None:
        path.write_text(text, encoding="utf-8", newline="\r\n")  # line endings as Desktop writes them
        written.append(path)

    (model_dir / "tables").mkdir(exist_ok=True)
    for table in TABLES:
        write(model_dir / "tables" / f"{table}.tmdl", table_tmdl(table, data_folder))
    write(model_dir / "relationships.tmdl", relationships_tmdl())
    write(model_dir / "expressions.tmdl", expressions_tmdl(data_folder))
    model = (model_dir / "model.tmdl").read_text(encoding="utf-8")
    # Auto date/time would add a hidden calendar table per date column; Fiscal year is the time axis.
    updated = model.replace("__PBI_TimeIntelligenceEnabled = 1", "__PBI_TimeIntelligenceEnabled = 0")
    missing = [t for t in TABLES if f"ref table {quote(t)}\n" not in updated]
    if missing:
        updated = updated.rstrip("\n") + "\n\n" + "".join(f"ref table {quote(t)}\n" for t in missing)
    if updated != model:
        write(model_dir / "model.tmdl", updated)
    return written
