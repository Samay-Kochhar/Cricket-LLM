from __future__ import annotations

from functools import lru_cache

from backend.app.config import AppConfig
from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.metric_models import QueryClass
from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.answer_composer import AnswerComposer
from backend.app.services.follow_up_suggester import suggest_follow_ups
from backend.app.services.gemini_client import GeminiClient
from backend.app.services.grounded_context import GroundedContextService
from backend.app.services.metric_catalog import MetricCatalog


@lru_cache
def get_services():
    config = AppConfig.from_env()
    repository = AnalyticsRepository(config.duckdb_path)
    metric_catalog = MetricCatalog()
    analytics_service = AnalyticsService(repository=repository, metric_catalog=metric_catalog)
    gemini_client = GeminiClient(
        api_key=config.gemini_api_key,
        default_model=config.gemini_default_model,
        complex_model=config.gemini_complex_model,
    )
    grounded_context = GroundedContextService(gemini_client)
    answer_composer = AnswerComposer()

    def query_handler(question: str):
        response = analytics_service.answer_question(question)
        grounded_notes, grounded_citations = grounded_context.gather(question)
        query_class = QueryClass(response.interpretation.query_class)
        follow_ups = suggest_follow_ups(query_class)
        return answer_composer.compose(response, grounded_notes, grounded_citations, follow_ups)

    return {
        "config": config,
        "repository": repository,
        "query_handler": query_handler,
    }
