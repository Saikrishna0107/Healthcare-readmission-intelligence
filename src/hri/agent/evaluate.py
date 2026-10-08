"""How often the agent answers correctly (step 8c, D-010).

Every question in evals/questions.yaml is asked, and the answer table is compared with a gold
answer from SQL written by hand on the marts (not through MetricFlow). An answer counts as
correct only if it uses an accepted metric, has the asked-for breakdown and every row and value
agrees. Questions the agent should refuse count as correct when it declines.

Variants of the same model show what each part of the design adds:
  full         the agent as shipped
  no_examples  the prompt without its worked examples
  no_rules     code rules off: values must match the data exactly (no 'Maryland' -> MD, no
               spelling fixes), no per-year rows for year ranges, no comparison rewrite
  reference    no model: the correct plans from the YAML. Must score 100%; checks the gold SQL,
               the scorer and the semantic layer against each other.

Every model reply is saved (reports/agent/responses.json), so the scores can be recomputed
without the model (`hri eval --replay`) and are checked in a test.
"""

import json
import statistics
from collections import Counter

import duckdb
import numpy as np
import pandas as pd
import yaml

from hri import PROJECT_ROOT
from hri.agent.agent import MAX_ANSWER_ROWS, Agent, Answer, _number
from hri.agent.llm import DEFAULT_MODEL, Call, OllamaClient
from hri.semantic import DB_PATH, SemanticLayer

QUESTIONS = PROJECT_ROOT / "evals" / "questions.yaml"
REPORT_DIR = PROJECT_ROOT / "reports" / "agent"
VARIANTS = {
    "full": {"examples": True, "rules": True},
    "no_examples": {"examples": False, "rules": True},
    "no_rules": {"examples": True, "rules": False},
    "reference": {"examples": True, "rules": True},
}
# Asked once per variant before the timed questions: loads the model and reads the prompt.
WARMUP = "How many hospitals were in the payment file?"
FACTS = {
    "{hy}": "marts.fct_hospital_year y left join marts.dim_hospital h using (facility_id)",
    "{rr}": "marts.fct_readmissions r left join marts.dim_hospital h using (facility_id)",
}


def load_questions(path=QUESTIONS) -> list[dict]:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def gold_answers(questions: list[dict], db_path=DB_PATH) -> dict[str, pd.DataFrame]:
    """The hand-written SQL of each answerable question, run on the warehouse (read-only)."""
    con = duckdb.connect(str(db_path), read_only=True)
    try:
        answers = {}
        for q in questions:
            if "sql" in q:
                sql = q["sql"]
                for name, source in FACTS.items():
                    sql = sql.replace(name, source)
                answers[q["id"]] = con.sql(sql).df()
        return answers
    finally:
        con.close()


class RecordingLLM:
    """Passes calls to the real model and keeps its replies."""

    def __init__(self, inner):
        self.inner, self.replies = inner, []

    @property
    def calls(self) -> list[Call]:
        return self.inner.calls

    def chat(self, messages, schema):
        reply = self.inner.chat(messages, schema)
        self.replies.append(reply)
        return reply


class ScriptedLLM:
    """Plays back given replies (recorded ones, or the reference plans)."""

    def __init__(self, replies: list[str]):
        self.replies, self.calls = list(replies), []

    def chat(self, messages, schema):
        if not self.replies:
            raise RuntimeError("The agent asked the model more often than recorded")
        self.calls.append(Call(0.0))
        return self.replies.pop(0)


def reference_reply(q: dict) -> str:
    """The correct plan of a question as the model would return it."""
    if q.get("expect") == "decline":
        plan = {"action": "decline", "decline_reason": q["reason"]}
    else:
        p = q["plan"]
        plan = {"action": "query", "decline_reason": "none", "metrics": p["metrics"],
                "group_by": p.get("group_by", []),
                "filters": [{"dimension": d, "op": op, "value": str(v)} for d, op, v in p.get("filters", [])],
                "sort": p.get("sort", "none"), "limit": p.get("limit", MAX_ANSWER_ROWS)}
    return json.dumps({"metrics": [], "group_by": [], "filters": [], "sort": "none",
                       "limit": MAX_ANSWER_ROWS, **plan})


def _table(data: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    """Rows with a value, keys as text (1.0 -> '1'), in a fixed order."""
    out = data[data["value"].notna()].copy()
    for k in keys:
        out[k] = out[k].map(_number)
    return out.sort_values(keys).reset_index(drop=True) if keys else out.reset_index(drop=True)


def score(q: dict, answer: Answer, gold: pd.DataFrame | None) -> tuple[bool, str]:
    """(correct, why). The reasons are short labels so they can be counted."""
    if q.get("expect") == "decline":
        if answer.status == "declined":
            return True, "declined"
        return False, f"not declined ({answer.status})"
    if answer.status != "answered":
        return False, answer.status  # declined or failed
    accepted = q["metric"] if isinstance(q["metric"], list) else [q["metric"]]
    metric = next((m for m in answer.plan.metrics if m in accepted), None)
    if metric is None:
        return False, "wrong metric"
    keys, data = q["keys"], answer.data
    if set(keys) - set(answer.plan.group_by):
        return False, "missing breakdown"
    # An extra breakdown is fine when it has one value (e.g. state = OH with the state shown).
    if any(data[d].nunique(dropna=False) > 1 for d in answer.plan.group_by if d not in keys):
        return False, "extra breakdown"
    got = _table(data[keys + [metric]].rename(columns={metric: "value"}), keys)
    want = _table(gold[keys + ["value"]], keys)
    if len(got) != len(want) or not got[keys].equals(want[keys]):
        return False, "wrong rows"
    if not np.allclose(got["value"].astype(float), want["value"].astype(float), rtol=1e-9, atol=1e-12):
        return False, "wrong values"
    return True, "correct"


def evaluate(variants=("full", "no_examples", "no_rules"), model: str = DEFAULT_MODEL,
             replay: dict | None = None, layer: SemanticLayer | None = None, log=print) -> dict:
    """Ask every question with each variant. With replay (variant -> question id -> replies) the
    recorded replies are played back instead of calling the model."""
    questions = load_questions()
    golds = gold_answers(questions)
    layer = layer or SemanticLayer()
    rows, responses = [], {}
    for variant in variants:
        live = replay is None and variant != "reference"
        llm = RecordingLLM(OllamaClient(model=model)) if live else ScriptedLLM([])
        agent = Agent(llm, layer, **VARIANTS[variant])
        if live:
            agent.ask(WARMUP)
        for q in questions:
            if live:
                llm.replies = []
            else:
                agent.llm = ScriptedLLM([reference_reply(q)] if variant == "reference"
                                        else replay[variant][q["id"]])
            answer = agent.ask(q["question"])
            correct, why = score(q, answer, golds.get(q["id"]))
            replies = llm.replies if live else []
            responses.setdefault(variant, {})[q["id"]] = replies
            rows.append({
                "variant": variant, "id": q["id"], "category": q["category"], "question": q["question"],
                "status": answer.status, "correct": correct, "why": why,
                "model_calls": len(answer.calls), "seconds": round(answer.seconds, 2),
                "output_tokens": sum(c.output_tokens for c in answer.calls),
                "plan": answer.plan.as_dict() if answer.plan else None,
                "decline_reason": answer.plan.decline_reason if answer.status == "declined" else None,
                "expected_reason": q.get("reason"),
            })
            log(f"{variant:12s} {q['id']}  {'ok ' if correct else 'BAD'} {why:18s} {answer.seconds:5.1f}s  "
                f"{q['question']}")
    return {"model": model, "questions": len(questions), "results": rows,
            "responses": responses if replay is None else replay}


def summarize(results: list[dict]) -> dict:
    """Per variant: accuracy overall, for answerable questions and for declines, the kinds of
    error, how often the repair round saved an answer, and latency."""
    out = {}
    for variant in dict.fromkeys(r["variant"] for r in results):
        rows = [r for r in results if r["variant"] == variant]
        answerable = [r for r in rows if r["category"] != "decline"]
        declines = [r for r in rows if r["category"] == "decline"]
        seconds = sorted(r["seconds"] for r in rows)
        out[variant] = {
            "accuracy": round(sum(r["correct"] for r in rows) / len(rows), 3),
            "correct": sum(r["correct"] for r in rows), "questions": len(rows),
            "answerable_correct": f"{sum(r['correct'] for r in answerable)}/{len(answerable)}",
            "declines_correct": f"{sum(r['correct'] for r in declines)}/{len(declines)}",
            "decline_reason_matches": f"{sum(r['decline_reason'] == r['expected_reason'] for r in declines)}"
                                      f"/{len(declines)}",
            "wrongly_declined": sum(r["status"] == "declined" for r in answerable),
            "errors": dict(Counter(r["why"] for r in rows if not r["correct"]).most_common()),
            "by_category": {c: f"{sum(r['correct'] for r in rows if r['category'] == c)}"
                               f"/{sum(r['category'] == c for r in rows)}"
                            for c in dict.fromkeys(r["category"] for r in rows)},
            "saved_by_repair": sum(r["correct"] and r["model_calls"] == 2 for r in rows),
            "median_seconds": round(statistics.median(seconds), 1),
            "p90_seconds": round(seconds[int(0.9 * (len(seconds) - 1))], 1),
        }
    return out


def save(run: dict) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    report = {"model": run["model"], "questions": run["questions"], "summary": summarize(run["results"]),
              "results": run["results"]}
    (REPORT_DIR / "eval_results.json").write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    responses = {v: r for v, r in run["responses"].items() if v != "reference"}
    (REPORT_DIR / "responses.json").write_text(json.dumps(responses, indent=2), encoding="utf-8")


def summary_text(summary: dict) -> str:
    lines = [f"{'variant':12s} {'all':>7s} {'answerable':>11s} {'declines':>9s} {'repair saved':>13s} "
             f"{'median s':>9s} {'p90 s':>6s}"]
    for v, s in summary.items():
        lines.append(f"{v:12s} {s['accuracy']:>7.1%} {s['answerable_correct']:>11s} "
                     f"{s['declines_correct']:>9s} {s['saved_by_repair']:>13d} "
                     f"{s['median_seconds']:>9.1f} {s['p90_seconds']:>6.1f}")
    for v, s in summary.items():
        lines.append(f"\n{v}: errors {s['errors'] or 'none'}; by category {s['by_category']}")
    return "\n".join(lines)

