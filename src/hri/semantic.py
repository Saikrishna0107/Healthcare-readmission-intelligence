"""The semantic layer from Python (step 8, D-025): approved metrics, queried read-only.

The metric definitions live in dbt/models/semantic/*.yml. MetricFlow (the engine behind the dbt
Semantic Layer) turns a request such as "share_penalized by hospital__state for FY2026" into SQL.
This module adds the rules the LLM agent (D-010) must follow:

- Only listed metrics and dimensions. Building-block metrics (meta.agent: hidden) are not listed.
- Filters are structured (dimension, operator, value), never free SQL text; values are quoted
  here, so a value cannot change the query.
- Read-only. The engine connects through the dbt target `semantic`: an in-memory database with
  the warehouse attached READ_ONLY. Startup fails if the warehouse is not read-only.
- At most MAX_ROWS rows per answer.
"""

import contextlib
import logging
import os
from dataclasses import dataclass, field
from functools import cached_property

import pandas as pd

from hri import PROJECT_ROOT

DBT_DIR = PROJECT_ROOT / "dbt"
DB_PATH = PROJECT_ROOT / "data" / "hri.duckdb"
TARGET = "semantic"
MAX_ROWS = 500
OPERATORS = ("=", "!=", ">", ">=", "<", "<=")

# Entities that can be used like dimensions: grouping by fiscal_year gives labels like 'FY2026'.
ENTITY_DIMENSIONS = {"fiscal_year": "HRRP fiscal year, e.g. 'FY2026' (Oct 2025 - Sep 2026)"}
# Time columns MetricFlow needs internally; fiscal_year is the way to ask about time.
INTERNAL_DIMENSIONS = ("metric_time", "hospital_year__fiscal_year_start",
                       "readmission_result__fiscal_year_start")


class SemanticLayerError(ValueError):
    """A request outside the approved metrics, dimensions or rules."""


@dataclass(frozen=True)
class Metric:
    name: str
    label: str
    description: str
    dimensions: tuple[str, ...]


@dataclass(frozen=True)
class Filter:
    dimension: str
    op: str
    value: str | int | float | bool


@dataclass
class QueryResult:
    data: pd.DataFrame
    sql: str
    metrics: list[Metric] = field(default_factory=list)


def manifest_is_stale() -> bool:
    """MetricFlow reads dbt/target/semantic_manifest.json, which only `dbt parse` (or any dbt
    command) rewrites. True when a model or YAML file changed after it was written."""
    manifest = DBT_DIR / "target" / "semantic_manifest.json"
    if not manifest.exists():
        return True
    sources = [*(DBT_DIR / "models").rglob("*.yml"), *(DBT_DIR / "models").rglob("*.sql"),
               DBT_DIR / "dbt_project.yml"]
    return max(p.stat().st_mtime for p in sources) > manifest.stat().st_mtime


@contextlib.contextmanager
def _environment(**values: str):
    """Set environment variables for the duration of the block (dbt reads its target from them)."""
    saved = {k: os.environ.get(k) for k in values}
    os.environ.update(values)
    try:
        yield
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def sql_literal(value: str | int | float | bool) -> str:
    """A value as a SQL literal. Strings are quoted with inner quotes doubled, so a value like
    "x' or 1=1 --" stays one string."""
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, int | float):
        return repr(value)
    return "'" + str(value).replace("'", "''") + "'"


def where_clause(f: Filter) -> str:
    """One filter in MetricFlow's where syntax, e.g. {{ Dimension('hospital__state') }} = 'MD'."""
    if f.op not in OPERATORS:
        raise SemanticLayerError(f"Operator {f.op!r} is not allowed; use one of {', '.join(OPERATORS)}")
    if f.dimension in ENTITY_DIMENSIONS:
        return f"{{{{ Entity('{f.dimension}') }}}} {f.op} {sql_literal(f.value)}"
    # Filters only accept entity__dimension; a two-join name (hospital__county__state_name) is
    # written as the last entity and dimension, with the entities before it as the path.
    *path, entity, name = f.dimension.split("__")
    path_arg = f", entity_path={path!r}" if path else ""
    return f"{{{{ Dimension('{entity}__{name}'{path_arg}) }}}} {f.op} {sql_literal(f.value)}"


class SemanticLayer:
    """Lazy: the MetricFlow engine (about 4 seconds to start) is built on first use."""

    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    @cached_property
    def _config(self):
        from dbt_metricflow.cli.cli_configuration import CLIConfiguration

        for name in ("metricflow", "metricflow_semantics", "dbt_metricflow"):  # chatty at INFO
            logging.getLogger(name).setLevel(logging.WARNING)
        if not self.db_path.exists():
            raise FileNotFoundError(f"{self.db_path} not found; run `hri ingest` and `hri dbt build` first")
        with _environment(DBT_TARGET=TARGET, HRI_DUCKDB_PATH=str(self.db_path)), contextlib.chdir(DBT_DIR):
            if manifest_is_stale():  # never answer from outdated metric definitions
                from dbt.cli.main import dbtRunner

                if not dbtRunner().invoke(["parse", "--quiet"]).success:
                    raise RuntimeError("`dbt parse` failed; run `hri dbt parse` to see why")
            config = CLIConfiguration()
            config.setup(dbt_profiles_path=DBT_DIR, dbt_project_path=DBT_DIR, configure_file_logging=False)
            databases = config.sql_client.query("select database_name, readonly from duckdb_databases()")
        if ("hri", True) not in set(databases.rows):
            raise RuntimeError("The semantic layer must open the warehouse read-only; check dbt/profiles.yml")
        return config

    @cached_property
    def metrics(self) -> dict[str, Metric]:
        """The metrics offered to users and the agent, with the dimensions each can be broken down by."""
        found = {}
        for m in self._config.mf.list_metrics():
            if (m.config.meta if m.config else {}).get("agent") == "hidden":
                continue
            dimensions = {d.granularity_free_dunder_name for d in m.dimensions} - set(INTERNAL_DIMENSIONS)
            found[m.name] = Metric(m.name, m.label or m.name, " ".join((m.description or "").split()),
                                   tuple(sorted(dimensions | set(ENTITY_DIMENSIONS))))
        return dict(sorted(found.items()))

    def dimensions_for(self, metric_names: list[str]) -> set[str]:
        """Dimensions valid for every one of the metrics (a query can only use shared ones)."""
        unknown = [m for m in metric_names if m not in self.metrics]
        if unknown:
            raise SemanticLayerError(f"Unknown metric(s): {', '.join(unknown)}. Use `hri sl list`.")
        return set.intersection(*(set(self.metrics[m].dimensions) for m in metric_names))

    def validate(self, metrics: list[str], group_by=(), filters=(), order_by=(), limit=MAX_ROWS) -> None:
        if not metrics:
            raise SemanticLayerError("Ask for at least one metric")
        allowed = self.dimensions_for(metrics)
        for name in [*group_by, *(f.dimension for f in filters)]:
            if name not in allowed:
                raise SemanticLayerError(f"{name!r} cannot be used with {', '.join(metrics)}; "
                                         f"allowed: {', '.join(sorted(allowed))}")
        for f in filters:
            where_clause(f)  # checks the operator
        for name in order_by:
            if name.removeprefix("-") not in {*metrics, *group_by}:
                raise SemanticLayerError(f"Can only order by a requested metric or dimension, not {name!r}")
        if not 1 <= limit <= MAX_ROWS:
            raise SemanticLayerError(f"limit must be between 1 and {MAX_ROWS}")

    def query(self, metrics: list[str], group_by=(), filters=(), order_by=(), limit=MAX_ROWS,
              ) -> QueryResult:
        from metricflow.engine.metricflow_engine import MetricFlowQueryRequest

        self.validate(metrics, group_by, filters, order_by, limit)
        order_by = list(order_by) or list(group_by)  # stable row order when none is asked for
        request = MetricFlowQueryRequest.create(
            metric_names=list(metrics),
            group_by_names=list(group_by) or None,
            where_constraints=[where_clause(f) for f in filters] or None,
            order_by_names=list(order_by) or None,
            limit=limit,
        )
        from metricflow_semantics.errors.error_classes import InvalidQueryException

        try:
            result = self._config.mf.query(request)
        except InvalidQueryException as exc:  # e.g. a combination MetricFlow cannot resolve
            lines = str(exc).splitlines()
            detail = " ".join(line.strip() for line in lines if "should" in line)
            raise SemanticLayerError(f"{lines[0]} {detail}".strip()) from exc
        table = result.result_df
        data = pd.DataFrame(list(table.rows), columns=list(table.column_names))
        return QueryResult(data=data, sql=result.sql or "", metrics=[self.metrics[m] for m in metrics])
