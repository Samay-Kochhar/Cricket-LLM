from __future__ import annotations

import pytest

from backend.app.config import AppConfig
from backend.app.cricket_analytics.semantic_service import SemanticAnalyticsService
from backend.app.db.repository import AnalyticsRepository


class FakeGeminiClient:
    def is_configured(self) -> bool:
        return False

    def generate_text(self, prompt: str, prefer_complex: bool = False) -> str | None:
        return None


@pytest.fixture(scope="module")
def semantic_service() -> SemanticAnalyticsService:
    return SemanticAnalyticsService(
        repository=AnalyticsRepository(AppConfig.from_env().duckdb_path),
        gemini_client=FakeGeminiClient(),
        app_env="development",
    )


def test_ranking_uses_a_horizontal_bar_with_the_evidence_table_metric(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Who has the highest batting strike rate?")
    table = response.tables[0]
    chart = response.charts[0]

    assert chart.chart_type == "horizontal_bar"
    assert chart.title == "Batting Strike Rate ranking"
    assert chart.series == [
        {"label": str(row[0]), "value": row[1]}
        for row in table.rows
    ]


def test_direct_single_statistic_does_not_render_a_chart(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("What is Virat Kohli's batting strike rate?")

    assert response.status.value == "supported"
    assert len(response.tables[0].rows) == 1
    assert response.charts == []


def test_single_metric_player_comparison_uses_a_grouped_chart_from_the_table(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Compare Virat Kohli and Rohit Sharma by batting strike rate."
    )
    table = response.tables[0]
    chart = response.charts[0]

    assert table.columns[:2] == ["Player", "Batting Strike Rate"]
    assert chart.chart_type == "grouped_bar"
    assert chart.series == [
        {"label": str(row[0]), "value": row[1], "group": "Batting Strike Rate"}
        for row in table.rows
    ]


def test_comparison_groups_multiple_metrics_only_when_their_units_match(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Compare Virat Kohli and Rohit Sharma by dot ball percentage and boundary percentage."
    )
    table = response.tables[0]
    chart = response.charts[0]

    assert table.columns[:3] == [
        "Player",
        "Batter Dot Ball Percentage",
        "Boundary Percentage",
    ]
    assert chart.chart_type == "grouped_bar"
    assert chart.series == [
        {"label": str(row[0]), "value": row[column_index], "group": table.columns[column_index]}
        for row in table.rows
        for column_index in (1, 2)
    ]


def test_comparison_does_not_graph_metrics_with_incompatible_units(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question("Compare Virat Kohli and Rohit Sharma.")

    assert len(response.tables[0].rows) == 2
    assert response.charts == []


def test_phase_comparison_groups_the_same_metric_by_phase(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Compare Bumrah and Starc by economy across powerplay, middle overs, and death overs"
    )
    table = response.tables[0]
    chart = response.charts[0]
    metric_index = table.columns.index("Economy Rate")

    assert chart.chart_type == "grouped_bar"
    assert chart.series == [
        {
            "label": str(row[0]),
            "value": row[metric_index],
            "group": f"{row[1]} — Economy Rate",
        }
        for row in table.rows
    ]


def test_two_sided_split_uses_a_grouped_comparison_chart(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Compare Jasprit Bumrah's economy in the powerplay versus death overs"
    )
    table = response.tables[0]
    chart = response.charts[0]

    assert chart.chart_type == "grouped_bar"
    assert chart.series == [
        {"label": "Powerplay", "value": table.rows[0][1], "group": "Economy Rate"},
        {"label": "Death", "value": table.rows[0][2], "group": "Economy Rate"},
    ]


def test_matchup_pitch_map_requires_sufficient_detailed_coverage(
    semantic_service: SemanticAnalyticsService,
) -> None:
    low_coverage = semantic_service.answer_matchup_page(
        batter="Steven Smith",
        bowler="Rashid Khan",
    )["matchup"]
    sufficient_coverage = semantic_service.answer_matchup_page(
        batter="Shikhar Dhawan",
        bowler="Mitchell Starc",
    )["matchup"]

    assert low_coverage.visuals is None or low_coverage.visuals.pitch_map is None
    assert sufficient_coverage.visuals is not None
    assert sufficient_coverage.visuals.pitch_map is not None
    assert sufficient_coverage.visuals.pitch_map.coverage.covered_balls >= 12
    assert sufficient_coverage.visuals.pitch_map.coverage.coverage_percentage >= 50


def test_line_and_length_matrix_uses_a_heatmap_bound_to_the_evidence_table(
    semantic_service: SemanticAnalyticsService,
) -> None:
    response = semantic_service.answer_question(
        "Show Virat Kohli's batting strike rate by line and length"
    )
    table = response.tables[0]
    chart = response.charts[0]

    assert response.status.value == "supported"
    assert response.interpretation.filters["semantic_group_by"] == ["line", "length"]
    assert table.columns[:3] == ["Line", "Length", "Batting Strike Rate"]
    assert chart.chart_type == "heatmap"
    assert chart.series == [
        {
            "label": f"{row[0]} / {row[1]}",
            "x": str(row[0]),
            "y": str(row[1]),
            "value": row[2],
        }
        for row in table.rows
    ]
