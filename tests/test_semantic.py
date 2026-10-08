"""The semantic layer (D-025): the rules, and every metric reconciled with hand-written SQL.

The reconciliation tests need the warehouse (data/hri.duckdb, built by `hri dbt build`) and are
skipped without it. They compare what MetricFlow computes with SQL written by hand directly on
the marts, so a wrong join, filter or aggregation in the YAML shows up as a failed test.
"""

import duckdb
import pandas as pd
import pytest

from hri.cli import parse_filter
from hri.semantic import DB_PATH, Filter, SemanticLayer, SemanticLayerError, sql_literal, where_clause

# --- Rules (no warehouse needed) -------------------------------------------------------------


def test_values_are_quoted_so_they_cannot_change_the_query():
    assert sql_literal("MD") == "'MD'"
    assert sql_literal("x' or 1=1 --") == "'x'' or 1=1 --'"
    assert sql_literal(True) == "TRUE"
    assert sql_literal(3) == "3"


def test_where_clause_uses_metricflow_syntax_and_rejects_other_operators():
    assert where_clause(Filter("fiscal_year", "=", "FY2026")) == "{{ Entity('fiscal_year') }} = 'FY2026'"
    assert where_clause(Filter("hospital__state", "!=", "MD")) == "{{ Dimension('hospital__state') }} != 'MD'"
    assert (where_clause(Filter("hospital__county__state_name", "=", "Maryland"))
            == "{{ Dimension('county__state_name', entity_path=['hospital']) }} = 'Maryland'")
    with pytest.raises(SemanticLayerError):
        where_clause(Filter("hospital__state", "like", "M%"))
    with pytest.raises(SemanticLayerError):
        where_clause(Filter("hospital__state", "= 'MD' or 1=1; --", "x"))


def test_cli_filters_are_typed():
    assert parse_filter("fiscal_year=FY2026") == Filter("fiscal_year", "=", "FY2026")
    assert parse_filter("hospital_year__peer_group >= 4") == Filter("hospital_year__peer_group", ">=", 4)
    assert (parse_filter("hospital_year__is_penalized=true")
            == Filter("hospital_year__is_penalized", "=", True))
    with pytest.raises(SemanticLayerError):
        parse_filter("fiscal_year like FY%")


# --- Against the warehouse ----------------------------------------------------------------------

needs_warehouse = pytest.mark.skipif(not DB_PATH.exists(), reason="no warehouse; run `hri dbt build`")


@pytest.fixture(scope="module")
def layer():
    return SemanticLayer()


@pytest.fixture(scope="module")
def con():
    connection = duckdb.connect(str(DB_PATH), read_only=True)
    yield connection
    connection.close()


def same(metricflow: pd.DataFrame, by_hand: pd.DataFrame, keys: list[str]) -> None:
    """Same rows and values (to 1e-9), whatever the row order."""
    left = metricflow.sort_values(keys).reset_index(drop=True)
    right = by_hand[list(metricflow.columns)].sort_values(keys).reset_index(drop=True)
    pd.testing.assert_frame_equal(left, right, check_dtype=False, check_exact=False, rtol=1e-9, atol=1e-12)


# Every metric the layer offers must appear in at least one reconciliation below.
PENALTY_BY_YEAR = """
    select fiscal_year,
           count(*) filter (where in_payment_file)  as hospitals_in_payment_file,
           count(*) filter (where is_penalized)  as penalized_hospitals,
           count(*) filter (where is_penalized)::double / count(*) filter (where in_payment_file)
                                                                                         as share_penalized,
           sum(payment_reduction_pct) / count(*) filter (where in_payment_file)  as avg_payment_reduction_pct,
           sum(payment_reduction_pct) / count(*) filter (where is_penalized)
                                                         as avg_payment_reduction_among_penalized_pct,
           max(payment_reduction_pct)  as max_payment_reduction_pct,
           count(*) filter (where payment_reduction_pct >= 3)  as hospitals_at_max_penalty,
           avg(recommend_score)  as avg_recommend_score,
           avg(overall_rating_score)  as avg_overall_rating_score,
           avg(care_transition_score)  as avg_care_transition_score,
           avg(discharge_information_score)                              as avg_discharge_information_score
    from marts.fct_hospital_year
    where fiscal_year >= 'FY2020'      -- FY 2019 has no payment file (ratios would divide by zero)
    group by fiscal_year
"""

RESULTS_BY_CONDITION = """
    select fiscal_year, condition as readmission_result__condition,
           count(excess_readmission_ratio)                                   as scored_results,
           avg(excess_readmission_ratio)                                     as avg_excess_readmission_ratio,
           count(*) filter (where excess_readmission_ratio > 1)              as results_worse_than_expected,
           count(*) filter (where excess_readmission_ratio > 1)::double / count(excess_readmission_ratio)
  as share_results_worse_than_expected,
           count(*) filter (where counts_toward_penalty)  as results_counting_toward_penalty,
           sum(eligible_discharges)                                          as eligible_discharges
    from marts.fct_readmissions
    where fiscal_year in ('FY2023', 'FY2026')
    group by all
"""


@needs_warehouse
def test_penalty_and_survey_metrics_match_hand_written_sql(layer, con):
    metrics = [m for m in con.sql(PENALTY_BY_YEAR).columns if m != "fiscal_year"]
    got = layer.query(metrics, group_by=["fiscal_year"], filters=[Filter("fiscal_year", ">=", "FY2020")]).data
    assert len(got) == 7
    same(got, con.sql(PENALTY_BY_YEAR).df(), ["fiscal_year"])


@needs_warehouse
def test_readmission_metrics_match_hand_written_sql(layer, con):
    metrics = [m for m in con.sql(RESULTS_BY_CONDITION).columns
               if m not in ("fiscal_year", "readmission_result__condition")]
    got = layer.query(metrics, group_by=["fiscal_year", "readmission_result__condition"],
                      filters=[Filter("fiscal_year", "=", "FY2023")]).data
    hand = con.sql(RESULTS_BY_CONDITION).df().query("fiscal_year == 'FY2023'")
    # FY 2023 has pneumonia results without any payment-file data (CMS left PN out that year):
    # the hand SQL gives NULL eligible discharges there, and so must MetricFlow.
    assert hand.loc[hand.readmission_result__condition == "PN", "eligible_discharges"].isna().all()
    same(got, hand, ["readmission_result__condition"])


@needs_warehouse
def test_joins_to_hospitals_and_counties_match_hand_written_sql(layer, con):
    got = layer.query(["penalized_hospitals", "share_penalized"], group_by=["hospital__state"],
                      filters=[Filter("fiscal_year", "=", "FY2026")]).data
    hand = con.sql("""
        select h.state as hospital__state,
               count(*) filter (where y.is_penalized)  as penalized_hospitals,
               count(*) filter (where y.is_penalized)::double / count(*) filter (where y.in_payment_file)
                                                                                        as share_penalized
        from marts.fct_hospital_year y join marts.dim_hospital h using (facility_id)
        where y.fiscal_year = 'FY2026'
        group by all
        having count(*) filter (where y.in_payment_file) > 0
    """).df()
    same(got.dropna(subset=["share_penalized"]), hand, ["hospital__state"])

    got = layer.query(["avg_excess_readmission_ratio"], group_by=["hospital__county__state_name"],
                      filters=[Filter("fiscal_year", "=", "FY2026"),
                               Filter("hospital__county__state_name", "=", "Maryland")]).data
    hand = con.sql("""
        select c.state_name as hospital__county__state_name, avg(r.excess_readmission_ratio)
               as avg_excess_readmission_ratio
        from marts.fct_readmissions r
        join marts.dim_hospital h using (facility_id)
        join marts.dim_county c on c.county_fips = h.county_fips
        where r.fiscal_year = 'FY2026' and c.state_name = 'Maryland'
        group by all
    """).df()
    same(got, hand, ["hospital__county__state_name"])


@needs_warehouse
def test_every_offered_metric_is_reconciled(layer, con):
    reconciled = set(con.sql(PENALTY_BY_YEAR).columns) | set(con.sql(RESULTS_BY_CONDITION).columns)
    assert set(layer.metrics) <= reconciled, set(layer.metrics) - reconciled


@needs_warehouse
def test_building_blocks_are_hidden_and_rules_enforced(layer):
    assert "payment_reduction_pct_total" not in layer.metrics
    assert "excess_readmission_ratio_total" not in layer.metrics
    with pytest.raises(SemanticLayerError, match="Unknown metric"):
        layer.query(["payment_reduction_pct_total"])
    with pytest.raises(SemanticLayerError, match="cannot be used"):
        layer.query(["share_penalized"], group_by=["readmission_result__condition"])
    with pytest.raises(SemanticLayerError, match="order by"):
        layer.query(["share_penalized"], order_by=["-hospital__state"])
    with pytest.raises(SemanticLayerError, match="limit"):
        layer.query(["share_penalized"], limit=100_000)


@needs_warehouse
def test_the_warehouse_is_read_only(layer):
    with pytest.raises(Exception, match="read-only|READ_ONLY|read only"):
        layer._config.sql_client.execute("create table hri.marts.should_not_exist as select 1 as x")
