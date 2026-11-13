import gzip
import hashlib
import json

import duckdb
import pytest

from scripts.bootstrap_data import DataBootstrapError
from scripts.bootstrap_multiformat import ensure_multiformat_database


def download_fixture(tmp_path):
    original = tmp_path / "source.duckdb"
    with duckdb.connect(str(original)) as connection:
        connection.execute("CREATE SCHEMA analytics")
        connection.execute("CREATE TABLE analytics.coverage_summary AS SELECT 'Test' AS format, 'female' AS gender")
        connection.execute("CREATE TABLE analytics.deliveries AS SELECT 'example' AS match_id")
    archive = tmp_path / "records.gz"
    archive.write_bytes(gzip.compress(original.read_bytes()))
    manifest = tmp_path / "download.json"
    manifest.write_text(json.dumps({
        "url": archive.as_uri(),
        "sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "database_bytes": original.stat().st_size,
    }))
    return manifest, tmp_path / "website" / "cricket_all.duckdb"


def test_first_start_downloads_checked_records_and_repeat_start_reuses_them(tmp_path):
    manifest, target = download_fixture(tmp_path)
    assert ensure_multiformat_database(target, manifest) == target
    with duckdb.connect(str(target), read_only=True) as connection:
        assert connection.execute("SELECT format, gender FROM analytics.coverage_summary").fetchall() == [("Test", "female")]
    manifest.unlink()  # Page changes must work even if the download is unavailable.
    assert ensure_multiformat_database(target, manifest) == target
    assert list(target.parent.iterdir()) == [target]


@pytest.mark.parametrize("field,value,message", [
    ("sha256", "0" * 64, "incomplete or changed"),
    ("database_bytes", 1, "unexpected size"),
])
def test_bad_download_never_leaves_a_partial_database(tmp_path, field, value, message):
    manifest, target = download_fixture(tmp_path)
    metadata = json.loads(manifest.read_text())
    metadata[field] = value
    manifest.write_text(json.dumps(metadata))
    with pytest.raises(DataBootstrapError, match=message):
        ensure_multiformat_database(target, manifest)
    assert not target.exists()
    assert not list(target.parent.iterdir())


def test_existing_database_is_never_modified(tmp_path):
    target = tmp_path / "existing.duckdb"
    target.write_bytes(b"existing records must remain untouched")
    assert ensure_multiformat_database(target, tmp_path / "absent.json") == target
    assert target.read_bytes() == b"existing records must remain untouched"
