"""The question-answering web page (step 9d), run headless with a scripted model: no Ollama needed."""

import pytest
from streamlit.testing.v1 import AppTest
from test_agent import FakeLLM, plan

from hri import PROJECT_ROOT
from hri.semantic import DB_PATH

pytestmark = pytest.mark.skipif(not DB_PATH.exists(), reason="no warehouse; run `hri dbt build`")
APP = PROJECT_ROOT / "src" / "hri" / "app.py"


def ask(question: str, *replies: dict) -> AppTest:
    app = AppTest.from_file(str(APP), default_timeout=120)
    app.session_state["llm"] = FakeLLM(*replies)
    app.run()
    app.chat_input[0].set_value(question).run()
    assert not app.exception, app.exception
    return app


def test_a_single_number_is_shown_as_a_metric_with_its_plan_and_sql():
    app = ask("How many hospitals were in the payment file in FY2024?",
              plan(metrics=["hospitals_in_payment_file"],
                   filters=[{"dimension": "fiscal_year", "op": "=", "value": "FY2024"}]))
    shown = [m.value for m in app.metric if m.label == "Hospitals in the payment file"]
    assert shown == ["3,037"]  # checked with SQL on the marts
    assert any("select" in c.value.lower() for c in app.code)  # the SQL is shown


def test_a_breakdown_gets_a_table_with_every_row():
    app = ask("Share penalized by state", plan(metrics=["share_penalized"], group_by=["hospital__state"]))
    table = app.dataframe[0].value
    assert list(table.columns) == ["state", "Share of hospitals penalized"]
    assert len(table) > 50
    assert table["Share of hospitals penalized"].str.contains(r"%|n/a").all()  # Maryland: n/a
    assert "(unknown)" in set(table["state"])  # hospital 420117 has no profile, so no state


def test_a_declined_question_says_why():
    app = ask("Why do hospitals get penalized?", plan(action="decline", decline_reason="causal"))
    assert "not why" in app.warning[0].value
    assert not app.dataframe
