"""Offline contracts: paid capture once, durable failures, and usage fidelity."""

import json

import pytest

from backend.app.multiformat.model_planner import GeminiPlanner
from backend.app.multiformat.plans import ScopePlan, UnderstandingPlan
from backend.app.services.gemini_client import GeminiStructuredResult


class Names:
    competitions = []

    def spot(self, question):
        return []


class Reader:
    names = Names()

    def read(self, question):
        return UnderstandingPlan(
            scopes=[ScopePlan(label="IPL", competition="Indian Premier League")]
        )


class Client:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def generate_structured(self, prompt, **kwargs):
        self.calls.append(kwargs)
        return self.result


@pytest.mark.parametrize("error", [None, "http_400", "http_429", "http_error"])
def test_capture_and_failure_replay_never_repeat_paid_call(tmp_path, error):
    raw = UnderstandingPlan(players=["V Kohli"], scopes=Reader().read("").scopes)
    client = Client(
        GeminiStructuredResult(
            text=raw.model_dump_json() if not error else None,
            selected_model="test-model",
            model_version="v1",
            finish_reason="STOP" if not error else None,
            latency_ms=1,
            prompt_token_count=100,
            output_token_count=50,
            thoughts_token_count=20,
            total_token_count=170,
            error_kind=error,
        )
    )
    planner = GeminiPlanner(client, "test-model", Reader(), tmp_path)
    first = planner.read("IPL test question")
    replay = GeminiPlanner(client, "test-model", Reader(), tmp_path, offline=True).read(
        "IPL test question"
    )
    assert first == replay
    assert len(client.calls) == 1
    assert client.calls[0]["max_output_tokens"] == 4096
    assert client.calls[0]["thinking_level"] == "low"
    saved = json.loads(planner.cache_path("IPL test question").read_text())
    assert saved["response"]["total_token_count"] == 170
    assert saved["response"]["thoughts_token_count"] == 20
    assert first == (Reader().read("IPL test question") if error else raw)
    assert bool(planner.diagnostic("IPL test question")) == bool(error)
    planner.read("IPL test question")
    assert len(client.calls) == 1


def test_offline_missing_capture_uses_standard_reader_without_call(tmp_path):
    client = Client(None)
    planner = GeminiPlanner(client, "test-model", Reader(), tmp_path, offline=True)
    result = planner.read("uncaptured IPL question")
    assert result == Reader().read("uncaptured IPL question")
    assert "standard question reader" in planner.diagnostic("uncaptured IPL question")
    assert client.calls == []


def test_cache_changes_with_model_pack_and_question(tmp_path):
    planner = GeminiPlanner(Client(None), "model-a", Reader(), tmp_path, offline=True)
    path = planner.cache_path("question")
    assert planner.cache_path("different question") != path
    planner.model = "model-b"
    assert planner.cache_path("question") != path
    planner.model = "model-a"
    planner.pack += "\nchanged policy"
    assert planner.cache_path("question") != path


def test_structured_client_sends_low_thinking_and_records_all_usage(monkeypatch):
    import httpx
    from backend.app.services.gemini_client import GeminiClient

    captured = []

    def post(url, **kwargs):
        captured.append(kwargs["json"])
        return httpx.Response(
            200,
            request=httpx.Request("POST", url),
            json={
                "candidates": [
                    {"finishReason": "STOP", "content": {"parts": [{"text": "{}"}]}}
                ],
                "usageMetadata": {
                    "promptTokenCount": 100,
                    "candidatesTokenCount": 30,
                    "thoughtsTokenCount": 40,
                    "totalTokenCount": 170,
                },
            },
        )

    monkeypatch.setattr("backend.app.services.gemini_client.httpx.post", post)
    result = GeminiClient("fake-test-key", "fake", "fake").generate_structured(
        "test",
        response_schema={"type": "object"},
        max_output_tokens=4096,
        thinking_level="low",
    )
    assert captured[0]["generationConfig"]["thinkingConfig"] == {"thinkingLevel": "low"}
    assert (
        result.prompt_token_count,
        result.output_token_count,
        result.thoughts_token_count,
        result.total_token_count,
    ) == (100, 30, 40, 170)


def test_invalid_json_is_durable_failure_without_paid_retry(tmp_path):
    client = Client(
        GeminiStructuredResult(
            text='{"intent":',
            selected_model="fake",
            model_version="fake",
            finish_reason="MAX_TOKENS",
            latency_ms=1,
        )
    )
    planner = GeminiPlanner(client, "fake", Reader(), tmp_path)
    assert planner.read("IPL question") == Reader().read("IPL question")
    assert planner.read("IPL question") == Reader().read("IPL question")
    record = json.loads(planner.cache_path("IPL question").read_text())
    assert record["response"]["finish_reason"] == "MAX_TOKENS"
    assert record["error"] == "invalid structured plan"
    assert len(client.calls) == 1


def test_competition_list_order_is_stable_so_the_capture_key_never_drifts(tmp_path):
    """Competitions sharing a name across formats must not reorder between
    processes: the knowledge pack (and so the paid-capture cache key) depends on it."""
    import duckdb

    from backend.app.multiformat.knowledge import knowledge_pack
    from backend.app.multiformat.service import MultiFormatService
    from backend.app.multiformat.understanding import NameIndex
    from tests.backend.multiformat_fixture import build_fixture_db

    db = build_fixture_db(tmp_path)
    conn = duckdb.connect(str(db))
    conn.execute(
        "INSERT INTO analytics.coverage (format, gender, competition, matches) VALUES "
        "('List A domestic', 'male', 'Tour X', 1), ('First-class domestic', 'male', 'Tour X', 1), "
        "('T20 (other international)', 'male', 'Cup Y', 1), ('List A (other international)', 'male', 'Cup Y', 1)"
    )
    conn.close()
    competitions = NameIndex(MultiFormatService(db)).competitions
    keys = [(r["competition"], r["format"], r["gender"]) for r in competitions]
    assert keys == sorted(keys)
    assert knowledge_pack(competitions) == knowledge_pack(
        NameIndex(MultiFormatService(db)).competitions
    )
