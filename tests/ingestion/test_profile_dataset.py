from ingestion.app.profile_dataset import CoverageStat, DatasetProfile, render_profile_markdown


def test_render_profile_markdown_contains_core_sections() -> None:
    profile = DatasetProfile(
        total_rows=100,
        min_year=2005,
        max_year=2025,
        distinct_competitions=12,
        distinct_grounds=34,
        distinct_batters=220,
        distinct_bowlers=180,
        coverage=[CoverageStat(field_name="shot", non_null_rows=88, total_rows=100)],
    )

    content = render_profile_markdown(profile)

    assert "# ODI Data Profile" in content
    assert "Total rows: 100" in content
    assert "`shot`" in content
    assert "88.00%" in content
