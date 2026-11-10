"""All Formats explorer, driven end to end against the built multi-format database."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from backend.app.multiformat.service import DeliveryFilter, MultiFormatService, player_options

ROOT = Path(__file__).resolve().parents[2]
DB = ROOT / "data" / "cricket_all.duckdb"
IPL = DeliveryFilter(format="T20 domestic", gender="male", competition="Indian Premier League")

pytestmark = pytest.mark.skipif(not DB.exists(), reason="multi-format database not built")

SCRIPT = f"""
import sys
sys.path.insert(0, {str(ROOT)!r})
from pathlib import Path
from streamlit_multiformat_explorer import render_multiformat_explorer
render_multiformat_explorer(Path({str(DB)!r}))
"""


def _player(role: str, name: str) -> str:
    return next(r["player_id"] for r in player_options(MultiFormatService(DB), role, IPL) if r["name"] == name)


def _ipl_app() -> AppTest:
    app = AppTest.from_string(SCRIPT, default_timeout=120).run()
    assert not app.exception
    app.selectbox(key="mf-format").set_value("T20 domestic").run()
    app.selectbox(key="mf-competition-T20 domestic-male").set_value("Indian Premier League").run()
    assert not app.exception
    return app


def _view(app: AppTest, view: str) -> AppTest:
    app.button_group(key="mf-view").set_value(view).run()
    assert not app.exception
    return app


def test_every_format_is_selectable_with_its_coverage_stated() -> None:
    app = AppTest.from_string(SCRIPT, default_timeout=120).run()
    options = app.selectbox(key="mf-format").options
    assert {"Test", "ODI", "T20I", "T20 domestic", "The Hundred"} <= set(options)
    app = _ipl_app()
    caption = app.caption[0].value
    assert "ball-by-ball Apr 2008" in caption and "line/length on" in caption


def test_player_view_shows_stats_and_line_length_with_limits() -> None:
    app = _ipl_app()
    app.selectbox(key="mf-player").set_value(_player("batting", "V Kohli")).run()
    assert not app.exception
    labels = {metric.label: metric.value for metric in app.metric}
    assert int(labels["Runs"].replace(",", "")) > 8000
    app.button_group(key="mf-player-section").set_value("Line & length").run()
    assert not app.exception
    captions = " ".join(c.value for c in app.caption)
    assert "Length is recorded for" in captions and "Limitation:" in captions


def test_compare_matchup_and_venue_views_render() -> None:
    kohli, rohit, bumrah = _player("batting", "V Kohli"), _player("batting", "RG Sharma"), _player("bowling", "JJ Bumrah")
    app = _view(_ipl_app(), "Compare")
    app.selectbox(key="mf-compare-a").set_value(kohli).run()
    app.selectbox(key="mf-compare-b").set_value(rohit).run()
    assert not app.exception and len(app.dataframe) == 1

    app = _view(_ipl_app(), "Matchups")
    app.selectbox(key="mf-matchup-bat").set_value(kohli).run()
    app.selectbox(key="mf-matchup-bowl").set_value(bumrah).run()
    assert not app.exception
    assert "V Kohli v JJ Bumrah" in app.subheader[0].value

    app = _view(_ipl_app(), "Venue")
    app.selectbox(key="mf-venue").set_value("Wankhede Stadium, Mumbai").run()
    assert not app.exception
    assert {m.label for m in app.metric} >= {"Matches", "Avg 1st innings", "Run rate"}
