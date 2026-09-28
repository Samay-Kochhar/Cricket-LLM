from pathlib import Path

from scripts import run_local


def _fake_conda_environment(tmp_path: Path) -> tuple[Path, Path, Path]:
    conda = tmp_path / "bin" / "conda"
    environment_python = (
        tmp_path / "envs" / run_local.CONDA_ENV / "bin" / "python"
    )
    environment_npm = tmp_path / "envs" / run_local.CONDA_ENV / "bin" / "npm"
    conda.parent.mkdir(parents=True)
    environment_python.parent.mkdir(parents=True)
    conda.touch()
    environment_python.touch()
    environment_npm.touch()
    return conda, environment_python, environment_npm


def test_backend_launcher_prefers_named_project_environment(
    monkeypatch, tmp_path: Path
) -> None:
    conda, environment_python, _ = _fake_conda_environment(tmp_path)
    monkeypatch.setattr(run_local.shutil, "which", lambda name: str(conda))
    monkeypatch.setattr(run_local.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(run_local.sys, "executable", "/base/bin/python")

    command = run_local._backend_command()

    assert command[0] == str(environment_python)


def test_backend_launcher_uses_active_python_when_project_environment_is_absent(
    monkeypatch,
) -> None:
    monkeypatch.setattr(run_local.shutil, "which", lambda name: None)
    monkeypatch.setattr(run_local.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(run_local.sys, "executable", "/active/bin/python")

    command = run_local._backend_command()

    assert command[0] == "/active/bin/python"


def test_frontend_launcher_prefers_named_project_environment(
    monkeypatch, tmp_path: Path
) -> None:
    conda, _, environment_npm = _fake_conda_environment(tmp_path)

    def executable(name: str) -> str | None:
        return str(conda) if name == "conda" else "/base/bin/npm"

    monkeypatch.setattr(run_local.shutil, "which", executable)

    command = run_local._frontend_command()

    assert command[0] == str(environment_npm)


def test_frontend_launcher_uses_path_npm_when_project_environment_is_absent(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        run_local.shutil,
        "which",
        lambda name: None if name == "conda" else "/active/bin/npm",
    )

    command = run_local._frontend_command()

    assert command[0] == "/active/bin/npm"
