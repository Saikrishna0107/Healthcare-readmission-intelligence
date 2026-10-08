"""Load the modeling table and the column roles declared for it in dbt (D-024).

The feature list is not written in Python: it is read from dbt/models/ml/_ml.yml, where every
column has a role and every feature a leakage review. A column becomes a model input only by
being declared a feature there.
"""

from dataclasses import dataclass
from pathlib import Path

import duckdb
import pandas as pd
import yaml

from hri import PROJECT_ROOT

DB_PATH = PROJECT_ROOT / "data" / "hri.duckdb"
ML_SPEC = PROJECT_ROOT / "dbt" / "models" / "ml" / "_ml.yml"
TABLE = "ml_penalty_features"


@dataclass(frozen=True)
class Roles:
    keys: tuple[str, ...]
    split: str
    target: str
    target_views: tuple[str, ...]
    features: tuple[str, ...]  # drivers: the main model's inputs
    variant_features: tuple[str, ...]  # results from an earlier, non-overlapping period
    groups: dict[str, str]  # feature -> group (volume, survey, county, ...)


def load_roles(spec_path: Path = ML_SPEC, model: str = TABLE) -> Roles:
    spec = yaml.safe_load(spec_path.read_text(encoding="utf-8"))
    columns = next(m for m in spec["models"] if m["name"] == model)["columns"]
    meta = {c["name"]: c["config"]["meta"] for c in columns}

    def having(role: str) -> tuple[str, ...]:
        return tuple(name for name, m in meta.items() if m["role"] == role)

    (split,) = having("split")
    (target,) = having("target")
    return Roles(
        keys=having("key"),
        split=split,
        target=target,
        target_views=having("target_view"),
        features=having("feature"),
        variant_features=having("variant_feature"),
        groups={name: m["group"] for name, m in meta.items() if "group" in m},
    )


def load_table(db_path: Path = DB_PATH) -> pd.DataFrame:
    if not db_path.exists():
        raise FileNotFoundError(f"{db_path} not found. Run: hri ingest, then hri dbt build")
    with duckdb.connect(str(db_path), read_only=True) as con:
        df = con.execute(f"select * from ml.{TABLE} order by fiscal_year, facility_id").df()
    # DuckDB returns nullable integer and boolean columns as pandas extension types; scikit-learn
    # wants plain floats with NaN for missing values.
    for column in df.columns:
        if df[column].dtype.name in {"bool", "boolean", "Int8", "Int16", "Int32", "Int64"}:
            df[column] = df[column].astype("float64")
    return df


class SplitError(Exception):
    """The table's split would let training and test data overlap."""


def honest_split(df: pd.DataFrame, split: str = "split") -> tuple[pd.DataFrame, pd.DataFrame]:
    """Training and test rows as marked in dbt. dbt tests that the periods do not overlap; this
    re-checks the parts Python relies on, so a stale or hand-edited table fails loudly."""
    train, test = df[df[split] == "train"], df[df[split] == "test"]
    test_years = test["fiscal_year"].unique()
    if len(test_years) != 1:
        raise SplitError(f"expected one test fiscal year, found {sorted(test_years)}")
    if set(train["fiscal_year"]) & set(test_years):
        raise SplitError("a fiscal year is in both training and test data")
    if train.empty:
        raise SplitError("no training rows")
    return train, test
