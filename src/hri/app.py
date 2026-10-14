"""A web page for the question-answering agent (step 9d, D-011): `hri app` opens it in the browser.

The same agent as `hri ask`: the local model (Ollama) writes a query plan, the semantic layer
runs it, code writes the answer. The page adds a table, a chart, the plan and the SQL under each
answer, and the agent's measured accuracy (step 8c) in the sidebar.

Everything runs on this computer. Tests replace the model by putting a scripted one in
st.session_state["llm"] before the first run.
"""

import json

import pandas as pd
import requests
import streamlit as st

from hri.agent import DEFAULT_MODEL, Agent, Answer, LLMError, OllamaClient, format_metric
from hri.agent.agent import short_name
from hri.agent.evaluate import REPORT_DIR, load_questions
from hri.agent.llm import OLLAMA_URL

CHART_ROWS = 25  # a bar chart with more bars than this is unreadable; the table has them all


@st.cache_resource(show_spinner="Loading the semantic layer...")
def ollama_agent(model: str) -> Agent:
    return Agent(OllamaClient(model=model))


@st.cache_data
def evaluation() -> dict | None:
    path = REPORT_DIR / "eval_results.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@st.cache_data
def example_questions() -> list[str]:
    """One question per category that the model answered correctly in the evaluation."""
    run = evaluation()
    if run is None:
        return []
    correct = {r["id"] for r in run["results"] if r["variant"] == "full" and r["correct"]}
    examples: dict[str, str] = {}
    for q in load_questions():
        if q["id"] in correct:
            examples.setdefault(q["category"], q["question"])
    return list(examples.values())


def ollama_running() -> bool:
    try:
        return requests.get(f"{OLLAMA_URL}/api/tags", timeout=2).ok
    except requests.RequestException:
        return False


def labels(agent: Agent) -> dict[str, str]:
    return {name: m.label for name, m in agent.layer.metrics.items()}


def answer_table(answer: Answer, metric_labels: dict[str, str]) -> pd.DataFrame:
    """The result with readable column names and values formatted like the answer text."""
    # A hospital in the payment file without a profile (420117) has no state: say so, not blank.
    table = pd.DataFrame({short_name(d): answer.data[d].fillna("(unknown)")
                          for d in answer.plan.group_by})
    for m in answer.plan.metrics:
        table[metric_labels[m]] = answer.data[m].map(lambda v, m=m: format_metric(m, v))
    return table


def chart(answer: Answer, metric_labels: dict[str, str]) -> None:
    """A line over years, or bars for one other breakdown; nothing for a single number."""
    plan, data = answer.plan, answer.data
    if len(plan.group_by) != 1 or len(plan.metrics) != 1 or len(data) < 2:
        return
    dimension, metric = plan.group_by[0], plan.metrics[0]
    values = data[[dimension, metric]].dropna()
    label = metric_labels[metric]
    if metric.startswith("share_"):  # stored as 0.78; the axis should read 78
        values[metric], label = values[metric] * 100, f"{label} (%)"
    values = values.rename(columns={dimension: short_name(dimension), metric: label})
    values = values.set_index(short_name(dimension))
    if dimension == "fiscal_year":
        st.line_chart(values.sort_index())
    else:
        st.bar_chart(values.head(CHART_ROWS), horizontal=True, sort=False)
        if len(values) > CHART_ROWS:
            st.caption(f"Chart shows the first {CHART_ROWS} of {len(values)} rows; the table has all.")


def show(answer: Answer, agent: Agent) -> None:
    metric_labels = labels(agent)
    if answer.status != "answered":
        (st.warning if answer.status == "declined" else st.error)(answer.text)
    elif not answer.plan.group_by and len(answer.data) == 1:
        for column, m in zip(st.columns(len(answer.plan.metrics)), answer.plan.metrics, strict=True):
            column.metric(metric_labels[m], format_metric(m, answer.data[m].iloc[0]))
    else:
        st.markdown(answer.text.split("\n\n")[0])  # the heading line; the table follows
        chart(answer, metric_labels)
        st.dataframe(answer_table(answer, metric_labels), hide_index=True)
    for note in answer.notes:
        st.info(note)
    if answer.plan is not None and answer.status == "answered":
        with st.expander("How this was answered"):
            for m in answer.plan.metrics:
                st.markdown(f"**{metric_labels[m]}** (`{m}`): {agent.layer.metrics[m].description}")
            st.markdown("Plan written by the model, after the program's corrections:")
            st.json(answer.plan.as_dict())
            st.markdown("SQL that MetricFlow generated and DuckDB ran:")
            st.code(answer.sql, language="sql")
    tokens = sum(c.output_tokens for c in answer.calls)
    st.caption(f"{answer.seconds:.1f} s · {len(answer.calls)} model call(s) · {tokens} tokens written")


def sidebar(model: str) -> str | None:
    """Returns an example question when one is clicked."""
    st.sidebar.header("About")
    st.sidebar.markdown(
        "Questions about the Medicare Hospital Readmissions Reduction Program, FY2019-FY2026. "
        f"A local model (`{model}`, via Ollama) turns the question into a plan; the numbers come "
        "from the governed semantic layer, never from the model.")
    run = evaluation()
    if run is not None:
        s = run["summary"]["full"]
        st.sidebar.metric("Correct on the 42-question test set", f"{s['accuracy']:.1%}")
        st.sidebar.caption(f"Answerable {s['answerable_correct']}, declines {s['declines_correct']}. "
                           "Wrong metric is the most common error: check the definition under each "
                           "answer.")
    st.sidebar.header("Try")
    clicked = None
    for question in example_questions():
        if st.sidebar.button(question, width="stretch"):
            clicked = question
    if st.sidebar.button("Clear the conversation"):
        st.session_state.history = []
    return clicked


def main() -> None:
    st.set_page_config(page_title="Ask the readmission data", layout="wide")
    st.title("Ask the readmission data")
    model = DEFAULT_MODEL
    clicked = sidebar(model)

    scripted = st.session_state.get("llm")  # set by tests
    if scripted is None and not ollama_running():
        st.error("Ollama is not running. Start the Ollama app, then reload this page.")
        st.stop()
    agent = Agent(scripted) if scripted is not None else ollama_agent(model)

    history: list[Answer] = st.session_state.setdefault("history", [])
    for answer in history:
        with st.chat_message("user"):
            st.markdown(answer.question)
        with st.chat_message("assistant"):
            show(answer, agent)

    question = st.chat_input("e.g. Which states had the highest share of penalized hospitals?") or clicked
    if question:
        with st.chat_message("user"):
            st.markdown(question)
        with st.chat_message("assistant"):
            with st.spinner("Writing a plan and running it (about 15 s; the first question loads "
                            "the model, about a minute)..."):
                try:
                    answer = agent.ask(question)
                except LLMError as exc:
                    st.error(str(exc))
                    st.stop()
            show(answer, agent)
        history.append(answer)


main()
