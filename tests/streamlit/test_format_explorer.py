"""One explorer for every format: driven through the real app page with AppTest.

Men's ODIs (the default) must render the original approved ODI pages; any other
format must read the multi-format database; features the selected data cannot
support must say so; and there is no separate "All Formats" page any more.
"""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import streamlit_app
from backend.app.multiformat.service import DeliveryFilter, MultiFormatService, player_options

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "cricket_all.duckdb"
IPL = DeliveryFilter(format="T20 domestic", gender="male", competition="Indian Premier League")
IPL_KEY = "T20 domestic|male|Indian Premier League"
TEST_KEY = "Test|male|"
needs_db = pytest.mark.skipif(not DB.exists(), reason="multi-format database not built")


class FakeOdiRepository:
    """Stands in for the ODI AnalyticsRepository; records that the ODI page used it."""

    def list_player_names(self):
        return ["Rohit Sharma", "Virat Kohli"]

    def list_venues(self):
        return ["Melbourne Cricket Ground"]


@pytest.fixture
def app_page(monkeypatch):
    monkeypatch.setattr(streamlit_app, "apply_cloud_secrets", lambda: None)
    repository = FakeOdiRepository()
    services = {"repository": repository, "player_names": tuple(repository.list_player_names())}
    monkeypatch.setattr(streamlit_app, "initialize_player_explorer_services", lambda *_: services)
    monkeypatch.setattr(streamlit_app, "initialize_services", lambda *_: services)

    def open_view(view: str) -> AppTest:
        app = AppTest.from_string("from streamlit_app import render_page\nrender_page()", default_timeout=180).run()
        assert not app.exception
        app.sidebar.radio[0].set_value(view).run()
        assert not app.exception
        return app

    return open_view


def _player(role: str, name: str, flt: DeliveryFilter = IPL) -> str:
    return next(r["player_id"] for r in player_options(MultiFormatService(DB), role, flt) if r["name"] == name)


def _choose_ipl(app: AppTest) -> AppTest:
    app.selectbox(key="explorer-format").set_value("T20 domestic").run()
    app.selectbox(key="explorer-competition-T20 domestic-male").set_value("Indian Premier League").run()
    assert not app.exception
    return app


def _text(app: AppTest) -> str:
    parts = [m.value for m in app.markdown] + [c.value for c in app.caption] + [i.value for i in app.info]
    return "\n".join(parts)


def test_sidebar_has_one_set_of_explorers_and_no_all_formats_page(app_page) -> None:
    app = app_page("Ask Atlas")
    options = app.sidebar.radio[0].options
    assert options == ["Ask Atlas", "Player Explorer", "Compare", "Matchups", "Venue Explorer"]
    assert "All Formats" not in options
    sidebar_text = " ".join(c.value for c in app.sidebar.caption)
    assert "ODI-first" not in sidebar_text and "All formats" in sidebar_text


@pytest.mark.parametrize(
    ("view", "first_page_selectbox", "kicker"),
    [
        ("Player Explorer", "Player", "CricAtlas player explorer"),
        ("Compare", "Player one", "CricAtlas compare explorer"),
        ("Matchups", "Batter", "CricAtlas matchups"),
        ("Venue Explorer", "Venue", "CricAtlas venue explorer"),
    ],
)
def test_odi_is_the_default_and_renders_the_original_odi_page(app_page, view, first_page_selectbox, kicker) -> None:
    app = app_page(view)
    if DB.exists():
        assert app.selectbox(key="explorer-format").value == "ODI"
        assert app.selectbox(key="explorer-gender-ODI").value == "male"
        page_selectboxes = [s for s in app.selectbox if s.key not in {"explorer-format", "explorer-gender-ODI"}]
    else:
        page_selectboxes = [s for s in app.selectbox if s.key != "explorer-format"]
    # The approved ODI page follows, fed by the ODI repository (names, not multi-format IDs).
    assert page_selectboxes[0].label == first_page_selectbox
    if first_page_selectbox != "Venue":
        assert page_selectboxes[0].options == ["Rohit Sharma", "Virat Kohli"]
    else:
        assert page_selectboxes[0].options == ["Melbourne Cricket Ground"]
    assert kicker in _text(app)
    assert not any(key.startswith("mf-") for key in app.session_state.filtered_state)


@needs_db
def test_another_format_reads_the_multiformat_database(app_page) -> None:
    app = _choose_ipl(app_page("Player Explorer"))
    picker = app.selectbox(key=f"mf-player-batting-{IPL_KEY}")
    picker.set_value(_player("batting", "V Kohli")).run()
    assert not app.exception
    labels = {metric.label: metric.value for metric in app.metric}
    assert list(labels) == ["Runs", "Balls", "Average", "Strike rate", "Control", "Dot balls", "Boundaries"]
    assert int(labels["Runs"].replace(",", "")) > 8000
    assert "IPL" in app.selectbox(key="explorer-format").format_func("T20 domestic")
    app.button_group(key="mf-player-section").set_value("Line & length").run()
    assert not app.exception
    captions = " ".join(c.value for c in app.caption)
    assert "Length is recorded for" in captions and "Limitation:" in captions


@needs_db
def test_unsupported_features_show_a_not_available_note(app_page) -> None:
    app = app_page("Player Explorer")
    app.selectbox(key="explorer-format").set_value("Test").run()
    assert app.selectbox(key="mf-player-phase-Test").disabled
    app.selectbox(key=f"mf-player-batting-{TEST_KEY}").set_value(
        _player("batting", "JE Root", DeliveryFilter(format="Test", gender="male"))
    ).run()
    assert not app.exception
    app.button_group(key="mf-player-section").set_value("Wagon wheel & shots").run()
    assert not app.exception
    assert any("wagon wheel is not available for this format" in i.value for i in app.info)
    assert app.get("plotly_chart")  # recorded Test shots are still shown
    app.button_group(key="mf-player-section").set_value("Phase analysis").run()
    assert any("Phase analysis is not available for this format" in i.value for i in app.info)


@needs_db
def test_compare_matchup_and_venue_render_for_another_format(app_page) -> None:
    kohli, rohit, bumrah = _player("batting", "V Kohli"), _player("batting", "RG Sharma"), _player("bowling", "JJ Bumrah")

    app = _choose_ipl(app_page("Compare"))
    app.selectbox(key=f"mf-compare-one-batting-{IPL_KEY}").set_value(kohli).run()
    app.selectbox(key=f"mf-compare-two-batting-{IPL_KEY}").set_value(rohit).run()
    next(b for b in app.button if b.label == "Compare players").click().run()
    assert not app.exception
    assert any(m.value == "## V Kohli vs RG Sharma" for m in app.markdown)
    assert app.dataframe

    app = _choose_ipl(app_page("Matchups"))
    app.selectbox(key=f"mf-matchup-batter-{IPL_KEY}").set_value(kohli).run()
    app.selectbox(key=f"mf-matchup-bowler-{IPL_KEY}").set_value(bumrah).run()
    next(b for b in app.button if b.label == "Show matchup").click().run()
    assert not app.exception
    assert any(m.value == "## V Kohli vs JJ Bumrah" for m in app.markdown)
    assert [m.label for m in app.metric] == [
        "Runs", "Balls", "Dismissals", "Batting Avg", "Batting SR", "Dot Ball %", "Boundary %", "False Shot %",
    ]
    assert "Compared with the batter's normal" in _text(app)

    app = _choose_ipl(app_page("Venue Explorer"))
    app.selectbox(key=f"mf-venue-name-{IPL_KEY}").set_value("M Chinnaswamy Stadium, Bengaluru").run()
    next(b for b in app.button if b.label == "Explore venue").click().run()
    assert not app.exception
    assert any(m.value == "## M Chinnaswamy Stadium, Bengaluru" for m in app.markdown)
    # Both recorded names of the ground are merged, as on the ODI page.
    assert "M Chinnaswamy Stadium, Bangalore" in _text(app)
    assert {m.label for m in app.metric} >= {"Matches", "Avg 1st innings", "Run rate"}
    assert any(m.value == "### Top Wicket Takers" for m in app.markdown)
