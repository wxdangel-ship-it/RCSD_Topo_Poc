from __future__ import annotations

from pathlib import Path
import sys

from rcsd_topo_poc import cli


def _touch_required_docs(root: Path) -> None:
    for rel in cli.REQUIRED_DOCS:
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("ok\n", encoding="utf-8")


def test_doctor_reports_success(monkeypatch, tmp_path: Path, capsys) -> None:
    _touch_required_docs(tmp_path)
    expected_python = tmp_path / ".venv" / "bin" / "python"
    expected_python.parent.mkdir(parents=True, exist_ok=True)
    expected_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(cli, "EXPECTED_PYTHON_SERIES", sys.version_info[:2])
    monkeypatch.setattr(cli, "_find_repo_root", lambda _start: tmp_path)
    monkeypatch.setattr(cli, "_current_python_matches_repo_venv", lambda _root: (True, str(expected_python)))
    monkeypatch.setattr(cli, "_format_dependency_group", lambda _specs: (True, "deps-ok"))
    monkeypatch.setattr(cli, "_lockfile_status", lambda _root: (True, "lock-ok"))

    exit_code = cli.main(["doctor"])
    captured = capsys.readouterr().out

    assert exit_code == 0
    assert "RepoRoot: OK" in captured
    assert "RepoVenv: OK" in captured
    assert "RuntimeDeps: OK" in captured
    assert "DevDeps: OK" in captured
    assert "Lockfile: OK" in captured


def test_doctor_fails_on_lockfile_audit(monkeypatch, tmp_path: Path, capsys) -> None:
    _touch_required_docs(tmp_path)
    expected_python = tmp_path / ".venv" / "bin" / "python"
    expected_python.parent.mkdir(parents=True, exist_ok=True)
    expected_python.write_text("", encoding="utf-8")

    monkeypatch.setattr(cli, "EXPECTED_PYTHON_SERIES", sys.version_info[:2])
    monkeypatch.setattr(cli, "_find_repo_root", lambda _start: tmp_path)
    monkeypatch.setattr(cli, "_current_python_matches_repo_venv", lambda _root: (True, str(expected_python)))
    monkeypatch.setattr(cli, "_format_dependency_group", lambda _specs: (True, "deps-ok"))
    monkeypatch.setattr(cli, "_lockfile_status", lambda _root: (False, "missing packages: pillow"))

    exit_code = cli.main(["doctor"])
    captured = capsys.readouterr().out

    assert exit_code == 1
    assert "Lockfile: FAIL (missing packages: pillow)" in captured


def test_lockfile_status_reports_missing_expected_package(tmp_path: Path) -> None:
    (tmp_path / "uv.lock").write_text(
        '\n'.join(
            [
                '[[package]]',
                'name = "fiona"',
                '',
                '[[package]]',
                'name = "numpy"',
            ]
        )
        + '\n',
        encoding="utf-8",
    )

    ok, detail = cli._lockfile_status(tmp_path)

    assert ok is False
    assert "pillow" in detail
