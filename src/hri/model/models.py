"""The baselines and the linear model of step 7b (D-009, D-024).

Baselines answer "is the model better than doing nothing clever?":
- training_mean: every hospital gets the training average. Ranks nothing (AUC 0.5); its level
  error shows how much the year-to-year shift alone costs.
- penalty_3_years_earlier: the hospital's own penalty from the fiscal year whose period ends
  just before this one starts. No shared patients, so a fair "history repeats" baseline.
- penalty_1_year_earlier: reported as a reference only. Its period shares two thirds of the
  patients with the year it scores, so it shows how good a score looks with overlap.

The linear model is ridge regression: least squares with a penalty on large coefficients, which
keeps correlated survey scores from getting large opposite-signed weights.
"""

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.pipeline import Pipeline, make_pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler


def split_feature_types(df: pd.DataFrame, features: tuple[str, ...]) -> tuple[list[str], list[str]]:
    """Text columns are categories (ownership); everything else is numeric (booleans as 0/1)."""
    categorical = [f for f in features if not pd.api.types.is_numeric_dtype(df[f])]
    return [f for f in features if f not in categorical], categorical


def make_linear(numeric: list[str], categorical: list[str], alpha: float = 1.0) -> Pipeline:
    """Ridge regression with the preprocessing it needs, fitted on training rows only.

    - Missing numbers are filled with the training median, plus a 0/1 "was missing" column, so
      the model can learn that a missing survey (small hospital) means something.
    - Numbers are standardized, so ridge penalizes all coefficients on the same scale and the
      coefficients can be compared ("one standard deviation more of X").
    - Categories become 0/1 columns; a category never seen in training gets all zeros.
    """
    preprocess = ColumnTransformer(
        [
            ("numeric", make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler()),
             numeric),
            ("categorical", make_pipeline(
                SimpleImputer(strategy="constant", fill_value="missing"),
                OneHotEncoder(handle_unknown="ignore"),
            ), categorical),
        ],
        verbose_feature_names_out=False,
    )
    return Pipeline([("preprocess", preprocess), ("ridge", Ridge(alpha=alpha))])


def linear_coefficients(model: Pipeline) -> pd.DataFrame:
    """Standardized coefficients: change in predicted reduction (percentage points) per standard
    deviation of a numeric feature, or for being in a category."""
    names = model.named_steps["preprocess"].get_feature_names_out()
    coef = model.named_steps["ridge"].coef_
    return (pd.DataFrame({"feature": names, "coefficient": coef})
            .assign(size=lambda d: d.coefficient.abs())
            .sort_values("size", ascending=False)
            .drop(columns="size")
            .reset_index(drop=True))


def training_mean(train: pd.DataFrame, test: pd.DataFrame, target: str) -> np.ndarray:
    return np.full(len(test), train[target].mean())


def earlier_penalty(table: pd.DataFrame, test: pd.DataFrame, years_earlier: int, target: str,
                    fill: float) -> np.ndarray:
    """The hospital's own reduction `years_earlier` fiscal years before; `fill` where it has none
    (new hospital, or not in that year's file)."""
    earlier = table[["facility_id", "fiscal_year", target]].assign(
        fiscal_year=lambda d: "FY" + (d.fiscal_year.str[2:].astype(int) + years_earlier).astype(str)
    )
    keys = ["facility_id", "fiscal_year"]
    merged = test[keys].merge(earlier, on=keys, how="left")
    return merged[target].fillna(fill).to_numpy()
