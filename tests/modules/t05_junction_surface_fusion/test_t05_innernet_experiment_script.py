from __future__ import annotations

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def _load_script_module():
    script_path = Path(__file__).resolve().parents[3] / "scripts" / "t05_innernet_experiment.py"
    spec = importlib.util.spec_from_file_location("t05_innernet_experiment", script_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _args(**overrides):
    defaults = {
        "t07_dir": None,
        "t07_input": None,
        "t07_evidence": None,
        "t02_evidence": None,
        "include_legacy_t02_evidence": False,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def test_t07_mode_disables_automatic_legacy_t02_evidence(tmp_path: Path) -> None:
    module = _load_script_module()
    t02_dir = tmp_path / "t02"
    t02_dir.mkdir()
    (t02_dir / "t02_swsd_rcsd_relation_evidence.csv").write_text("target_id\n1\n", encoding="utf-8")

    resolved = module._resolve_t02_evidence(args=_args(t07_dir="/tmp/t07"), t02_dir=t02_dir, t07_mode=True)

    assert resolved is None


def test_legacy_t02_evidence_can_be_explicitly_included_in_t07_mode(tmp_path: Path) -> None:
    module = _load_script_module()
    t02_dir = tmp_path / "t02"
    t02_dir.mkdir()
    evidence_path = t02_dir / "t02_swsd_rcsd_relation_evidence.csv"
    evidence_path.write_text("target_id\n1\n", encoding="utf-8")

    resolved = module._resolve_t02_evidence(
        args=_args(t07_dir="/tmp/t07", include_legacy_t02_evidence=True),
        t02_dir=t02_dir,
        t07_mode=True,
    )

    assert resolved == evidence_path


def test_explicit_t02_evidence_is_honored_in_t07_mode(tmp_path: Path) -> None:
    module = _load_script_module()
    t02_dir = tmp_path / "t02"
    t02_dir.mkdir()
    evidence_path = tmp_path / "explicit_t02.csv"
    evidence_path.write_text("target_id\n1\n", encoding="utf-8")

    resolved = module._resolve_t02_evidence(
        args=_args(t07_dir="/tmp/t07", t02_evidence=str(evidence_path)),
        t02_dir=t02_dir,
        t07_mode=True,
    )

    assert resolved == evidence_path


def test_t07_evidence_auto_discovery_accepts_json(tmp_path: Path) -> None:
    module = _load_script_module()
    t07_dir = tmp_path / "t07"
    t07_dir.mkdir()
    evidence_path = t07_dir / "t07_swsd_rcsd_relation_evidence.json"
    evidence_path.write_text('{"rows": []}', encoding="utf-8")

    resolved = module._resolve_t07_file(None, t07_dir, module.T07_RELATION_EVIDENCE_FILENAMES)

    assert resolved == evidence_path
