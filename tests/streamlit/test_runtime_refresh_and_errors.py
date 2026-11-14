"""Exercise long-running sessions, failed requests, and navigation costs without AI calls."""
from unittest.mock import patch

import pytest
from streamlit.testing.v1 import AppTest

import streamlit_app
from backend.app.services.chat_service import ChatReply


def test_services_refresh_when_multiformat_data_arrives(monkeypatch, tmp_path):
    monkeypatch.setattr(streamlit_app, 'ROOT', tmp_path)
    monkeypatch.setattr(streamlit_app, 'DB_PATH', tmp_path / 'odi.duckdb')
    monkeypatch.delenv('MULTIFORMAT_DUCKDB_PATH', raising=False)
    database = tmp_path / 'data/cricket_all.duckdb'
    database.parent.mkdir()
    streamlit_app.initialize_services.clear()
    with patch('scripts.bootstrap_data.ensure_database'), patch('backend.app.bootstrap.get_services') as factory:
        factory.side_effect = lambda: {'multiformat_available': database.exists()}
        assert not streamlit_app.initialize_services()['multiformat_available']
        database.write_bytes(b'fixture')
        assert streamlit_app.initialize_services()['multiformat_available']
        assert factory.call_count == 2
        assert streamlit_app.initialize_services()['multiformat_available']
        assert factory.call_count == 2, 'Unchanged data must keep the warm service bundle'
    streamlit_app.initialize_services.clear()


@pytest.mark.parametrize('failure', ['exception', 'empty'])
def test_chat_failure_is_visible_and_survives_a_rerun(monkeypatch, failure):
    class Chat:
        def reply(self, question, history):
            if failure == 'exception':
                raise TimeoutError('private transport details')
            return ChatReply(mode='conversation', message='')

    monkeypatch.setattr(streamlit_app, 'apply_cloud_secrets', lambda: None)
    monkeypatch.setattr(streamlit_app, 'initialize_services', lambda *_: {'chat_service': Chat()})
    app = AppTest.from_string('from streamlit_app import render_page\nrender_page()').run()
    app.chat_input[0].set_value('How many IPL runs has Kohli scored?').run()
    assert not app.exception
    messages = app.session_state.messages
    assert len(messages) == 2 and messages[-1]['role'] == 'assistant'
    assert 'try again' in messages[-1]['content'].lower()
    assert 'private transport details' not in messages[-1]['content']
    app.run()
    assert any('try again' in m.value.lower() for m in app.markdown)


def test_matchup_navigation_does_not_initialize_chat(monkeypatch):
    class Repository:
        def list_player_names(self): return ['Virat Kohli', 'Jasprit Bumrah']
        def list_venues(self): return ['The Oval']

    def no_chat(*args):
        raise AssertionError('Opening Matchups must not initialize chat or its model/data indexes')

    monkeypatch.setattr(streamlit_app, 'apply_cloud_secrets', lambda: None)
    monkeypatch.setattr(streamlit_app, 'initialize_services', no_chat)
    monkeypatch.setattr(streamlit_app, 'initialize_player_explorer_services', lambda *_: {'repository': Repository()})
    app = AppTest.from_string('from streamlit_app import render_page\nrender_page()').run()
    app.sidebar.radio[0].set_value('Matchups').run()
    assert not app.exception
    assert not app.error
    assert any(s.label == 'Batter' for s in app.selectbox)
