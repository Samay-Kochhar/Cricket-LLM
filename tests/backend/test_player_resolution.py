from backend.app.services.player_resolution import resolve_player_name


def test_resolve_player_alias_maps_to_dataset_name() -> None:
    result = resolve_player_name("Steve Smith", ["Steven Smith", "Virat Kohli"])

    assert result.canonical_name == "Steven Smith"
    assert result.suggestions == ()


def test_resolve_unknown_player_returns_suggestions() -> None:
    result = resolve_player_name("Virat Kholi", ["Virat Kohli", "Hardik Pandya"])

    assert result.canonical_name is None
    assert "Virat Kohli" in result.suggestions
