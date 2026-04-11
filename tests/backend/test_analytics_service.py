from backend.app.services.analytics_service import AnalyticsService
from backend.app.services.metric_catalog import MetricCatalog


class StubRepository:
    def list_player_names(self) -> list[str]:
        return ["Virat Kohli", "Steven Smith"]

    def list_venues(self) -> list[str]:
        return ["M Chinnaswamy Stadium"]


def test_analytics_service_initializes_router_and_venues() -> None:
    service = AnalyticsService(repository=StubRepository(), metric_catalog=MetricCatalog())

    assert service.router is not None
    assert "M Chinnaswamy Stadium" in service.available_venues
