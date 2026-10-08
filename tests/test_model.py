"""The model code: split guard, metrics, preprocessing and grouped folds. Synthetic data only,
so these run without the warehouse."""

import numpy as np
import pandas as pd
import pytest

from hri.model import SplitError, honest_split, load_roles
from hri.model.metrics import bootstrap_difference, bootstrap_interval, within_year_metrics, year_metrics
from hri.model.models import earlier_penalty, make_linear, split_feature_types
from hri.model.train import grouped_folds


def hospital_years(n_hospitals: int = 200, years=("FY2020", "FY2021", "FY2026"), seed=0) -> pd.DataFrame:
    """A small table shaped like ml_penalty_features: one driver that raises the penalty."""
    rng = np.random.default_rng(seed)
    rows = []
    for fy in years:
        driver = rng.normal(size=n_hospitals)
        reduction = np.clip(0.4 + 0.3 * driver + rng.normal(scale=0.3, size=n_hospitals), 0, 3)
        rows.append(pd.DataFrame({
            "facility_id": [f"{i:06d}" for i in range(n_hospitals)],
            "fiscal_year": fy,
            "split": "test" if fy == years[-1] else "train",
            "payment_reduction_pct": reduction,
            "driver": driver,
            "ownership": rng.choice(["Proprietary", "Voluntary non-profit - Private"], n_hospitals),
        }))
    df = pd.concat(rows, ignore_index=True)
    df["is_penalized"] = df.payment_reduction_pct > 0
    top_quarter_from = df.groupby("fiscal_year").payment_reduction_pct.transform(lambda s: s.quantile(0.75))
    df["is_top_quarter_penalty"] = df.payment_reduction_pct >= top_quarter_from
    return df


def test_roles_come_from_the_dbt_yaml_and_never_mix():
    roles = load_roles()
    assert roles.target == "payment_reduction_pct"
    assert roles.split == "split"
    assert roles.features and roles.variant_features
    outcome_columns = {roles.target, *roles.target_views, roles.split, *roles.keys}
    # The main model's features hold no target, key or prior-results column.
    assert not outcome_columns & set(roles.features)
    assert not set(roles.variant_features) & set(roles.features)
    assert all(f in roles.groups for f in roles.features + roles.variant_features)


def test_honest_split_returns_the_marked_rows():
    df = hospital_years()
    train, test = honest_split(df)
    assert set(train.fiscal_year) == {"FY2020", "FY2021"} and set(test.fiscal_year) == {"FY2026"}


@pytest.mark.parametrize("broken", ["two_test_years", "year_on_both_sides"])
def test_honest_split_refuses_an_overlapping_table(broken):
    df = hospital_years()
    if broken == "two_test_years":
        df.loc[df.fiscal_year == "FY2021", "split"] = "test"
    else:
        df.loc[(df.fiscal_year == "FY2026") & (df.facility_id == "000001"), "split"] = "train"
    with pytest.raises(SplitError):
        honest_split(df)


def test_metrics_for_perfect_constant_and_reversed_scores():
    year = hospital_years(years=("FY2026",))
    perfect = year_metrics(year, year.payment_reduction_pct.to_numpy())
    assert perfect["auc_top_quarter"] == pytest.approx(1.0) and perfect["spearman"] == pytest.approx(1.0)
    assert perfect["mae_pct"] == 0

    constant = year_metrics(year, np.full(len(year), 0.5))
    assert constant["auc_top_quarter"] == 0.5 and np.isnan(constant["spearman"])

    reversed_ = year_metrics(year, -year.payment_reduction_pct.to_numpy())
    assert reversed_["auc_top_quarter"] == pytest.approx(0.0)


def test_within_year_metrics_ignore_differences_between_years():
    # A score that is perfect inside each year but shifted by year: pooled it would be worse,
    # within each year it is still perfect.
    df = hospital_years()
    shift = df.fiscal_year.map({"FY2020": 10.0, "FY2021": -10.0, "FY2026": 0.0})
    result = within_year_metrics(df, df.payment_reduction_pct + shift)
    assert result["auc_top_quarter"] == pytest.approx(1.0)
    assert result["spearman"] == pytest.approx(1.0)


def test_bootstrap_interval_is_reproducible_and_brackets_the_estimate():
    year = hospital_years(years=("FY2026",))
    score = year.driver.to_numpy()
    first = bootstrap_interval(year, score, n=200, seed=1)
    assert first == bootstrap_interval(year, score, n=200, seed=1)
    point = year_metrics(year, score)
    for metric, (low, high) in first.items():
        assert low <= point[metric] <= high
    with pytest.raises(ValueError):
        bootstrap_interval(hospital_years(), hospital_years().driver.to_numpy(), n=10)


def test_paired_difference_sees_a_better_score():
    year = hospital_years(years=("FY2026",))
    noise = np.random.default_rng(2).normal(scale=2, size=len(year))
    result = bootstrap_difference(year, year.driver.to_numpy(), year.driver.to_numpy() + noise, n=200)
    assert result["difference"] > 0 and result["interval_95"][0] > 0


def test_linear_model_handles_missing_values_and_unseen_categories():
    df = hospital_years()
    train, test = honest_split(df)
    train = train.copy()
    train.loc[train.index[:20], "driver"] = np.nan
    test = test.assign(ownership="Tribal")  # never seen in training
    numeric, categorical = split_feature_types(train, ("driver", "ownership"))
    assert numeric == ["driver"] and categorical == ["ownership"]
    model = make_linear(numeric, categorical, alpha=1.0)
    model.fit(train[["driver", "ownership"]], train.payment_reduction_pct)
    predictions = model.predict(test[["driver", "ownership"]])
    assert np.isfinite(predictions).all()
    assert year_metrics(test, predictions)["auc_top_quarter"] > 0.75  # the driver carries real signal


def test_grouped_folds_never_put_a_hospital_on_both_sides():
    df = hospital_years()
    for fit_idx, val_idx in grouped_folds(df):
        assert not set(df.facility_id.iloc[fit_idx]) & set(df.facility_id.iloc[val_idx])


def test_earlier_penalty_looks_back_by_fiscal_year():
    table = pd.DataFrame({
        "facility_id": ["A", "A", "B"],
        "fiscal_year": ["FY2023", "FY2026", "FY2026"],
        "payment_reduction_pct": [0.9, 0.2, 0.4],
    })
    test = table[table.fiscal_year == "FY2026"]
    assert earlier_penalty(table, test, 3, "payment_reduction_pct", fill=0.33).tolist() == [0.9, 0.33]
