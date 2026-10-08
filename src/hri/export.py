"""Data for the Power BI dashboard (step 9a, D-011): the star schema as Parquet files.

Power BI reads Parquet with its built-in connector, so no database driver is needed. The export
is a copy: rerun `hri export powerbi` after `hri dbt build` or `hri model train`, then refresh
the report.

Files written to data/powerbi/:
  dim_fiscal_year, dim_hospital, dim_county        the marts, as built by dbt
  fct_hospital_year, fct_readmissions
  model_risk       FY2026 penalty-risk predictions of the chosen model (step 7), with rank
  model_drivers    why: each hospital's SHAP contribution per feature family, in percentage points
  metric_checks    every semantic-layer metric by fiscal year, computed by MetricFlow; the
                   report's Checks page compares its DAX measures with these
  manifest.json    row counts, sources and time of the export
"""

import json
from datetime import UTC, datetime
from pathlib import Path

import duckdb
import pandas as pd

from hri import PROJECT_ROOT
from hri.semantic import DB_PATH

EXPORT_DIR = PROJECT_ROOT / "data" / "powerbi"
MODEL_DIR = PROJECT_ROOT / "data" / "model"
MARTS = ("dim_fiscal_year", "dim_hospital", "dim_county", "fct_hospital_year", "fct_readmissions")
# Power BI's Parquet reader has no 128-bit integers; DuckDB uses them for some sums.
POWER_BI_TYPES = {"HUGEINT": "BIGINT", "UHUGEINT": "BIGINT"}


def _select(con: duckdb.DuckDBPyConnection, table: str) -> str:
    columns = []
    for name, kind, *_ in con.sql(f"describe marts.{table}").fetchall():
        cast = POWER_BI_TYPES.get(kind)
        columns.append(f'cast("{name}" as {cast}) as "{name}"' if cast else f'"{name}"')
    return f"select {', '.join(columns)} from marts.{table}"


def export_marts(con: duckdb.DuckDBPyConnection, out: Path) -> dict[str, int]:
    rows = {}
    for table in MARTS:
        path = (out / f"{table}.parquet").as_posix()
        con.sql(f"copy ({_select(con, table)}) to '{path}' (format parquet)")
        rows[table] = con.sql(f"select count(*) from marts.{table}").fetchone()[0]
    return rows


def model_tables() -> tuple[pd.DataFrame, pd.DataFrame]:
    """The chosen model's test-year predictions, and SHAP contributions summed by feature family
    (the same grouping as notebook 03: correlated features share credit unpredictably, a family
    total is stable). Contributions plus the model's base value add up to the prediction."""
    import joblib
    import shap

    from hri.model.data import honest_split, load_roles, load_table

    path = MODEL_DIR / "models.joblib"
    if not path.exists():
        raise FileNotFoundError(f"{path} not found; run `hri model train` first")
    bundle = joblib.load(path)
    name = f"{bundle['chosen']}_drivers"
    roles = load_roles()
    _, test = honest_split(load_table())
    test = test.reset_index(drop=True)

    pipeline = bundle["models"][name]
    drivers = list(bundle["drivers"])
    X = pipeline.named_steps["categories"].transform(test[drivers])
    explainer = shap.TreeExplainer(pipeline.named_steps["lightgbm"])
    contributions = pd.DataFrame(explainer.shap_values(X), columns=drivers)
    by_family = contributions.T.groupby(roles.groups).sum().T
    base = float(explainer.expected_value)

    predicted = pipeline.predict(test[drivers])
    risk = pd.DataFrame({
        "facility_id": test["facility_id"],
        "fiscal_year": test["fiscal_year"],
        "model": name,
        "predicted_reduction_pct": predicted,
        "actual_reduction_pct": test[roles.target],
        "is_actual_top_quarter": test["is_top_quarter_penalty"].astype(bool),
        # Percentile rank within the year: 0.9 = higher predicted penalty than 90% of hospitals.
        "predicted_rank_pct": pd.Series(predicted).rank(pct=True),
        "model_base_pct": base,
    })
    risk["is_flagged"] = risk["predicted_rank_pct"] > 0.75  # predicted top quarter, as in notebook 03
    drivers_long = (by_family.assign(facility_id=test["facility_id"], fiscal_year=test["fiscal_year"])
                    .melt(id_vars=["facility_id", "fiscal_year"], var_name="family",
                          value_name="contribution_pp"))
    return risk, drivers_long


def metric_checks() -> pd.DataFrame:
    """Every offered metric for every fiscal year, from MetricFlow (long format)."""
    from hri.semantic import SemanticLayer

    layer = SemanticLayer()
    frames = []
    for metric in layer.metrics:
        data = layer.query([metric], group_by=["fiscal_year"]).data
        frames.append(pd.DataFrame({"metric": metric, "fiscal_year": data["fiscal_year"],
                                    "expected_value": data[metric].astype(float)}))
    return pd.concat(frames, ignore_index=True)


def export_powerbi(out: Path = EXPORT_DIR, db_path: Path = DB_PATH, with_model: bool = True) -> dict:
    out.mkdir(parents=True, exist_ok=True)
    with duckdb.connect(str(db_path), read_only=True) as con:
        rows = export_marts(con, out)
    tables = {"metric_checks": metric_checks()}
    if with_model:
        tables["model_risk"], tables["model_drivers"] = model_tables()
    for name, frame in tables.items():
        frame.to_parquet(out / f"{name}.parquet", index=False)
        rows[name] = len(frame)
    modified = datetime.fromtimestamp(db_path.stat().st_mtime, UTC)
    manifest = {
        "exported_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "warehouse": str(db_path),
        "warehouse_modified": modified.isoformat(timespec="seconds"),
        "rows": rows,
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    return manifest
