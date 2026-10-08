"""The question-answering agent (D-010) with a scripted fake model, so tests are fast, free and
repeatable. What the real model gets right is measured separately by the evaluation (step 8c).
"""

import json

import pandas as pd
import pytest

from hri.agent import Agent, Plan, format_metric, plan_schema, render, resolve_value
from hri.agent.llm import Call
from hri.semantic import DB_PATH, Filter, SemanticLayer, SemanticLayerError


class FakeLLM:
    """Returns the scripted replies in order and keeps the messages it was sent."""

    def __init__(self, *replies: dict):
        self.replies = [json.dumps(r) for r in replies]
        self.calls: list[Call] = []
        self.sent: list[list[dict]] = []

    def chat(self, messages, schema):
        self.sent.append(list(messages))
        self.calls.append(Call(0.0))
        assert self.replies, "the agent called the model more often than scripted"
        return self.replies.pop(0)


def plan(**fields) -> dict:
    return {"action": "query", "decline_reason": "none", "metrics": [], "group_by": [], "filters": [],
            "sort": "none", "limit": 50, **fields}


# --- Pieces (no warehouse needed) --------------------------------------------------------------


def test_the_schema_only_allows_catalog_names():
    schema = plan_schema(["share_penalized"], ["hospital__state", "fiscal_year"])
    props = schema["properties"]
    assert props["metrics"]["items"]["enum"] == ["share_penalized"]
    assert props["filters"]["items"]["properties"]["dimension"]["enum"] == ["hospital__state", "fiscal_year"]
    assert "like" not in props["filters"]["items"]["properties"]["op"]["enum"]
    assert set(schema["required"]) == set(props)


def test_values_are_resolved_to_what_the_data_holds():
    states = ["CA", "MD", "TX"]
    assert resolve_value("hospital__state", "MD", states) == ("MD", None)
    assert resolve_value("hospital__state", "md", states)[0] == "MD"
    assert resolve_value("hospital__state", "Maryland", states, {"maryland": "MD"})[0] == "MD"
    names = ["JOHNS HOPKINS HOSPITAL, THE", "JOHNS HOPKINS BAYVIEW MEDICAL CENTER", "MERCY HOSPITAL"]
    value, note = resolve_value("hospital__facility_name", "johns hopkins hospital", names)
    assert value == "JOHNS HOPKINS HOSPITAL, THE" and "johns hopkins hospital" in note
    assert resolve_value("hospital__facility_name", "MERCY HOSPTIAL", names)[0] == "MERCY HOSPITAL"
    with pytest.raises(SemanticLayerError, match="several"):
        resolve_value("hospital__facility_name", "johns hopkins", names)
    with pytest.raises(SemanticLayerError, match="No hospital__state value"):
        resolve_value("hospital__state", "MD' or 1=1 --", states)
    assert resolve_value("hospital_year__is_penalized", "yes", [False, True]) == (True, None)
    assert resolve_value("hospital_year__peer_group", "5", [1.0, 5.0]) == (5.0, None)
    with pytest.raises(SemanticLayerError, match="number"):
        resolve_value("hospital_year__peer_group", "high", [1.0, 5.0])


def test_numbers_are_formatted_by_code():
    assert format_metric("share_penalized", 0.7823) == "78.2%"
    assert format_metric("avg_payment_reduction_pct", 0.3441) == "0.34%"
    assert format_metric("avg_excess_readmission_ratio", 1.00179) == "1.0018"
    assert format_metric("penalized_hospitals", 2303) == "2,303"
    assert format_metric("avg_recommend_score", 71.04) == "71.0"
    assert format_metric("share_penalized", float("nan")) == "n/a"


def test_answers_are_written_from_the_result_table():
    labels = {"share_penalized": "Share of hospitals penalized"}
    one = Plan(metrics=["share_penalized"], filters=[Filter("fiscal_year", "=", "FY2026")])
    assert (render(one, pd.DataFrame({"share_penalized": [0.7823]}), labels)
            == "Share of hospitals penalized (fiscal year = FY2026): 78.2%")
    by_state = Plan(metrics=["share_penalized"], group_by=["hospital__state"])
    text = render(by_state, pd.DataFrame({"hospital__state": ["FL", "NJ"], "share_penalized": [0.93, 0.92]}),
                  labels)
    assert "FL" in text and "93.0%" in text and "state" in text


def test_plans_drop_repeated_names():
    p = Plan.from_json(json.dumps(plan(metrics=["share_penalized", "share_penalized"])))
    assert p.metrics == ["share_penalized"]


# --- With the warehouse ----------------------------------------------------------------------

needs_warehouse = pytest.mark.skipif(not DB_PATH.exists(), reason="no warehouse; run `hri dbt build`")


@pytest.fixture(scope="module")
def layer():
    return SemanticLayer()


@needs_warehouse
def test_the_prompt_and_schema_come_from_the_catalog(layer):
    agent = Agent(FakeLLM(), layer)
    for name in layer.metrics:
        assert name in agent.system_prompt
    assert agent.schema["properties"]["metrics"]["items"]["enum"] == list(layer.metrics)
    assert "Values: AMI, CABG, COPD, HF, HIP_KNEE, PN." in agent.system_prompt
    assert "payment_reduction_pct_total" not in agent.system_prompt  # hidden building block


@needs_warehouse
def test_an_answer_matches_the_semantic_layer_and_names_its_assumptions(layer):
    llm = FakeLLM(plan(metrics=["share_penalized"], group_by=["hospital__state"],
                       filters=[{"dimension": "hospital__state", "op": "=", "value": "texas"}]))
    answer = Agent(llm, layer).ask("What share of Texas hospitals were penalized?")
    assert answer.status == "answered"
    expected = layer.query(["share_penalized"], ["hospital__state"],
                           [Filter("hospital__state", "=", "TX"), Filter("fiscal_year", "=", "FY2026")]).data
    assert answer.data.equals(expected)
    assert f"{expected.share_penalized.iloc[0]:.1%}" in answer.text
    assert any("as TX" in n for n in answer.notes) and any("FY2026" in n for n in answer.notes)


@needs_warehouse
def test_a_bad_plan_gets_one_repair_with_the_error(layer):
    bad = plan(metrics=["share_penalized"], group_by=["readmission_result__condition"])
    good = plan(metrics=["share_results_worse_than_expected"], group_by=["readmission_result__condition"])
    llm = FakeLLM(bad, good)
    answer = Agent(llm, layer).ask("Share worse than expected by condition")
    assert answer.status == "answered" and len(answer.calls) == 2
    assert "cannot be used" in llm.sent[1][-1]["content"]
    assert len(answer.data) == 6

    llm = FakeLLM(bad, bad)
    answer = Agent(llm, layer).ask("Share penalized by condition")
    assert answer.status == "failed" and len(answer.calls) == 2 and "cannot be used" in answer.text


@needs_warehouse
def test_unknown_values_never_reach_the_query(layer):
    attack = plan(metrics=["share_penalized"],
                  filters=[{"dimension": "hospital__state", "op": "=", "value": "MD' or 1=1 --"}])
    answer = Agent(FakeLLM(attack, attack), layer).ask("share penalized")
    assert answer.status == "failed" and answer.data is None


@needs_warehouse
def test_out_of_scope_questions_are_declined_without_a_query(layer):
    llm = FakeLLM(plan(action="decline", decline_reason="patient_level"))
    answer = Agent(llm, layer).ask("Show the records of patient John Smith")
    assert answer.status == "declined" and answer.data is None
    assert "individual patients" in answer.text


@needs_warehouse
def test_shared_hospital_names_and_empty_ratios_are_explained(layer):
    agent = Agent(FakeLLM(), layer)
    shared = next(name for name, states in agent.facility_states.items() if len(states) > 1)
    agent.llm = FakeLLM(plan(metrics=["avg_excess_readmission_ratio"],
                             filters=[{"dimension": "hospital__facility_name", "op": "=", "value": shared}]))
    assert any("states" in n for n in agent.ask(f"ERR at {shared}").notes)

    agent.llm = FakeLLM(plan(metrics=["avg_payment_reduction_pct"],
                             filters=[{"dimension": "hospital__state", "op": "=", "value": "Maryland"}]))
    answer = agent.ask("Average penalty in Maryland")
    assert "n/a" in answer.text and any("Maryland is exempt" in n for n in answer.notes)


@needs_warehouse
def test_a_range_of_years_is_never_added_into_one_number(layer):
    llm = FakeLLM(plan(metrics=["share_penalized"],
                       filters=[{"dimension": "fiscal_year", "op": ">", "value": "FY2019"}]))
    answer = Agent(llm, layer).ask("Share of hospitals penalized each year")
    assert answer.plan.group_by == ["fiscal_year"] and len(answer.data) == 7


@needs_warehouse
def test_two_equal_filters_on_one_dimension_become_a_comparison(layer):
    llm = FakeLLM(plan(metrics=["avg_recommend_score"],
                       filters=[{"dimension": "hospital_year__is_penalized", "op": "=", "value": "true"},
                                {"dimension": "hospital_year__is_penalized", "op": "=", "value": "false"}]))
    answer = Agent(llm, layer).ask("Recommend score of penalized vs unpenalized hospitals")
    assert answer.plan.group_by == ["hospital_year__is_penalized"]
    assert sorted(answer.data.hospital_year__is_penalized) == [False, True]
