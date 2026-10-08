"""The evaluation harness (step 8c): the scorer, the gold answers and the recorded run."""

import json

import pandas as pd
import pytest

from hri.agent.agent import Answer, Plan
from hri.agent.evaluate import REPORT_DIR, evaluate, load_questions, score, summarize
from hri.semantic import DB_PATH

needs_warehouse = pytest.mark.skipif(not DB_PATH.exists(), reason="no warehouse; run `hri dbt build`")

Q = {"id": "x", "category": "breakdown", "metric": "share_penalized", "keys": ["hospital__state"]}
GOLD = pd.DataFrame({"hospital__state": ["CA", "TX", "MD"], "value": [0.8, 0.7, None]})


def answer(data: dict, group_by=("hospital__state",), metrics=("share_penalized",)) -> Answer:
    return Answer("q", "answered", "", plan=Plan(metrics=list(metrics), group_by=list(group_by)),
                  data=pd.DataFrame(data))


def test_the_scorer_needs_the_right_metric_breakdown_rows_and_values():
    right = {"hospital__state": ["TX", "CA", "MD"], "share_penalized": [0.7, 0.8, None]}
    assert score(Q, answer(right), GOLD) == (True, "correct")  # row order and empty rows don't matter
    wrong_metric = answer({"hospital__state": ["CA", "TX"], "penalized_hospitals": [8, 7]},
                          metrics=["penalized_hospitals"])
    assert score(Q, wrong_metric, GOLD) == (False, "wrong metric")
    assert score(Q, answer({"share_penalized": [0.75]}, group_by=()), GOLD) == (False, "missing breakdown")
    missing_row = answer({"hospital__state": ["CA"], "share_penalized": [0.8]})
    assert score(Q, missing_row, GOLD) == (False, "wrong rows")
    off = {"hospital__state": ["CA", "TX"], "share_penalized": [0.8, 0.71]}
    assert score(Q, answer(off), GOLD) == (False, "wrong values")


def test_a_constant_extra_breakdown_is_allowed_but_a_real_one_is_not():
    single = {**Q, "keys": []}
    gold = pd.DataFrame({"value": [0.9]})
    shown = {"hospital__state": ["OH"], "share_penalized": [0.9]}
    assert score(single, answer(shown), gold) == (True, "correct")
    split = {"hospital__state": ["OH", "MI"], "share_penalized": [0.9, 0.8]}
    assert score(single, answer(split), gold) == (False, "extra breakdown")


def test_declines_are_scored_on_whether_the_agent_declined():
    q = {"id": "d", "category": "decline", "expect": "decline", "reason": "causal"}
    assert score(q, Answer("q", "declined", ""), None) == (True, "declined")
    answered = answer({"share_penalized": [0.9]}, group_by=())
    assert score(q, answered, None) == (False, "not declined (answered)")


def test_the_question_set_is_complete():
    questions = load_questions()
    assert len({q["id"] for q in questions}) == len(questions)
    for q in questions:
        assert ("sql" in q and "plan" in q and "keys" in q) or q.get("expect") == "decline", q["id"]


@needs_warehouse
def test_the_reference_plans_score_100_percent():
    """The correct plans, run through the agent and scored against the hand-written SQL: any
    disagreement means a wrong gold answer, scorer or metric definition."""
    run = evaluate(["reference"], log=lambda *_: None)
    wrong = [(r["id"], r["why"]) for r in run["results"] if not r["correct"]]
    assert not wrong


@needs_warehouse
@pytest.mark.skipif(not (REPORT_DIR / "responses.json").exists(), reason="no recorded evaluation")
def test_the_recorded_run_replays_to_the_published_scores():
    """Replays the saved model replies (no model needed) and checks every published verdict."""
    recorded = json.loads((REPORT_DIR / "eval_results.json").read_text(encoding="utf-8"))
    replay = json.loads((REPORT_DIR / "responses.json").read_text(encoding="utf-8"))
    run = evaluate(list(replay), replay=replay, log=lambda *_: None)
    verdict = {(r["variant"], r["id"]): (r["correct"], r["why"]) for r in run["results"]}
    assert verdict == {(r["variant"], r["id"]): (r["correct"], r["why"]) for r in recorded["results"]}
    for variant, s in summarize(run["results"]).items():
        assert s["accuracy"] == recorded["summary"][variant]["accuracy"]
