from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from rcsd_topo_poc.modules.t04_divmerge_virtual_polygon import provenance


def test_current_git_sha_is_cached_per_repo_root(monkeypatch, tmp_path: Path) -> None:
    calls: list[Path] = []

    def fake_run(*_args, cwd: Path, **_kwargs):
        calls.append(cwd)
        return SimpleNamespace(stdout="123456789abc\n")

    provenance.current_git_sha.cache_clear()
    monkeypatch.setattr(provenance.subprocess, "run", fake_run)

    assert provenance.current_git_sha(repo_root=tmp_path) == "123456789abc"
    assert provenance.current_git_sha(repo_root=tmp_path) == "123456789abc"
    assert calls == [tmp_path]
    provenance.current_git_sha.cache_clear()
