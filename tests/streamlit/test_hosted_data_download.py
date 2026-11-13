from streamlit.testing.v1 import AppTest

import scripts.bootstrap_multiformat as bootstrap
import streamlit_app


def test_new_host_downloads_before_showing_app_and_reuses_file(monkeypatch, tmp_path):
    target = tmp_path / "cricket_all.duckdb"
    monkeypatch.setenv("MULTIFORMAT_DUCKDB_PATH", str(target))
    monkeypatch.setattr(streamlit_app, "apply_cloud_secrets", lambda: None)
    calls = []

    def download(path):
        calls.append(path)
        path.write_bytes(b"prepared records")

    monkeypatch.setattr(bootstrap, "ensure_multiformat_database", download)
    app = AppTest.from_string("from streamlit_app import render_page\nrender_page()").run()
    assert not app.exception and not app.error
    assert calls == [target]
    assert app.chat_input
    app.run()
    assert calls == [target]


def test_failed_download_explains_problem_instead_of_showing_odi_only(monkeypatch, tmp_path):
    monkeypatch.setenv("MULTIFORMAT_DUCKDB_PATH", str(tmp_path / "absent.duckdb"))
    monkeypatch.setattr(streamlit_app, "apply_cloud_secrets", lambda: None)

    def unavailable(path):
        raise OSError("download unavailable")

    monkeypatch.setattr(bootstrap, "ensure_multiformat_database", unavailable)
    app = AppTest.from_string("from streamlit_app import render_page\nrender_page()").run()
    assert not app.exception
    assert "could not download" in app.error[0].value
    assert not app.chat_input and not app.selectbox
