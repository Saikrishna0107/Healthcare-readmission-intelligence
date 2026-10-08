"""The Power BI export (step 9a): complete, typed for Power BI, keys that relationships can use,
and model tables that agree with step 7."""

import duckdb
import numpy as np
import pandas as pd
import pytest

from hri.export import MARTS, MODEL_DIR, export_powerbi
from hri.semantic import DB_PATH

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason="no warehouse; run `hri dbt build`")
has_model = (MODEL_DIR / "models.joblib").exists()


@pytest.fixture(scope="module")
def exported(tmp_path_factory):
    out = tmp_path_factory.mktemp("powerbi")
    manifest = export_powerbi(out, with_model=has_model)
    return out, manifest


def read(out, table) -> pd.DataFrame:
    return pd.read_parquet(out / f"{table}.parquet")


def test_every_mart_is_exported_whole(exported):
    out, manifest = exported
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for table in MARTS:
            assert manifest["rows"][table] == con.sql(f"select count(*) from marts.{table}").fetchone()[0]
            assert len(read(out, table)) == manifest["rows"][table]


def test_column_types_survive_the_export(exported):
    """Counts stay whole numbers in Power BI. DuckDB writes a 128-bit integer (HUGEINT, e.g. a
    sum of counts) to Parquet as a DOUBLE unless it is cast first."""
    out, _ = exported
    integers = {"TINYINT", "SMALLINT", "INTEGER", "BIGINT", "HUGEINT", "UHUGEINT"}
    with duckdb.connect(str(DB_PATH), read_only=True) as con:
        for table in MARTS:
            path = (out / f"{table}.parquet").as_posix()
            exported_kinds = dict(r[:2] for r in con.sql(f"describe select * from '{path}'").fetchall())
            for name, kind, *_ in con.sql(f"describe marts.{table}").fetchall():
                if kind in integers:
                    assert exported_kinds[name] in integers - {"HUGEINT", "UHUGEINT"}, (table, name)
                else:
                    assert exported_kinds[name] == kind, (table, name)


def test_keys_support_one_to_many_relationships(exported):
    """Power BI needs unique keys on the 'one' side and shows facts without a match as (Blank)."""
    out, _ = exported
    hospitals, counties = read(out, "dim_hospital"), read(out, "dim_county")
    years = read(out, "dim_fiscal_year")
    assert hospitals.facility_id.is_unique and counties.county_fips.is_unique and years.fiscal_year.is_unique
    for fact in ("fct_hospital_year", "fct_readmissions", "metric_checks"):
        data = read(out, fact)
        assert data.fiscal_year.isin(years.fiscal_year).all(), fact
        if "facility_id" in data:
            assert data.facility_id.isin(hospitals.facility_id).all(), fact
    linked = hospitals.county_fips.dropna()
    assert linked.isin(counties.county_fips).all()


def test_metric_checks_cover_every_metric_and_year(exported):
    from hri.semantic import SemanticLayer

    checks = read(exported[0], "metric_checks")
    assert set(checks.metric) == set(SemanticLayer().metrics)
    assert not checks.duplicated(["metric", "fiscal_year"]).any()


@pytest.mark.skipif(not has_model, reason="no trained model; run `hri model train`")
def test_model_tables_agree_with_step_7(exported):
    out, _ = exported
    risk, drivers = read(out, "model_risk"), read(out, "model_drivers")
    step7 = pd.read_parquet(MODEL_DIR / "test_predictions.parquet")
    merged = risk.merge(step7, on=["facility_id", "fiscal_year"], validate="one_to_one")
    assert len(merged) == len(risk) == len(step7)
    assert np.allclose(merged.predicted_reduction_pct, merged[risk.model.iloc[0]])
    # SHAP is additive: base value + the family contributions = the prediction, per hospital.
    total = drivers.groupby("facility_id").contribution_pp.sum() + risk.model_base_pct.iloc[0]
    assert np.allclose(total.loc[risk.facility_id].to_numpy(), risk.predicted_reduction_pct, atol=1e-6)
    assert risk.is_flagged.mean() == pytest.approx(0.25, abs=0.01)
