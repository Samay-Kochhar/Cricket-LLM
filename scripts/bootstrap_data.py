from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

DEFAULT_DATA_SOURCE_PAGE = "https://himanishganjoo.com/cricket-data/"
DEFAULT_DATA_URL = (
    "https://www.dropbox.com/scl/fi/ld7wj5wtyekke7h9zdtgv/odi_bbb.csv"
    "?rlkey=a9fgdu2qrma6w3w6fpcz3s2f7&dl=1"
)


class DataBootstrapError(RuntimeError):
    """Raised when CricAtlas cannot prepare its local analytical data."""


def _safe_source_label(source_url: str) -> str:
    parsed = urllib.parse.urlsplit(source_url)
    if parsed.scheme in {"http", "https"}:
        return urllib.parse.urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))
    return source_url


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _download(source_url: str, destination: Path) -> None:
    parsed = urllib.parse.urlparse(source_url)
    request: str | urllib.request.Request
    if parsed.scheme in {"http", "https"}:
        request = urllib.request.Request(
            source_url,
            headers={"User-Agent": "CricAtlas-data-bootstrap/1.0"},
        )
    else:
        request = source_url

    try:
        with urllib.request.urlopen(request, timeout=120) as response, destination.open("wb") as target:
            shutil.copyfileobj(response, target, length=1024 * 1024)
    except (OSError, urllib.error.URLError) as exc:
        raise DataBootstrapError(
            f"Could not download CricAtlas data from {_safe_source_label(source_url)}: {exc}"
        ) from exc


def _select_csv_member(archive: zipfile.ZipFile, archive_member: str | None) -> str:
    files = [name for name in archive.namelist() if not name.endswith("/")]
    if archive_member:
        exact_matches = [name for name in files if name == archive_member]
        basename_matches = [name for name in files if Path(name).name == Path(archive_member).name]
        matches = exact_matches or basename_matches
        if len(matches) == 1:
            return matches[0]
        raise DataBootstrapError(
            f"Archive member {archive_member!r} was not found uniquely in the downloaded dataset."
        )

    csv_files = [name for name in files if name.lower().endswith(".csv")]
    if len(csv_files) == 1:
        return csv_files[0]
    raise DataBootstrapError(
        "The downloaded archive contains multiple CSV files. Set "
        "CRICATLAS_DATA_ARCHIVE_MEMBER to the ODI delivery CSV path."
    )


def ensure_source_csv(
    source_url: str | None,
    csv_path: Path,
    expected_sha256: str | None = None,
    archive_member: str | None = None,
    *,
    force: bool = False,
) -> Path:
    """Ensure the source CSV exists, downloading and extracting it atomically when needed."""

    if csv_path.exists() and not force:
        return csv_path
    if not source_url:
        raise DataBootstrapError(
            f"Source CSV is missing at {csv_path}. Set CRICATLAS_DATA_URL to a direct "
            "dataset download URL or place the CSV at that path."
        )

    csv_path.parent.mkdir(parents=True, exist_ok=True)
    download_fd, download_name = tempfile.mkstemp(prefix="cricatlas-download-", dir=csv_path.parent)
    os.close(download_fd)
    downloaded = Path(download_name)
    extracted = downloaded.with_name(f"{downloaded.name}.csv")

    try:
        _download(source_url, downloaded)
        if expected_sha256:
            actual_sha256 = _sha256(downloaded)
            if actual_sha256.lower() != expected_sha256.strip().lower():
                raise DataBootstrapError(
                    "Downloaded dataset checksum did not match CRICATLAS_DATA_SHA256 "
                    f"(expected {expected_sha256}, got {actual_sha256})."
                )

        if zipfile.is_zipfile(downloaded):
            with zipfile.ZipFile(downloaded) as archive:
                member = _select_csv_member(archive, archive_member)
                with archive.open(member) as source, extracted.open("wb") as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)
            os.replace(extracted, csv_path)
        else:
            os.replace(downloaded, csv_path)
    finally:
        downloaded.unlink(missing_ok=True)
        extracted.unlink(missing_ok=True)

    return csv_path


def ensure_database(
    *,
    root: Path,
    csv_path: Path,
    db_path: Path,
    source_url: str | None,
    expected_sha256: str | None = None,
    archive_member: str | None = None,
    force_download: bool = False,
    force_rebuild: bool = False,
    profile_output: Path | None = None,
) -> Path:
    """Prepare the source CSV and build DuckDB only when the database is absent or stale."""

    if db_path.exists() and not force_rebuild:
        if profile_output:
            _write_profile(db_path, profile_output)
        return db_path

    ensure_source_csv(
        source_url or DEFAULT_DATA_URL,
        csv_path,
        expected_sha256,
        archive_member,
        force=force_download,
    )

    from ingestion.app.load_odi_csv import run as load_csv

    db_path.parent.mkdir(parents=True, exist_ok=True)
    database_fd, database_name = tempfile.mkstemp(
        prefix="cricatlas-build-",
        suffix=".duckdb",
        dir=db_path.parent,
    )
    os.close(database_fd)
    temporary_database = Path(database_name)
    temporary_database.unlink()
    try:
        load_csv(
            csv_path,
            temporary_database,
            root / "ingestion" / "sql" / "base_schema.sql",
            root / "ingestion" / "sql" / "derived_views.sql",
        )
        os.replace(temporary_database, db_path)
    finally:
        temporary_database.unlink(missing_ok=True)
        temporary_database.with_suffix(f"{temporary_database.suffix}.wal").unlink(missing_ok=True)

    if profile_output:
        _write_profile(db_path, profile_output)

    return db_path


def _write_profile(db_path: Path, profile_output: Path) -> None:
    import duckdb

    from ingestion.app.profile_dataset import build_profile, render_profile_markdown

    connection = duckdb.connect(str(db_path), read_only=True)
    try:
        profile = build_profile(connection)
    finally:
        connection.close()
    profile_output.parent.mkdir(parents=True, exist_ok=True)
    profile_output.write_text(render_profile_markdown(profile), encoding="utf-8")


def _load_env_file(root: Path) -> None:
    env_path = root / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", maxsplit=1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def main() -> None:
    root = REPO_ROOT
    _load_env_file(root)
    parser = argparse.ArgumentParser(
        description="Download CricAtlas source data when missing and build the analytical DuckDB."
    )
    parser.add_argument("--csv-path", type=Path, default=root / "data" / "odi_bbb-25.csv")
    parser.add_argument("--db-path", type=Path, default=root / "data" / "odi_analytics.duckdb")
    parser.add_argument(
        "--source-url",
        default=os.getenv("CRICATLAS_DATA_URL") or DEFAULT_DATA_URL,
        help=(
            "Direct source CSV/ZIP URL. Defaults to Himanish Ganjoo's published ODI CSV; "
            "CRICATLAS_DATA_URL overrides it."
        ),
    )
    parser.add_argument("--sha256", default=os.getenv("CRICATLAS_DATA_SHA256"))
    parser.add_argument("--archive-member", default=os.getenv("CRICATLAS_DATA_ARCHIVE_MEMBER"))
    parser.add_argument("--force-download", action="store_true")
    parser.add_argument("--force-rebuild", action="store_true")
    parser.add_argument("--profile-output", type=Path)
    args = parser.parse_args()

    database_existed = args.db_path.exists() and not args.force_rebuild
    database = ensure_database(
        root=root,
        csv_path=args.csv_path,
        db_path=args.db_path,
        source_url=args.source_url,
        expected_sha256=args.sha256,
        archive_member=args.archive_member,
        force_download=args.force_download,
        force_rebuild=args.force_rebuild,
        profile_output=args.profile_output,
    )
    action = "Using existing" if database_existed else "Prepared"
    print(f"{action} CricAtlas database at {database}")


if __name__ == "__main__":
    main()
