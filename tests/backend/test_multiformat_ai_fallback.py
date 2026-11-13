"""Rules first, AI investigation when the rules cannot account for a question, saved case otherwise.

Offline: a scripted fake model stands in for Gemini, the database is the small
synthetic fixture, and nothing touches the network.
"""

from __future__ import annotations

import json
from pathlib import Path

import duckdb
import pytest

from backend.app.multiformat.chat import MultiFormatChat
from backend.app.multiformat.investigation import (
    GeminiToolModel,
    Investigator,
    QueryResult,
    ReadOnlyDatabase,
    SqlRejected,
    UnansweredBacklog,
    check_sql,
    unsupported_numbers,
)
from backend.app.multiformat.service import MultiFormatService
from tests.backend.multiformat_fixture import build_fixture_db

RUNS_SQL = (
    "SELECT p.name, sum(d.runs_batter) AS runs FROM analytics.deliveries d "
    "JOIN analytics.players p ON p.player_id = d.batter_id GROUP BY 1 ORDER BY runs DESC"
)


class ScriptedModel:
    """Returns one scripted function call per model turn and records every request."""

    model = "fake-model"

    def __init__(self, *calls: tuple[str, dict]) -> None:
        self.calls = list(calls)
        self.requests: list[dict] = []

    def call(self, payload: dict) -> dict:
        self.requests.append(json.loads(json.dumps(payload)))  # snapshot: contents keep growing
        if not self.calls:
            return {"error": "script exhausted"}
        name, args = self.calls.pop(0)
        return {
            "candidates": [{"content": {"role": "model", "parts": [{"functionCall": {"name": name, "args": args}}]}}],
            "usageMetadata": {"promptTokenCount": 1000, "candidatesTokenCount": 100, "thoughtsTokenCount": 50},
        }


def run_sql(sql: str = RUNS_SQL, purpose: str = "runs by batter") -> tuple[str, dict]:
    return "run_sql", {"sql": sql, "purpose": purpose}


def submit(answer: str, **extra) -> tuple[str, dict]:
    args = {
        "outcome": "answered",
        "showing": "Showing: runs by batter · all recorded matches",
        "answer": answer,
        "tables": [{"query": 1, "title": "Runs by batter"}],
    }
    args.update(extra)
    return "submit_answer", args


@pytest.fixture()
def db(tmp_path: Path) -> Path:
    return build_fixture_db(tmp_path)


@pytest.fixture()
def backlog(tmp_path: Path) -> UnansweredBacklog:
    return UnansweredBacklog(tmp_path / "unanswered.jsonl")


def make_chat(db: Path, model, backlog: UnansweredBacklog | None = None) -> MultiFormatChat:
    investigator = Investigator(model, ReadOnlyDatabase(db), "knowledge pack", backlog=backlog) if model else None
    return MultiFormatChat(MultiFormatService(db), investigator=investigator, backlog=backlog)


def saved(backlog: UnansweredBacklog) -> list[dict]:
    if not backlog.path.exists():
        return []
    return [json.loads(line) for line in backlog.path.read_text().splitlines()]


def path_note(answer) -> str:
    return next(n.detail for n in answer.query_response.evidence_notes if n.title == "How this was answered")


# ------------------------------------------------------------------ hand-off triggers
def test_fully_matched_question_stays_with_the_rules_and_says_so(db, backlog) -> None:
    model = ScriptedModel()
    answer = make_chat(db, model, backlog).answer("How many runs did A Batter score in the IPL?")
    assert answer.query_response.status.value == "supported"
    assert path_note(answer).startswith("Database rules")
    assert "How this was answered: Database rules" in answer.message
    assert answer.query_response.evidence_notes[-1].title == "Afghanistan coverage"
    assert model.requests == []  # the AI is never called
    assert saved(backlog) == []


def test_unmatched_qualifier_hands_off_instead_of_answering_a_simpler_question(db, backlog) -> None:
    model = ScriptedModel(run_sql(), submit("A Batter has 11 runs."))
    answer = make_chat(db, model, backlog).answer("A Batter runs in IPL run chases")
    prompt = model.requests[0]["contents"][0]["parts"][0]["text"]
    assert "Question: A Batter runs in IPL run chases" in prompt  # the WHOLE question
    assert "chases" in prompt  # and why the rules handed it over
    assert path_note(answer).startswith("AI investigation")
    assert answer.query_response.status.value == "supported"


def test_rules_refusal_hands_off(db) -> None:
    model = ScriptedModel(run_sql(), submit("A Batter has 11 runs."))
    answer = make_chat(db, model).answer("Best opening partnerships in the IPL")
    assert model.requests, "a refused question must reach the AI investigation"
    assert "could not answer" in model.requests[0]["contents"][0]["parts"][0]["text"]
    assert path_note(answer).startswith("AI investigation")


def test_without_ai_an_unmatched_question_is_not_answered_and_saved(db, backlog) -> None:
    answer = make_chat(db, None, backlog).answer("A Batter runs in IPL run chases")
    assert answer.query_response.status.value == "unsupported"
    assert not answer.query_response.tables
    assert "“chases”" in answer.message and "saved as a case" in answer.message
    assert path_note(answer).startswith("Not answered")
    [case] = saved(backlog)
    assert case["question"] == "A Batter runs in IPL run chases" and "chases" in case["reason"]


def test_without_ai_a_refusal_keeps_the_rules_explanation_and_is_saved(db, backlog) -> None:
    answer = make_chat(db, None, backlog).answer("Best opening partnerships in the IPL")
    assert "I can't answer the" in answer.message
    assert path_note(answer).startswith("Not answered")
    assert len(saved(backlog)) == 1


# ------------------------------------------------------------------ SQL guardrails
@pytest.mark.parametrize(
    "sql",
    [
        "DELETE FROM analytics.deliveries",
        "INSERT INTO analytics.players VALUES ('x')",
        "CREATE TABLE t AS SELECT 1",
        "DROP TABLE analytics.players",
        "UPDATE analytics.players SET name = 'x'",
        "SELECT 1; SELECT 2",
        "SELECT 1; DROP TABLE analytics.players",
        "ATTACH 'other.duckdb' AS other",
        "COPY (SELECT 1) TO 'out.csv'",
        "PRAGMA database_list",
        "SET threads = 1",
        "SELECT * FROM read_csv('/etc/hosts')",
        "SELECT ll_source FROM analytics.deliveries",
        "WITH x AS (SELECT 1) DELETE FROM analytics.players",
        "EXPLAIN SELECT 1",
        "",
    ],
)
def test_guard_rejects_anything_but_one_read_only_select(sql) -> None:
    with pytest.raises(SqlRejected):
        check_sql(sql, duckdb.connect())


def test_guard_allows_select_and_with_and_ignores_keywords_inside_strings() -> None:
    assert check_sql("WITH a AS (SELECT 1 AS x) SELECT x FROM a;", duckdb.connect())
    assert check_sql("SELECT 'drop; delete' AS note", duckdb.connect())


def test_database_rejects_oversized_results_and_reports_errors(db) -> None:
    database = ReadOnlyDatabase(db, max_rows=3)
    too_big = database.run("SELECT * FROM range(10)")
    assert too_big.error and "more than 3 rows" in too_big.error and not too_big.rows
    assert database.run("SELECT * FROM range(3)").rows == [[0], [1], [2]]
    assert database.run("SELECT nope FROM analytics.deliveries").error.startswith("database error")
    assert database.run("DELETE FROM analytics.deliveries").error.startswith("rejected")


def test_database_stops_slow_queries(db) -> None:
    database = ReadOnlyDatabase(db, timeout_seconds=0.2)
    slow = database.run("SELECT count(*) FROM range(1000000000) a, range(1000) b")
    assert slow.error and "longer than" in slow.error


def test_connection_itself_is_read_only_with_file_access_disabled(db) -> None:
    conn = ReadOnlyDatabase(db).conn
    with pytest.raises(duckdb.Error):
        conn.execute("CREATE TABLE analytics.t AS SELECT 1")
    with pytest.raises(duckdb.Error):
        conn.execute("SELECT * FROM read_csv('/etc/hosts')")
    with pytest.raises(duckdb.Error):
        conn.execute("SET enable_external_access = true")


# ------------------------------------------------------------------ number provenance
def test_every_number_must_come_from_a_query_result() -> None:
    results = [QueryResult(sql="SELECT ... WHERE year >= 2019", purpose="", columns=["runs", "sr"], rows=[[1234, 134.857], [87, 0.4521]])]
    assert unsupported_numbers("1,234 runs at a strike rate of 134.86", results) == []
    assert unsupported_numbers("45.2% of balls", results) == []
    assert unsupported_numbers("2019 runs", results) == ["2019"]
    assert unsupported_numbers("5 runs", results, question="top 5 run scorers") == ["5"]
    assert unsupported_numbers("1,235 runs at 134.9 and 99 fifties", results) == ["1,235", "99"]
    assert unsupported_numbers("4521 runs", results) == ["4521"]
    assert unsupported_numbers("strike rate 134.9", results) == []  # rounding of 134.857
    failed = [QueryResult(sql="SELECT 777", purpose="", error="database error: x")]
    assert unsupported_numbers("777 runs", failed) == ["777"]


def test_fabricated_number_is_sent_back_and_a_corrected_answer_accepted(db) -> None:
    model = ScriptedModel(run_sql(), submit("A Batter has 999 runs."), submit("A Batter has 11 runs."))
    answer = make_chat(db, model).answer("A Batter runs in IPL run chases")
    rejection = model.requests[2]["contents"][-1]["parts"][0]["functionResponse"]["response"]
    assert "999" in rejection["rejected"]
    assert "A Batter has 11 runs." in answer.message
    table = answer.query_response.tables[0]
    assert table.columns == ["name", "runs"] and table.rows[0] == ["A Batter", 11]


def test_repeatedly_unsupported_numbers_end_as_a_saved_case(db, backlog) -> None:
    bad = submit("A Batter has 999 runs.")
    model = ScriptedModel(run_sql(), bad, bad, bad)
    answer = make_chat(db, model, backlog).answer("A Batter runs in IPL run chases")
    assert answer.query_response.status.value == "unsupported"
    assert "couldn't produce a checked answer" in answer.message and "999" in answer.message
    [case] = saved(backlog)
    assert case["path"] == "AI investigation" and case["tried"][0]["sql"] == RUNS_SQL
    assert "chases" in case["handed_off_because"]


def test_tables_must_be_copied_from_successful_queries(db) -> None:
    model = ScriptedModel(
        run_sql("SELECT broken"),
        submit("A Batter has 11 runs."),  # refers to the failed query 1
        run_sql(),
        submit("A Batter has 11 runs.", tables=[{"query": 2, "title": "Runs", "columns": ["runs"]}]),
    )
    answer = make_chat(db, model).answer("A Batter runs in IPL run chases")
    assert answer.query_response.tables[0].columns == ["runs"]
    assert any("SQL query 2" in n.title and RUNS_SQL in n.detail for n in answer.query_response.evidence_notes)
    assert not any(n.title.startswith("SQL query 1") for n in answer.query_response.evidence_notes)


# ------------------------------------------------------------------ outcomes and labels
def test_ai_answer_keeps_showing_line_tables_evidence_and_hides_sources(db) -> None:
    model = ScriptedModel(run_sql(), submit(
        "A Batter has 11 runs according to Cricsheet.",
        limitations=["Line and length come from AUCB for part of the data."],
        definitions="Runs off the bat.",
    ))
    answer = make_chat(db, model).answer("A Batter runs in IPL run chases")
    assert answer.message.startswith("Showing: runs by batter")
    assert "| name | runs |" in answer.message
    assert "Evidence & limitations" in answer.message
    lowered = answer.message.lower()
    assert "cricsheet" not in lowered and "aucb" not in lowered
    titles = [n.title for n in answer.query_response.evidence_notes]
    assert titles[0] == "How this was answered" and titles[-1] == "Afghanistan coverage"
    assert "fake-model" in path_note(answer) and "1 read-only database query" in path_note(answer)


def test_ai_may_ask_a_clarification(db, backlog) -> None:
    model = ScriptedModel(("submit_answer", {
        "outcome": "clarify",
        "clarification_question": "Which Batter do you mean?",
        "clarification_options": ["A Batter", "Another Batter"],
    }))
    answer = make_chat(db, model, backlog).answer("A Batter runs in IPL run chases")
    assert answer.message == "Which Batter do you mean?"
    assert [option.rsplit("(", 1)[-1].rstrip(")") for option in answer.clarification] == ["A Batter", "Another Batter"]
    assert saved(backlog) == []


def test_cannot_answer_is_explained_and_saved(db, backlog) -> None:
    model = ScriptedModel(run_sql(), ("submit_answer", {"outcome": "cannot_answer", "reason": "chase results are not recorded"}))
    answer = make_chat(db, model, backlog).answer("A Batter runs in IPL run chases")
    assert "Why: chase results are not recorded" in answer.message
    assert path_note(answer).startswith("Not answered")
    assert saved(backlog)[0]["reason"] == "chase results are not recorded"


def test_query_and_turn_limits_end_the_investigation(db, backlog) -> None:
    model = ScriptedModel(*[run_sql()] * 20)
    investigator = Investigator(model, ReadOnlyDatabase(db), "pack", max_queries=3, max_turns=5, backlog=backlog)
    result = investigator.investigate("question", "reason")
    assert result.outcome == "not_answered" and len(result.queries) == 3 and result.model_calls == 5
    assert "query limit" in json.dumps(model.requests[-1]["contents"][-1])
    assert len(saved(backlog)) == 1


def test_model_responses_are_cached_and_replayed_offline(tmp_path) -> None:
    model = GeminiToolModel("not-used", "gemini-test", tmp_path, offline=True)
    payload = {"contents": [{"role": "user", "parts": [{"text": "q"}]}]}
    assert model.call(payload) == {"error": "missing offline capture"}
    path = model.cache_path(payload)
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"candidates": [], "cached": True}))
    assert model.call(payload)["cached"] is True
    assert model.paid_calls == 0


def test_cost_is_reported_per_question(db) -> None:
    model = ScriptedModel(run_sql(), submit("A Batter has 11 runs."))
    model.model = "gemini-3.1-pro-preview"
    result = Investigator(model, ReadOnlyDatabase(db), "pack").investigate("q", "r")
    assert result.prompt_tokens == 2000 and result.output_tokens == 300
    assert result.cost_usd == round((2000 * 2 + 300 * 12) / 1_000_000, 4)


def test_odi_refusal_reaches_the_ai_through_the_chat_service(db) -> None:
    from backend.app.domain.evidence_models import EvidenceStatus, QueryInterpretation, QueryResponse
    from backend.app.services.chat_service import ChatReply, ChatService

    model = ScriptedModel(run_sql(), submit("A Batter has 11 runs."))
    service = ChatService(repository=None, query_handler=None, gemini_client=None, multiformat=make_chat(db, model))
    refusal = ChatReply(mode="analysis", message="unsupported", query_response=QueryResponse(
        status=EvidenceStatus.unsupported,
        interpretation=QueryInterpretation(original_question="q", query_class="x"),
    ))
    reply = service._investigate_odi_refusal("Kohli's ODI runs in successful chases", refusal)
    assert "AI investigation" in reply.activity_trace
    assert "ODI database rules could not answer" in model.requests[0]["contents"][0]["parts"][0]["text"]
    assert reply.query_response.status.value == "supported"


def test_investigation_connection_does_not_lock_the_apps_own_connections(db) -> None:
    first, second = ReadOnlyDatabase(db), ReadOnlyDatabase(db)  # two investigators in one process
    assert first.run("SELECT count(*) FROM analytics.deliveries").rows == second.run(
        "SELECT count(*) FROM analytics.deliveries"
    ).rows
    with duckdb.connect(str(db), read_only=True) as app_conn:
        assert app_conn.execute("SELECT current_setting('enable_external_access')").fetchone() == (True,)


@pytest.mark.parametrize("fields", [
    {"tables": [{"query": "not-a-number"}]},
    {"tables": ["invalid-table"]},
    {"tables": [{"query": 1, "max_rows": [1]}]},
])
def test_malformed_submissions_become_saved_cases(db, backlog, fields) -> None:
    model = ScriptedModel(run_sql(), *[submit("11 runs", **fields)] * 3)
    result = Investigator(model, ReadOnlyDatabase(db), "pack", backlog=backlog).investigate("q", "r")
    assert result.outcome == "not_answered"
    assert len(saved(backlog)) == 1


def test_model_exception_is_saved_without_exposing_error_details(db, backlog) -> None:
    class BrokenModel:
        model = "fake-model"

        def call(self, payload):
            raise RuntimeError("private transport details")

    result = Investigator(BrokenModel(), ReadOnlyDatabase(db), "pack", backlog=backlog).investigate("q", "r")
    assert result.outcome == "not_answered" and "RuntimeError" in result.failure
    assert "private" not in result.failure
    assert len(saved(backlog)) == 1


def test_table_title_numbers_are_checked(db, backlog) -> None:
    bad = submit("11 runs", tables=[{"query": 1, "title": "999 runs"}])
    result = Investigator(ScriptedModel(run_sql(), bad, bad, bad), ReadOnlyDatabase(db), "pack", backlog=backlog).investigate("q", "r")
    assert result.outcome == "not_answered" and "999" in result.failure


def test_select_star_cannot_expose_hidden_source_columns(db) -> None:
    result = ReadOnlyDatabase(db).run("SELECT * FROM analytics.deliveries LIMIT 1")
    assert result.error and "source-identifying" in result.error
    assert not result.rows


@pytest.mark.parametrize("qualifier", ["after the powerplay", "on the first ball", "by season"])
def test_known_words_in_an_unsupported_combination_still_hand_off(db, qualifier) -> None:
    model = ScriptedModel(run_sql(), submit("A Batter has 11 runs."))
    answer = make_chat(db, model).answer("A Batter runs in IPL " + qualifier)
    assert model.requests
    assert path_note(answer).startswith("AI investigation")
