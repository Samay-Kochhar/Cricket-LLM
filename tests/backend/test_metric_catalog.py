from backend.app.domain.metric_models import QueryClass
from backend.app.services.metric_catalog import MetricCatalog


def test_metric_catalog_returns_known_metric() -> None:
    metric = MetricCatalog().get("runs_scored")

    assert metric.label == "Runs Scored"
    assert "batruns" in metric.formula


def test_metric_catalog_filters_by_query_class() -> None:
    metrics = MetricCatalog().list_for_query_class(QueryClass.strengths_weaknesses)

    assert any(metric.metric_id == "control_percentage" for metric in metrics)
