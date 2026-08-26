from __future__ import annotations

from functools import lru_cache

from backend.app.config import AppConfig
from backend.app.db.repository import AnalyticsRepository
from backend.app.domain.metric_models import QueryClass
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.answer_composer import AnswerComposer
from backend.app.services.chat_service import ChatService
from backend.app.services.follow_up_suggester import suggest_follow_ups
from backend.app.services.gemini_client import GeminiClient
from backend.app.services.grounded_context import GroundedContextService
from backend.app.services.metric_catalog import MetricCatalog
from backend.app.services.query_interpreter import QueryInterpreter
from backend.app.services.workbench_service import WorkbenchService


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
    query_interpreter = QueryInterpreter(
        repository=repository,
        gemini_client=gemini_client,
        fallback_router=analytics_service.router,
    )
    grounded_context = GroundedContextService(gemini_client)
    answer_composer = AnswerComposer()
    semantic_service = SemanticAnalyticsService(
        repository=repository,
        gemini_client=gemini_client,
        app_env=config.app_env,
        allow_dev_fallback=config.semantic_v2_dev_fallback,
    )

    def query_handler(question: str):
        if config.use_semantic_analytics_v2:
            semantic_response = semantic_service.answer_question(question)
            grounded_notes, grounded_citations = grounded_context.gather(question, semantic_response)
            query_class = QueryClass(semantic_response.interpretation.query_class)
            follow_ups = suggest_follow_ups(query_class)
            return answer_composer.compose(semantic_response, grounded_notes, grounded_citations, follow_ups)

        interpreted = query_interpreter.interpret(question)
        response = analytics_service.answer_route(question, interpreted.route)
        grounded_notes, grounded_citations = grounded_context.gather(question, response)
        query_class = QueryClass(response.interpretation.query_class)
        follow_ups = suggest_follow_ups(query_class)
        return answer_composer.compose(response, grounded_notes, grounded_citations, follow_ups)

    def legacy_query_handler(question: str):
        interpreted = query_interpreter.interpret(question)
        response = analytics_service.answer_route(question, interpreted.route)
        grounded_notes, grounded_citations = grounded_context.gather(question, response)
        query_class = QueryClass(response.interpretation.query_class)
        follow_ups = suggest_follow_ups(query_class)
        return answer_composer.compose(response, grounded_notes, grounded_citations, follow_ups)

    def matchup_handler(**filters):
        return semantic_service.answer_matchup_page(**filters)

    chat_service = ChatService(
        repository=repository,
        query_handler=query_handler,
        gemini_client=gemini_client,
    )
    workbench_service = WorkbenchService(
        repository=repository,
        query_handler=legacy_query_handler,
        gemini_client=gemini_client,
    )

    return {
        "config": config,
        "repository": repository,
        "analytics_service": analytics_service,
        "query_interpreter": query_interpreter,
        "semantic_service": semantic_service,
        "query_handler": query_handler,
        "matchup_handler": matchup_handler,
        "chat_service": chat_service,
        "workbench_service": workbench_service,
    }
