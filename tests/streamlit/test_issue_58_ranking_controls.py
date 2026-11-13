from __future__ import annotations

import duckdb
import pytest
from streamlit.testing.v1 import AppTest

import streamlit_app
from backend.app.cricket_analytics.ranking_controls import controlled_plan
from backend.app.cricket_analytics.schemas import CricketQueryPlan, MinimumSampleSpec, SortSpec
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.services.chat_service import ChatReply, ChatService


class Gemini:
    def is_configured(self) -> bool:
        return False


class Repository:
    def __init__(self) -> None:
        self.connection = duckdb.connect(":memory:")
        self.connection.execute("CREATE SCHEMA analytics")
        # Every wicket in this fixture is the striker's own; declare that identity
        # explicitly (production never infers who was out from the striker's flag).
        self.connection.execute(
            """CREATE TABLE analytics.deliveries_v1 (
                bat VARCHAR, bowl VARCHAR, team_bat VARCHAR, team_bowl VARCHAR,
                p_match INTEGER, inns INTEGER, ballfaced INTEGER, wide INTEGER,
                noball INTEGER, batruns INTEGER, bowlruns INTEGER, dismissal VARCHAR,
                out VARCHAR, control INTEGER, length VARCHAR, over INTEGER,
                bowl_kind VARCHAR, ground VARCHAR, year INTEGER,
                p_bat VARCHAR GENERATED ALWAYS AS (bat) VIRTUAL, p_out VARCHAR GENERATED ALWAYS AS (CASE WHEN LOWER(CAST(out AS VARCHAR)) = 'true' THEN bat END) VIRTUAL
            )"""
        )
        rows = [
            ("A", "A", 1, 1, 6), ("A", "A", 1, 2, 6),
            ("B", "B", 2, 1, 4), ("B", "B", 3, 1, 4),
            ("C", "C", 4, 1, 1), ("C", "C", 5, 1, 1),
        ]
        for batter, bowler, match, innings, runs in rows:
            self.connection.execute(
                "INSERT INTO analytics.deliveries_v1 VALUES (?, ?, 'India', 'Australia', ?, ?, 1, 0, 0, ?, ?, '', 'false', 1, 'GOOD', 2, 'pace bowler', 'The Oval', 2023)",
                [batter, bowler, match, innings, runs, {"A": 0, "B": 2, "C": 4}[bowler]],
            )
        # This delivery would dominate without the year and venue filters.
        self.connection.execute(
            "INSERT INTO analytics.deliveries_v1 VALUES ('A', 'A', 'India', 'Australia', 6, 1, 1, 0, 0, 100, 0, '', 'false', 1, 'GOOD', 2, 'pace bowler', 'Other', 2022)"
        )
        self.last_sql = ""
        self.last_params: list[object] = []

    def list_player_names(self) -> list[str]:
        return ["A", "B", "C"]

    def list_venues(self) -> list[str]:
        return ["The Oval", "Other"]

    def list_teams(self) -> list[str]:
        return ["India", "Australia"]

    def _fetchall(self, sql: str, params: list[object]):
        self.last_sql = sql
        self.last_params = params
        return self.connection.execute(sql, params).fetchall()


@pytest.fixture
def service():
    repository = Repository()
    yield SemanticAnalyticsService(repository, Gemini(), app_env="development"), repository
    repository.connection.close()


def plan(entity: str) -> CricketQueryPlan:
    metric = "batting_strike_rate" if entity == "batter" else "economy_rate"
    unit = "balls" if entity == "batter" else "legal_balls"
    return CricketQueryPlan(
        operation="aggregate", entity=entity, metric=metric, group_by=[entity],
        filters={"phase": "powerplay", "bowling_style": "pace", "venue": "The Oval", "years": [2023]},
        sort=SortSpec(by=metric, direction="desc" if entity == "batter" else "asc"),
        minimum_sample=MinimumSampleSpec(**{unit: 2}), limit=2,
    )


@pytest.mark.parametrize("entity,unit", [("batter", "balls"), ("bowler", "legal_balls")])
def test_matching_and_sorting_recalculate_before_limit(service, entity, unit):
    analytics, repository = service
    base = plan(entity)
    question = "The Oval powerplay pace ranking in 2023, resolved from 'second'"
    first = analytics.answer_ranking_plan(question, base)
    assert first.status.value == "supported"
    assert first.tables[0].rows[0][0] == "A"
    assert first.tables[0].rows[0][first.tables[0].columns.index("Matches")] == 1

    matches_plan = controlled_plan(base, unit="matches", minimum=2, sort_by=base.metric, direction=base.sort.direction)
    assert matches_plan.minimum_sample_explicit is True
    matches = analytics.answer_ranking_plan(question, matches_plan)
    assert [row[0] for row in matches.tables[0].rows] == ["B", "C"]
    assert "COUNT(DISTINCT p_match) AS matches" in repository.last_sql
    assert "matches >= ?" in repository.last_sql
    assert repository.last_params[:4] == [10.0, "pace bowler", "The Oval", 2023]
    assert matches.interpretation.original_question == question
    assert matches.ranking_plan["filters"] == base.model_dump()["filters"]
    assert "minimum sample of 2 matches" in matches.summaries[0].body

    sort_column = "runs_scored" if entity == "batter" else "runs_conceded"
    ascending = controlled_plan(base, unit=unit, minimum=2, sort_by=sort_column, direction="asc")
    descending = controlled_plan(base, unit=unit, minimum=2, sort_by=sort_column, direction="desc")
    assert ascending.minimum_sample_explicit is False
    assert analytics.answer_ranking_plan(question, ascending).tables[0].rows[0][0] == ("C" if entity == "batter" else "A")
    assert analytics.answer_ranking_plan(question, descending).tables[0].rows[0][0] == ("A" if entity == "batter" else "C")


def test_invalid_control_fails_without_rewriting_plan():
    base = plan("batter")
    for unit, minimum, sort_by, direction in [
        ("legal_balls", 2, base.metric, "asc"),
        ("matches", -1, base.metric, "asc"),
        ("matches", 1.5, base.metric, "asc"),
        ("matches", True, base.metric, "asc"),
        ("matches", 1_000_001, base.metric, "asc"),
        ("matches", 2, "not_a_column", "asc"),
        ("matches", 2, base.metric, "sideways"),
    ]:
        with pytest.raises(ValueError):
            controlled_plan(base, unit=unit, minimum=minimum, sort_by=sort_by, direction=direction)
    assert base.minimum_sample.balls == 2
    assert base.sort.direction == "desc"
    no_default = base.model_copy(update={"minimum_sample": None})
    sort_only = controlled_plan(no_default, unit="balls", minimum=0, sort_by="runs_scored", direction="asc")
    assert sort_only.minimum_sample is None
    assert sort_only.minimum_sample_explicit is False


@pytest.mark.parametrize("entity,unit", [("batter", "balls"), ("bowler", "legal_balls")])
def test_clearing_minimum_does_not_reapply_default(service, entity, unit):
    analytics, repository = service
    base = plan(entity)
    base.minimum_sample = MinimumSampleSpec(**{unit: 100})
    changed = controlled_plan(base, unit=unit, minimum=0, sort_by=base.metric, direction=base.sort.direction)
    result = analytics.answer_ranking_plan("rank players", changed)
    assert result.status.value == "supported"
    assert result.ranking_plan["minimum_sample"] is None
    assert "sample_balls >= ?" not in repository.last_sql
    assert "legal_balls >= ?" not in repository.last_sql


def test_sort_only_preserves_all_original_sample_qualifications(service):
    analytics, _ = service
    base = plan("batter")
    base.minimum_sample = MinimumSampleSpec(balls=2, matches=2)
    changed = controlled_plan(base, unit="balls", minimum=2, sort_by="runs_scored", direction="desc")
    assert changed.minimum_sample == base.minimum_sample
    response = analytics.answer_ranking_plan("rank players", changed)
    assert [row[0] for row in response.tables[0].rows] == ["B", "C"]
    reply = ChatReply(mode="analysis", message=response.summaries[0].body, query_response=response)
    app = AppTest.from_string(
        "import streamlit as st\nfrom streamlit_app import render_reply\nrender_reply(st.session_state.messages[0]['reply'], 0)"
    )
    app.session_state.messages = [{"reply": reply.model_dump(mode="json")}]
    app.run()
    assert not app.exception
    assert any("minimum 2 balls faced and 2 matches" in item.value for item in app.caption)


def test_bowling_sample_excludes_wides_and_no_balls(service):
    analytics, repository = service
    for wide, noball in [(0, 0), (1, 0), (0, 1), (1, 0)]:
        repository.connection.execute(
            "INSERT INTO analytics.deliveries_v1 VALUES ('D', 'D', 'India', 'Australia', 10, 1, 1, ?, ?, 1, 0, '', 'false', 1, 'GOOD', 2, 'pace bowler', 'The Oval', 2023)",
            [wide, noball],
        )
    response = analytics.answer_ranking_plan("rank bowlers", plan("bowler"))
    assert [row[0] for row in response.tables[0].rows] == ["A", "B"]
    changed = controlled_plan(plan("bowler"), unit="legal_balls", minimum=1, sort_by="economy_rate", direction="asc")
    result = analytics.answer_ranking_plan("rank bowlers", changed)
    assert [row[0] for row in result.tables[0].rows] == ["D", "A"]
    assert result.tables[0].rows[0][result.tables[0].columns.index("Legal Balls")] == 1


@pytest.mark.parametrize("entity", ["batter", "bowler"])
def test_streamlit_apply_and_reset_preserve_resolved_question(service, monkeypatch, entity):
    analytics, _ = service
    monkeypatch.setattr(streamlit_app, "initialize_services", lambda *_: {"semantic_service": analytics})
    base = plan(entity)
    question = "The Oval powerplay pace ranking in 2023, resolved from 'second'"
    response = analytics.answer_ranking_plan(question, base)
    reply = ChatReply(mode="analysis", message=response.summaries[0].body, query_response=response).model_dump(mode="json")
    app = AppTest.from_string(
        """import streamlit as st
from streamlit_app import render_reply
for index, message in enumerate(st.session_state.messages):
    render_reply(message['reply'], index)
"""
    )
    app.session_state.messages = [{"role": "assistant", "reply": reply, "base_reply": reply}]
    app.run()
    assert not app.exception
    assert [widget.label for widget in app.selectbox] == ["Minimum sample unit", "Sort column", "Sort direction"]
    unit_label = "balls faced" if entity == "batter" else "legal balls"
    assert any(f"minimum 2 {unit_label}" in item.value for item in app.caption)

    app.selectbox[0].select("matches")
    app.number_input[0].set_value(2)
    app.button[0].click().run()
    assert not app.exception
    changed = app.session_state.messages[0]["reply"]
    assert changed["query_response"]["tables"][0]["rows"][0][0] == "B"
    assert changed["query_response"]["interpretation"]["original_question"] == question
    assert changed["query_response"]["ranking_plan"]["filters"] == base.model_dump()["filters"]

    app.button[1].click().run()
    assert not app.exception
    assert app.session_state.messages[0]["reply"] == reply

    app.number_input[0].set_value(100).run()
    app.button[0].click().run()
    assert not app.exception
    assert app.error
    assert not app.dataframe
    assert not any("ranks first" in item.value for item in app.markdown)
    assert app.session_state.messages[0]["reply"] == reply

    # Unrelated reruns must not resurrect the stale answer after a failed apply.
    app.run()
    assert app.error
    assert not app.dataframe
    assert not any("ranks first" in item.value for item in app.markdown)

    app.button[1].click().run()
    assert not app.exception
    assert not app.error
    assert app.number_input[0].value == 2
    assert app.selectbox[0].value == ("balls" if entity == "batter" else "legal_balls")
    assert app.session_state.messages[0]["reply"] == reply
    assert app.dataframe


@pytest.mark.parametrize("entity,sort_by", [("batter", "runs_scored"), ("bowler", "runs_conceded")])
@pytest.mark.parametrize("direction", ["asc", "desc"])
def test_selected_sort_drives_headline_and_chart(service, entity, sort_by, direction):
    analytics, _ = service
    changed = controlled_plan(plan(entity), unit="matches", minimum=2, sort_by=sort_by, direction=direction)
    response = analytics.answer_ranking_plan("rank players", changed)
    table = response.tables[0]
    sort_label = sort_by.replace("_", " ").title()
    leader = table.rows[0][0]
    assert f"{leader} ranks first for {sort_label}" in response.summaries[0].body
    assert ("lowest first" if direction == "asc" else "highest first") in response.summaries[0].body
    assert "minimum sample of 2 matches" in response.summaries[0].body
    assert len(response.charts) == 1
    assert sort_label in response.charts[0].title
    index = table.columns.index(sort_label)
    assert response.charts[0].series == [
        {"label": row[0], "value": row[index]} for row in table.rows
    ]


def test_short_clarification_context_survives_streamlit_controls(service, monkeypatch):
    analytics, repository = service
    chat = ChatService(repository, analytics.answer_question, Gemini())
    question = "Who has the highest strike rate in powerplay against pace at The Oval in 2023, minimum 2 balls?"
    clarification = chat.reply(question, [])
    assert clarification.mode == "clarification"
    resolved = chat.reply("first", [], clarification.conversation_state)
    assert resolved.query_response.status.value == "supported"
    original_plan = resolved.query_response.ranking_plan
    assert original_plan["metric"] == "batting_strike_rate"
    assert original_plan["filters"] == {
        "phase": "powerplay", "bowling_style": "pace", "venue": "The Oval", "years": [2023],
    }
    monkeypatch.setattr(streamlit_app, "initialize_services", lambda *_: {"semantic_service": analytics})
    app = AppTest.from_string(
        "import streamlit as st\nfrom streamlit_app import render_reply\nrender_reply(st.session_state.messages[0]['reply'], 0)"
    )
    app.session_state.messages = [{"reply": resolved.model_dump(mode="json")}]
    app.run()
    app.selectbox[0].select("matches")
    app.number_input[0].set_value(2)
    app.selectbox[1].select("runs_scored")
    app.selectbox[2].select("asc")
    app.button[0].click().run()
    assert not app.exception
    response = app.session_state.messages[0]["reply"]["query_response"]
    assert response["ranking_plan"]["filters"] == original_plan["filters"]
    assert response["ranking_plan"]["metric"] == original_plan["metric"]
    assert response["interpretation"]["original_question"] == resolved.query_response.interpretation.original_question
    assert [row[0] for row in response["tables"][0]["rows"]] == ["C", "B"]
    assert "C ranks first for Runs Scored" in app.session_state.messages[0]["reply"]["message"]
    assert response["charts"][0]["series"] == [{"label": "C", "value": 2}, {"label": "B", "value": 8}]

    app.selectbox[2].select("desc")
    app.button[0].click().run()
    assert not app.exception
    assert app.dataframe[0].value.iloc[0]["Batter"] == "B"
    app.button[1].click().run()
    assert not app.exception
    assert app.session_state.messages[0]["reply"] == resolved.model_dump(mode="json")
    assert app.selectbox[1].value == "batting_strike_rate"
    assert app.selectbox[2].value == "desc"


def test_execution_failure_stays_hidden_until_successful_retry(service, monkeypatch):
    analytics, _ = service
    reply = ChatReply(mode="analysis", message="Original answer", query_response=analytics.answer_ranking_plan("rank players", plan("batter")))
    def unavailable(*_):
        raise RuntimeError("Temporary connection failure")
    monkeypatch.setattr(streamlit_app, "initialize_services", unavailable)
    app = AppTest.from_string(
        "import streamlit as st\nfrom streamlit_app import render_reply\nrender_reply(st.session_state.messages[0]['reply'], 0)"
    )
    app.session_state.messages = [{"reply": reply.model_dump(mode="json")}]
    app.run()
    app.button[0].click().run()
    app.run()
    assert not app.exception
    assert app.error
    assert not app.dataframe
    assert not any(item.value == "Original answer" for item in app.markdown)
    monkeypatch.setattr(streamlit_app, "initialize_services", lambda *_: {"semantic_service": analytics})
    app.button[0].click().run()
    assert not app.exception
    assert not app.error
    assert app.dataframe


@pytest.mark.parametrize("entity", ["batter", "bowler"])
def test_apply_updates_reply_before_rendering_any_answer(service, monkeypatch, entity):
    analytics, _ = service
    monkeypatch.setattr(streamlit_app, "initialize_services", lambda *_: {"semantic_service": analytics})
    response = analytics.answer_ranking_plan("rank players", plan(entity))
    reply = ChatReply(mode="analysis", message=response.summaries[0].body, query_response=response)
    rendered_leaders = []
    original_render = streamlit_app.render_reply

    def record_render(data, index):
        rendered_leaders.append(data["query_response"]["tables"][0]["rows"][0][0])
        original_render(data, index)

    monkeypatch.setattr(streamlit_app, "render_reply", record_render)
    app = AppTest.from_string(
        "import streamlit as st\nfrom streamlit_app import render_reply\nrender_reply(st.session_state.messages[0]['reply'], 0)"
    )
    app.session_state.messages = [{"reply": reply.model_dump(mode="json")}]
    app.run()
    rendered_leaders.clear()
    app.selectbox[0].select("matches")
    app.number_input[0].set_value(2)
    app.button[0].click().run()
    assert not app.exception
    assert rendered_leaders == ["B"]
    answers = [item.value for item in app.markdown if "ranks first" in item.value]
    assert len(answers) == 2
    assert all("B ranks first" in answer for answer in answers)
    assert app.dataframe[0].value.iloc[0, 0] == "B"


def test_full_page_ten_match_apply_keeps_both_answers_and_chart_together(service, monkeypatch):
    analytics, repository = service
    repository.connection.execute(
        "UPDATE analytics.deliveries_v1 SET bat = CASE bat WHEN 'A' THEN 'Asif Khan' WHEN 'B' THEN 'Vriitya Aravind' ELSE bat END"
    )
    for batter, runs in [("Vriitya Aravind", 1), ("C", 0)]:
        for match in range(10, 18):
            repository.connection.execute(
                "INSERT INTO analytics.deliveries_v1 VALUES (?, 'B', 'India', 'Australia', ?, 1, 1, 0, 0, ?, 0, '', 'false', 1, 'GOOD', 2, 'pace bowler', 'The Oval', 2023)",
                [batter, match, runs],
            )
    monkeypatch.setattr(streamlit_app, "initialize_services", lambda *_: {"semantic_service": analytics})
    monkeypatch.setattr(streamlit_app, "apply_cloud_secrets", lambda: None)
    response = analytics.answer_ranking_plan("rank powerplay batting against pace at The Oval in 2023", plan("batter"))
    reply = ChatReply(mode="analysis", message=response.summaries[0].body, query_response=response)
    app = AppTest.from_string("from streamlit_app import render_page\nrender_page()")
    app.session_state.messages = [{"role": "assistant", "reply": reply.model_dump(mode="json")}]
    app.run()
    assert not app.exception

    for unit, minimum, expected in [
        ("matches", 10, "Vriitya Aravind"),
        ("balls", 2, "Asif Khan"),
        ("matches", 10, "Vriitya Aravind"),
    ]:
        app.selectbox[0].select(unit)
        app.number_input[0].set_value(minimum)
        next(button for button in app.button if button.label == "Apply").click().run()
        assert not app.exception
        answers = [item.value for item in app.markdown if "ranks first" in item.value]
        assert len(answers) == 2
        assert all(f"{expected} ranks first" in answer for answer in answers)
        assert app.dataframe[0].value.iloc[0]["Batter"] == expected
        saved = app.session_state.messages[0]
        assert saved["content"] == saved["reply"]["message"] == answers[0] == answers[1]
        assert saved["reply"]["query_response"]["charts"][0]["series"][0]["label"] == expected

    next(button for button in app.button if button.label == "Reset").click().run()
    assert not app.exception
    assert app.session_state.messages[0]["reply"] == reply.model_dump(mode="json")
    assert all("Asif Khan ranks first" in item.value for item in app.markdown if "ranks first" in item.value)
