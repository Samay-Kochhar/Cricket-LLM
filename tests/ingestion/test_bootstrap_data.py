from __future__ import annotations

import hashlib
import zipfile
from pathlib import Path

import pytest

from scripts.bootstrap_data import DataBootstrapError, _safe_source_label, ensure_source_csv


def test_downloads_direct_csv_and_verifies_checksum(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("player,runs\nA,10\n", encoding="utf-8")
    destination = tmp_path / "data" / "odi.csv"
    checksum = hashlib.sha256(source.read_bytes()).hexdigest()

    result = ensure_source_csv(source.as_uri(), destination, checksum)

    assert result == destination
    assert destination.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_extracts_named_csv_from_zip_download(tmp_path: Path) -> None:
    archive = tmp_path / "dataset.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        bundle.writestr("release/odi_bbb-25.csv", "player,runs\nA,10\n")
        bundle.writestr("release/readme.txt", "dataset notes")
    destination = tmp_path / "data" / "odi_bbb-25.csv"

    result = ensure_source_csv(
        archive.as_uri(),
        destination,
        archive_member="release/odi_bbb-25.csv",
    )

    assert result == destination
    assert destination.read_text(encoding="utf-8") == "player,runs\nA,10\n"


def test_rejects_download_with_wrong_checksum(tmp_path: Path) -> None:
    source = tmp_path / "source.csv"
    source.write_text("player,runs\nA,10\n", encoding="utf-8")
    destination = tmp_path / "data" / "odi.csv"

    with pytest.raises(DataBootstrapError, match="checksum"):
        ensure_source_csv(source.as_uri(), destination, "0" * 64)

    assert not destination.exists()


def test_existing_csv_does_not_require_a_download_url(tmp_path: Path) -> None:
    destination = tmp_path / "odi.csv"
    destination.write_text("player,runs\nA,10\n", encoding="utf-8")

    result = ensure_source_csv(None, destination)

    assert result == destination


def test_missing_csv_explains_how_to_configure_source(tmp_path: Path) -> None:
    destination = tmp_path / "odi.csv"

    with pytest.raises(DataBootstrapError, match="CRICATLAS_DATA_URL"):
        ensure_source_csv(None, destination)


def test_source_label_removes_secret_query_parameters() -> None:
    label = _safe_source_label("https://data.example/odi.zip?token=do-not-log")

    assert label == "https://data.example/odi.zip"
