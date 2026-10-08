"""Questions in plain English, answered from the semantic layer (step 8b, D-010).

The flow for one question:

1. The model reads the question and the catalog (approved metrics and dimensions with their
   descriptions) and returns a *plan*: metrics, breakdowns, filters, sort, limit, or a decline.
   The JSON schema lists the allowed names, so it cannot ask for anything else.
2. Our code checks the plan and fixes the values: 'Maryland' becomes the state code MD,
   'johns hopkins' becomes JOHNS HOPKINS HOSPITAL. Every change is shown in the answer.
3. If the plan cannot run, the error goes back to the model once ("repair"), then we give up.
4. The semantic layer runs the query, read-only.
5. Our code writes the answer from the result. The numbers never pass through the model, so it
   cannot misquote or invent them.
"""

import difflib
import json
import time
from dataclasses import dataclass, field
from functools import cached_property

import pandas as pd

from hri.agent.llm import LLM, Call
from hri.semantic import OPERATORS, Filter, SemanticLayer, SemanticLayerError

MAX_QUESTION_CHARS = 500
MAX_ANSWER_ROWS = 50
# Dimensions the agent does not offer: one value only, or another way to say fiscal_year.
HIDDEN_DIMENSIONS = ("hospital__hospital_type", "fiscal_year__is_latest_fiscal_year")
# Dimensions with this many values or fewer have their values listed in the prompt.
LISTED_VALUES = 12

DECLINES = {
    "patient_level": "The data are hospital totals published by CMS; there is nothing about individual "
                     "patients or their records.",
    "causal": "The data can show what goes together, not why. They cannot say what causes readmissions "
              "or penalties.",
    "prediction": "This assistant reports published figures, not forecasts. For penalty-risk "
                  "predictions see the model (step 7, docs/model_card.md).",
    "advice": "This assistant does not give medical, financial or legal advice.",
    "not_in_data": "That is not among the approved metrics.",
}

SYSTEM_PROMPT = """\
You turn questions about the US Medicare Hospital Readmissions Reduction Program (HRRP) into a
query plan in JSON. You never answer with numbers yourself: the plan is run on the approved
metrics below and the program writes the answer.

How to fill the plan:
- metrics: the metric(s) whose description fits the question. Usually one.
- group_by: dimensions to break the answer down by ("by state", "per condition", "each year",
  "which hospitals"). Empty when the question asks for a single number.
- filters: conditions such as "in Maryland", "for heart failure", "in FY2025". Use the listed
  values exactly. Years are fiscal years written like FY2026. A question with no year needs no
  fiscal_year filter: the program uses the latest year.
- sort and limit: for "top", "highest", "most", "lowest", "fewest". Otherwise sort "none" and
  limit 50.
- action "decline" with a decline_reason when the question asks about individual patients
  (patient_level), why something happens (causal), the future (prediction), what someone should
  do (advice), or anything the metrics cannot answer (not_in_data). Otherwise action "query" and
  decline_reason "none".

METRICS
{metrics}

DIMENSIONS usable with every metric
{common}
{extra}
EXAMPLES
{examples}"""

EXAMPLES = [
    ("What share of hospitals were penalized in FY2025?",
     {"metrics": ["share_penalized"], "group_by": [],
      "filters": [{"dimension": "fiscal_year", "op": "=", "value": "FY2025"}]}),
    ("Which 5 states have the highest average payment reduction?",
     {"metrics": ["avg_payment_reduction_pct"], "group_by": ["hospital__state"], "filters": [],
      "sort": "highest_first", "limit": 5}),
    ("Average excess readmission ratio for heart failure by year",
     {"metrics": ["avg_excess_readmission_ratio"], "group_by": ["fiscal_year"],
      "filters": [{"dimension": "readmission_result__condition", "op": "=", "value": "HF"}]}),
    ("How many hospitals were penalized each year since FY2022?",
     {"metrics": ["penalized_hospitals"], "group_by": ["fiscal_year"],
      "filters": [{"dimension": "fiscal_year", "op": ">=", "value": "FY2022"}]}),
    ("Why do hospitals in poor areas get penalized more?",
     {"action": "decline", "decline_reason": "causal", "metrics": []}),
    ("Will Mercy Hospital be penalized next year?",
     {"action": "decline", "decline_reason": "prediction", "metrics": []}),
]


@dataclass
class Plan:
    action: str = "query"
    decline_reason: str = "none"
    metrics: list[str] = field(default_factory=list)
    group_by: list[str] = field(default_factory=list)
    filters: list[Filter] = field(default_factory=list)
    sort: str = "none"
    limit: int = MAX_ANSWER_ROWS
    keep: dict[str, list] = field(default_factory=dict)  # rows to keep after a comparison

    @classmethod
    def from_json(cls, text: str) -> "Plan":
        raw = json.loads(text)
        return cls(
            action=raw.get("action", "query"),
            decline_reason=raw.get("decline_reason", "none"),
            metrics=list(dict.fromkeys(raw.get("metrics") or [])),  # drop repeats, keep order
            group_by=list(dict.fromkeys(raw.get("group_by") or [])),
            filters=[Filter(f["dimension"], f["op"], str(f["value"])) for f in raw.get("filters") or []],
            sort=raw.get("sort", "none"),
            limit=int(raw.get("limit") or MAX_ANSWER_ROWS),
        )

    def as_dict(self) -> dict:
        return {"action": self.action, "decline_reason": self.decline_reason, "metrics": self.metrics,
                "group_by": self.group_by,
                "filters": [{"dimension": f.dimension, "op": f.op, "value": f.value} for f in self.filters],
                "sort": self.sort, "limit": self.limit}


@dataclass
class Answer:
    question: str
    status: str  # answered | declined | failed
    text: str
    plan: Plan | None = None
    data: pd.DataFrame | None = None
    sql: str = ""
    notes: list[str] = field(default_factory=list)  # assumptions and corrected values
    calls: list[Call] = field(default_factory=list)
    seconds: float = 0.0


def plan_schema(metrics: list[str], dimensions: list[str]) -> dict:
    """The JSON schema of a plan. The name lists become a grammar inside Ollama."""
    return {
        "type": "object",
        "properties": {
            "action": {"type": "string", "enum": ["query", "decline"]},
            "decline_reason": {"type": "string", "enum": ["none", *DECLINES]},
            "metrics": {"type": "array", "items": {"type": "string", "enum": metrics}, "maxItems": 3},
            "group_by": {"type": "array", "items": {"type": "string", "enum": dimensions}, "maxItems": 2},
            "filters": {"type": "array", "maxItems": 4, "items": {
                "type": "object",
                "properties": {"dimension": {"type": "string", "enum": dimensions},
                               "op": {"type": "string", "enum": list(OPERATORS)},
                               "value": {"type": "string"}},
                "required": ["dimension", "op", "value"]}},
            "sort": {"type": "string", "enum": ["none", "highest_first", "lowest_first"]},
            "limit": {"type": "integer", "minimum": 1, "maximum": MAX_ANSWER_ROWS},
        },
        "required": ["action", "decline_reason", "metrics", "group_by", "filters", "sort", "limit"],
    }


# --- Values ----------------------------------------------------------------------------------


def _number(value) -> str:
    """1.0 -> '1'; a missing value -> '(none)'; other values unchanged, as text."""
    if value is None or value != value:
        return "(none)"
    return str(int(value)) if isinstance(value, float) and value.is_integer() else str(value)


def resolve_value(dimension: str, value: str, known: list, aliases: dict[str, str] | None = None):
    """The value as stored in the data, and a note when it was changed.

    Tries in order: exact, case-insensitive, an alias (state name -> code), a unique name that
    contains the value, the closest spelling. Raises SemanticLayerError when nothing fits, with
    the closest values, so the model (or the user) can try again."""
    text = str(value).strip()
    if known and all(isinstance(v, bool) for v in known):
        if text.lower() in ("true", "yes", "1"):
            return True, None
        if text.lower() in ("false", "no", "0"):
            return False, None
        raise SemanticLayerError(f"{dimension} is true or false, not {text!r}")
    if known and all(isinstance(v, int | float) for v in known):
        try:
            return float(text), None
        except ValueError:
            raise SemanticLayerError(f"{dimension} is a number ({', '.join(map(_number, known))}), "
                                     f"not {text!r}") from None
    if text in known:
        return text, None
    by_folded = {str(v).casefold(): v for v in known}
    folded = text.casefold()
    found = by_folded.get(folded) or by_folded.get((aliases or {}).get(folded, "").casefold())
    if found is None:
        containing = [v for k, v in by_folded.items() if folded in k]
        if len(containing) == 1:
            found = containing[0]
        elif len(containing) > 1:
            raise SemanticLayerError(f"{text!r} matches several {dimension} values: "
                                     f"{', '.join(map(str, containing[:8]))}. Which one?")
    if found is None:
        close = difflib.get_close_matches(folded, list(by_folded), n=3, cutoff=0.8)
        if len(close) == 1 or (close and difflib.SequenceMatcher(None, folded, close[0]).ratio() >= 0.9):
            found = by_folded[close[0]]
        else:
            hint = f" Closest: {', '.join(str(by_folded[c]) for c in close)}." if close else ""
            raise SemanticLayerError(f"No {dimension} value {text!r} in the data.{hint}")
    return found, f"Read '{text}' as {found}."


# --- Answers ---------------------------------------------------------------------------------


def format_metric(name: str, value) -> str:
    """Shares as %, payment reductions as % of Medicare base payments, counts with commas."""
    if value is None or (isinstance(value, float) and value != value):
        return "n/a"
    if name.startswith("share_"):
        return f"{value:.1%}"
    if name.endswith("_pct"):
        return f"{value:.2f}%"
    if "excess_readmission_ratio" in name:
        return f"{value:.4f}"
    if name.endswith("_score"):
        return f"{value:.1f}"
    return f"{value:,.0f}"


def short_name(dimension: str) -> str:
    """hospital__county__state_name -> state name"""
    return dimension.split("__")[-1].replace("_", " ")


def render(plan: Plan, data: pd.DataFrame, labels: dict[str, str]) -> str:
    """The answer text, written by code from the result table."""
    conditions = ", ".join(f"{short_name(f.dimension)} {f.op} {_number(f.value)}" for f in plan.filters)
    where = f" ({conditions})" if conditions else ""
    if data.empty:
        return f"No data for {', '.join(labels[m] for m in plan.metrics)}{where}."
    if not plan.group_by and len(data) == 1:
        return "\n".join(f"{labels[m]}{where}: {format_metric(m, data[m].iloc[0])}" for m in plan.metrics)
    table = pd.DataFrame({short_name(d): data[d].map(_number) for d in plan.group_by})
    for m in plan.metrics:
        table[labels[m]] = data[m].map(lambda v, m=m: format_metric(m, v))
    return f"{', '.join(labels[m] for m in plan.metrics)}{where}:\n\n{table.to_string(index=False)}"


# --- The agent -------------------------------------------------------------------------------


class Agent:
    def __init__(self, llm: LLM, layer: SemanticLayer | None = None):
        self.llm = llm
        self.layer = layer or SemanticLayer()
        self._values: dict[str, list] = {}

    @cached_property
    def dimensions(self) -> list[str]:
        offered = set().union(*(m.dimensions for m in self.layer.metrics.values()))
        return sorted(offered - set(HIDDEN_DIMENSIONS))

    @cached_property
    def schema(self) -> dict:
        return plan_schema(list(self.layer.metrics), self.dimensions)

    def values(self, dimension: str) -> list:
        """The dimension's values in the data, queried once."""
        if dimension not in self._values:
            self._values[dimension] = self.layer.dimension_values(dimension)[dimension].tolist()
        return self._values[dimension]

    @cached_property
    def state_names(self) -> dict[str, str]:
        """'maryland' -> 'MD', from the data itself (hospital state code next to its county's state)."""
        pairs = self.layer.dimension_values("hospital__state", "hospital__county__state_name")
        return {name.casefold(): code for code, name in pairs.itertuples(index=False)}

    @cached_property
    def facility_states(self) -> dict[str, list[str]]:
        """Hospital name -> the states with a hospital of that name (names are not unique)."""
        pairs = self.layer.dimension_values("hospital__facility_name", "hospital__state")
        return pairs.groupby("hospital__facility_name")["hospital__state"].agg(sorted).to_dict()

    @cached_property
    def latest_fiscal_year(self) -> str:
        return max(self.values("fiscal_year"))

    @cached_property
    def system_prompt(self) -> str:
        metrics = self.layer.metrics
        common = [d for d in self.dimensions
                  if all(d in m.dimensions for m in metrics.values())]

        def line(d: str) -> str:
            text = f"- {d}: {self.layer.describe(d)}"
            values = self.values(d)
            if len(values) <= LISTED_VALUES and not all(isinstance(v, bool) for v in values):
                text += f" Values: {', '.join(map(_number, values))}."
            return text

        groups: dict[tuple[str, ...], list[str]] = {}
        for d in self.dimensions:
            if d not in common:
                users = tuple(m.name for m in metrics.values() if d in m.dimensions)
                groups.setdefault(users, []).append(d)
        extra = "".join(f"\nDIMENSIONS usable only with {', '.join(users)}\n"
                        + "\n".join(line(d) for d in dims) + "\n" for users, dims in groups.items())
        examples = "\n".join(f"Q: {q}\nA: {json.dumps(self._full(p))}" for q, p in EXAMPLES)
        return SYSTEM_PROMPT.format(
            metrics="\n".join(f"- {m.name}: {m.description}" for m in metrics.values()),
            common="\n".join(line(d) for d in common), extra=extra, examples=examples)

    @staticmethod
    def _full(partial: dict) -> dict:
        return {"action": "query", "decline_reason": "none", "metrics": [], "group_by": [], "filters": [],
                "sort": "none", "limit": MAX_ANSWER_ROWS, **partial}

    def prepare(self, plan: Plan) -> tuple[Plan, list[str]]:
        """Check the plan and fix its values. Raises SemanticLayerError with a reason the model
        can act on."""
        notes = []
        if not plan.metrics:
            raise SemanticLayerError("The plan has no metric; choose one from METRICS or decline.")
        filters = []
        for f in plan.filters:
            aliases = self.state_names if f.dimension == "hospital__state" else None
            if f.dimension not in self.dimensions:
                raise SemanticLayerError(f"Unknown dimension {f.dimension!r}")
            value, note = resolve_value(f.dimension, f.value, self.values(f.dimension), aliases)
            filters.append(Filter(f.dimension, f.op, value))
            notes += [note] if note else []
            states = self.facility_states.get(value, []) if f.dimension == "hospital__facility_name" else []
            if len(states) > 1 and "hospital__state" not in [g.dimension for g in plan.filters]:
                notes.append(f"Hospitals named {value} are in {len(states)} states ({', '.join(states)}); "
                             "the figures combine them. Name the state to see one.")
        group_by, keep = list(plan.group_by), {}
        for dimension in dict.fromkeys(f.dimension for f in filters):
            equal = [f.value for f in filters if f.dimension == dimension and f.op == "="]
            if len(equal) > 1:
                # "penalized vs unpenalized" as two = filters would match nothing; compare instead.
                filters = [f for f in filters if not (f.dimension == dimension and f.op == "=")]
                group_by += [] if dimension in group_by else [dimension]
                keep[dimension] = equal
                notes.append(f"Compared {' and '.join(map(_number, equal))} side by side.")
        year_range = any(f.dimension == "fiscal_year" and f.op != "=" for f in filters)
        if year_range and "fiscal_year" not in group_by:
            # A range of years added into one number is rarely what was meant ("each year since").
            group_by.insert(0, "fiscal_year")
            notes.append("Several years asked for: one row per fiscal year, not one total.")
        if "fiscal_year" not in [*group_by, *(f.dimension for f in filters)]:
            filters.append(Filter("fiscal_year", "=", self.latest_fiscal_year))
            notes.append(f"No year given: used {self.latest_fiscal_year}, the latest.")
        plan = Plan("query", "none", plan.metrics, group_by, filters, plan.sort,
                    max(1, min(plan.limit, MAX_ANSWER_ROWS)), keep)
        self.layer.validate(plan.metrics, plan.group_by, plan.filters, self._order(plan), plan.limit)
        return plan, notes

    @staticmethod
    def _order(plan: Plan) -> list[str]:
        if plan.sort == "none" or not plan.group_by:
            return []
        return [("-" if plan.sort == "highest_first" else "") + plan.metrics[0]]

    def ask(self, question: str) -> Answer:
        start = time.perf_counter()
        calls_before = len(self.llm.calls)

        def finish(answer: Answer) -> Answer:
            answer.calls = self.llm.calls[calls_before:]
            answer.seconds = time.perf_counter() - start
            return answer

        question = " ".join(question.split())
        if not question:
            return finish(Answer(question, "failed", "Ask a question."))
        if len(question) > MAX_QUESTION_CHARS:
            return finish(Answer(question, "failed", f"Please keep questions under {MAX_QUESTION_CHARS} "
                                                     "characters."))
        messages = [{"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": question}]
        plan, error = None, None
        for _attempt in range(2):  # the first plan, then one repair
            reply = self.llm.chat(messages, self.schema)
            try:
                plan = Plan.from_json(reply)
                if plan.action == "decline":
                    reason = plan.decline_reason if plan.decline_reason in DECLINES else "not_in_data"
                    return finish(Answer(question, "declined", DECLINES[reason] + " " + self._can_ask(),
                                         plan=plan))
                plan, notes = self.prepare(plan)
                result = self.layer.query(plan.metrics, plan.group_by, plan.filters, self._order(plan),
                                          plan.limit)
                break
            except (SemanticLayerError, ValueError, KeyError, TypeError) as exc:
                error = str(exc)
                messages += [{"role": "assistant", "content": reply},
                             {"role": "user", "content": f"That plan cannot run: {error} "
                                                         "Return a corrected plan for the same question."}]
        else:
            return finish(Answer(question, "failed", f"Could not answer that: {error}\n{self._can_ask()}",
                                 plan=plan))
        data = result.data
        for dimension, values in plan.keep.items():
            data = data[data[dimension].isin(values)].reset_index(drop=True)
        labels = {m.name: m.label for m in result.metrics}
        text = render(plan, data, labels)
        if data[plan.metrics].isna().any().any():
            notes.append("n/a: nothing to compute from, e.g. no hospital in the payment file matches "
                         "(Maryland is exempt from the HRRP) or the condition was not scored that year.")
        return finish(Answer(question, "answered", text, plan=plan, data=data, sql=result.sql,
                             notes=notes))

    def _can_ask(self) -> str:
        return ("You can ask about HRRP penalties, excess readmission ratios and patient survey scores "
                "by year, state, county, hospital, ownership, star rating, peer group or condition. "
                "`hri sl list` shows every metric.")
