from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any

from rcsd_topo_poc.modules.p05_neural_road_generation.models import sha256_file
from rcsd_topo_poc.modules.p05_neural_road_generation.pto_models import PTOCandidateConfig, PTOStrategyReplay
from rcsd_topo_poc.modules.t00_utility_toolbox.common import normalize_runtime_path


_REQUIRED_HANDOFFS = (
    "t01_roads",
    "t05_intersection_match_all",
    "t05_rcsdnode_out",
    "t06_frcsd_road",
    "t06_frcsd_node",
)
_REQUIRED_EXTERNAL = ("prepared_swsd_nodes", "rcsdroad", "rcsdnode")


def read_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def resolved_path(value: str | Path, *, strict: bool = True) -> Path:
    return normalize_runtime_path(str(value)).resolve(strict=strict)


def _windows_path_from_wsl(value: str) -> Path | None:
    parts = PurePosixPath(value).parts
    if os.name != "nt" or len(parts) < 4 or parts[:2] != ("/", "mnt") or len(parts[2]) != 1:
        return None
    return Path(f"{parts[2]}:/", *parts[3:])


def _git_commit_from_metadata(root: Path) -> str | None:
    marker = root / ".git"
    if marker.is_file():
        line = marker.read_text(encoding="utf-8-sig").strip()
        if not line.startswith("gitdir:"):
            return None
        raw_git_dir = line.partition(":")[2].strip()
        git_dir = _windows_path_from_wsl(raw_git_dir) or Path(raw_git_dir)
        if not git_dir.is_absolute():
            git_dir = (root / git_dir).resolve()
    elif marker.is_dir():
        git_dir = marker
    else:
        return None

    head_path = git_dir / "HEAD"
    if not head_path.is_file():
        return None
    head = head_path.read_text(encoding="ascii").strip()
    if len(head) == 40 and all(character in "0123456789abcdefABCDEF" for character in head):
        return head.casefold()
    return None


def _git_commit(root: Path) -> str:
    metadata_commit = _git_commit_from_metadata(root)
    if metadata_commit is not None:
        return metadata_commit
    command = ["git", "-C", str(root), "rev-parse", "HEAD"]
    try:
        result = subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError):
        if os.name != "nt" or not root.drive:
            raise
        drive = root.drive.rstrip(":").casefold()
        tail = root.as_posix()[2:].lstrip("/")
        wsl_root = f"/mnt/{drive}/{tail}"
        result = subprocess.run(
            ["wsl.exe", "--", "git", "-C", wsl_root, "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    return result.stdout.strip()


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _business_id(case_id: str) -> str:
    value = case_id.strip()
    return value.removeprefix("segment_")


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "size_bytes": path.stat().st_size,
    }


def _validate_replay_header(replay: PTOStrategyReplay, *, verify_git_commit: bool) -> tuple[Path, dict[str, Any]]:
    code_root = resolved_path(replay.code_root)
    run_root = resolved_path(replay.run_root)
    if verify_git_commit:
        actual = _git_commit(code_root)
        if actual != replay.code_commit:
            raise ValueError(f"strategy commit mismatch for {replay.family}: {actual} != {replay.code_commit}")
    manifest_path = run_root / "t10_e2e_run_manifest.json"
    manifest = read_json(manifest_path)
    if manifest.get("status") != "passed":
        raise ValueError(f"strategy replay did not pass: {manifest_path}")
    if manifest.get("silent_fix") is True:
        raise ValueError(f"strategy replay declares silent_fix=true: {manifest_path}")
    return run_root, manifest


def load_strategy_replay_cases(config: PTOCandidateConfig) -> list[dict[str, Any]]:
    allowed_root = resolved_path(config.allowed_data_root)
    excluded = set(config.excluded_business_ids)
    cases: list[dict[str, Any]] = []
    seen_scope: set[tuple[str, str]] = set()
    for replay in config.strategy_replays:
        run_root, run_manifest = _validate_replay_header(replay, verify_git_commit=config.verify_git_commit)
        raw_cases = list(run_manifest.get("cases") or [])
        actual_business_ids = {_business_id(str(row.get("case_id") or "")) for row in raw_cases}
        if replay.expected_case_ids and actual_business_ids != set(replay.expected_case_ids):
            raise ValueError(
                f"strategy replay case set mismatch for {replay.family}: "
                f"missing={sorted(set(replay.expected_case_ids) - actual_business_ids)}, "
                f"extra={sorted(actual_business_ids - set(replay.expected_case_ids))}"
            )
        for row in raw_cases:
            business_id = _business_id(str(row.get("case_id") or ""))
            if not business_id:
                raise ValueError(f"strategy replay case has no business id: {row}")
            if business_id in excluded:
                raise ValueError(f"approved exclusion appears in strategy replay: {replay.family}/{business_id}")
            scope = (replay.family, business_id)
            if scope in seen_scope:
                raise ValueError(f"duplicate strategy replay scope: {scope}")
            seen_scope.add(scope)
            if row.get("overall_status") != "passed":
                raise ValueError(f"strategy replay case did not pass: {scope}")
            statuses = dict(row.get("stage_statuses") or {})
            if statuses.get("t06_step3") != "passed":
                raise ValueError(f"strategy replay case has no passed t06_step3: {scope}")

            case_manifest_path = resolved_path(str(row.get("case_run_manifest_path") or ""))
            case_manifest = read_json(case_manifest_path)
            case_dir = resolved_path(str(case_manifest.get("case_dir") or case_manifest.get("package_root") or ""))
            if case_dir.name != business_id:
                raise ValueError(f"strategy replay case_dir/business id mismatch: {case_dir} != {business_id}")
            wrapper_outside_allowed_root = not _is_within(case_dir, allowed_root)
            handoffs = dict(case_manifest.get("handoffs") or {})
            external = dict(case_manifest.get("external_inputs") or {})
            missing_handoffs = sorted(set(_REQUIRED_HANDOFFS) - set(handoffs))
            missing_external = sorted(set(_REQUIRED_EXTERNAL) - set(external))
            if missing_handoffs or missing_external:
                raise ValueError(
                    f"incomplete strategy replay lineage for {scope}: "
                    f"handoffs={missing_handoffs}, external={missing_external}"
                )
            artifact_paths = {
                role: resolved_path(path)
                for role, path in {
                    **{key: handoffs[key] for key in _REQUIRED_HANDOFFS},
                    **external,
                }.items()
            }
            case_evidence_manifest = (case_dir / "t10_case_evidence_manifest.json").resolve(strict=True)
            artifact_paths["case_evidence_manifest"] = case_evidence_manifest
            outside_external = [
                role
                for role in external
                if not _is_within(artifact_paths[role], allowed_root)
            ]
            if outside_external:
                raise ValueError(f"external input is outside allowed_data_root for {scope}: {outside_external}")
            truth_tokens = ("truth", "oracle", "label")
            suspicious = [role for role, path in artifact_paths.items() if any(token in str(path).casefold() for token in truth_tokens)]
            if suspicious:
                raise ValueError(f"truth-like path appears in candidate lineage for {scope}: {suspicious}")
            artifact_records = {role: _artifact(path) for role, path in artifact_paths.items()}
            stage_seconds = sum(float(item.get("duration_seconds") or 0.0) for item in list(case_manifest.get("stage_records") or []))
            cases.append(
                {
                    "sample_id": f"{replay.family.casefold().replace('-', '_')}:{business_id}",
                    "family": replay.family,
                    "business_id": business_id,
                    "code_commit": replay.code_commit,
                    "code_root": str(resolved_path(replay.code_root)),
                    "replay_run_root": str(run_root),
                    "aggregate_manifest": _artifact(run_root / "t10_e2e_run_manifest.json"),
                    "case_manifest": _artifact(case_manifest_path),
                    "case_dir": str(case_dir),
                    "case_wrapper_outside_allowed_root": wrapper_outside_allowed_root,
                    "all_external_inputs_within_allowed_root": True,
                    "artifacts": artifact_records,
                    "replay_duration_seconds": stage_seconds,
                    "silent_fix": False,
                }
            )
    cases.sort(key=lambda item: (str(item["family"]), str(item["business_id"])))
    if len(cases) != config.expected_case_count:
        raise ValueError(f"PTO candidate run requires {config.expected_case_count} cases, got {len(cases)}")
    return cases


__all__ = ["load_strategy_replay_cases", "read_json", "resolved_path"]
