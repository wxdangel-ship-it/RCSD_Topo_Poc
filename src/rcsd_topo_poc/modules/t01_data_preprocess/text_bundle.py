from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import zipfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Literal, Sequence


T01_TEXT_BUNDLE_VERSION = "1"
T01_TEXT_BUNDLE_TYPE = "t01_data_preprocess_skill_v1_evidence"
T01_TEXT_BUNDLE_BEGIN = "BEGIN_T01_DATA_PREPROCESS_BUNDLE"
T01_TEXT_BUNDLE_PAYLOAD = "payload:"
T01_TEXT_BUNDLE_META = "meta: "
T01_TEXT_BUNDLE_CHECKSUM = "checksum: "
T01_TEXT_BUNDLE_END = "END_T01_DATA_PREPROCESS_BUNDLE"
T01_TEXT_BUNDLE_LINE_WIDTH = 120

T01_CURRENT_TEXT_BUNDLE_NAME = "t01_skill_v1_evidence_bundle.txt"
T01_CURRENT_TEXT_BUNDLE_SIZE_REPORT_NAME = "t01_skill_v1_evidence_bundle_size_report.json"
T01_BASELINE_TEXT_BUNDLE_NAME = "t01_skill_v1_freeze_evidence_bundle.txt"
T01_BASELINE_TEXT_BUNDLE_SIZE_REPORT_NAME = "t01_skill_v1_freeze_evidence_bundle_size_report.json"
T01_INTERNAL_MANIFEST_NAME = "text_bundle_manifest.json"
T01_INTERNAL_SIZE_REPORT_NAME = "text_bundle_size_report.json"

T01_REQUIRED_EVIDENCE_FILES_BY_MODE = {
    "current": (
        "skill_v1_manifest.json",
        "skill_v1_summary.json",
        "validated_pairs_skill_v1.csv",
        "segment_body_membership_skill_v1.csv",
        "trunk_membership_skill_v1.csv",
        "refreshed_nodes_hash.json",
        "refreshed_roads_hash.json",
    ),
    "baseline": (
        "FREEZE_MANIFEST.json",
        "FREEZE_SUMMARY.json",
        "validated_pairs_baseline.csv",
        "segment_body_membership_baseline.csv",
        "trunk_membership_baseline.csv",
        "refreshed_nodes_hash.json",
        "refreshed_roads_hash.json",
    ),
}

T01_OPTIONAL_EVIDENCE_FILES = (
    "FREEZE_COMPARE_RULES.md",
    "segment_summary.json",
    "inner_nodes_summary.json",
    "oneway_segment_summary.json",
    "oneway_segment_build_table.csv",
    "unsegmented_roads.csv",
    "unsegmented_roads_summary.json",
    "distance_gate_scope_check.json",
    "freeze_compare_report.json",
    "freeze_compare_report.md",
    "t01_skill_v1_summary.json",
    "t01_skill_v1_summary.md",
    "t01_skill_v1_progress.json",
    "t01_skill_v1_perf.json",
    "t01_skill_v1_perf.md",
    "t01_skill_v1_perf_markers.jsonl",
)

T01_VECTOR_EVIDENCE_FILES = (
    "nodes.gpkg",
    "roads.gpkg",
    "segment.gpkg",
    "inner_nodes.gpkg",
    "segment_error.gpkg",
    "segment_error_s_grade_conflict.gpkg",
    "segment_error_grade_kind_conflict.gpkg",
    "oneway_segment_roads.gpkg",
    "unsegmented_roads.gpkg",
)


class T01TextBundleError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class T01TextBundleExportArtifacts:
    success: bool
    bundle_txt_path: Path
    size_report_path: Path | None
    bundle_size_bytes: int
    included_file_count: int = 0
    failure_reason: str | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class T01TextBundleDecodeArtifacts:
    success: bool
    out_dir: Path
    manifest_path: Path


def text_bundle_name_for_mode(mode: Literal["current", "baseline"]) -> str:
    return T01_BASELINE_TEXT_BUNDLE_NAME if mode == "baseline" else T01_CURRENT_TEXT_BUNDLE_NAME


def text_bundle_size_report_name_for_mode(mode: Literal["current", "baseline"]) -> str:
    return T01_BASELINE_TEXT_BUNDLE_SIZE_REPORT_NAME if mode == "baseline" else T01_CURRENT_TEXT_BUNDLE_SIZE_REPORT_NAME


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _wrap_payload_text(text: str, *, width: int = T01_TEXT_BUNDLE_LINE_WIDTH) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def _build_bundle_text(*, meta: dict[str, Any], payload_bytes: bytes) -> tuple[str, int]:
    payload_text = base64.b85encode(payload_bytes).decode("ascii")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    lines = [
        T01_TEXT_BUNDLE_BEGIN,
        T01_TEXT_BUNDLE_META + json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        T01_TEXT_BUNDLE_PAYLOAD,
        _wrap_payload_text(payload_text),
        T01_TEXT_BUNDLE_CHECKSUM + checksum,
        T01_TEXT_BUNDLE_END,
        "",
    ]
    text = "\n".join(lines)
    return text, len(text.encode("utf-8"))


def _parse_text_bundle(bundle_text: str) -> tuple[dict[str, Any], bytes]:
    lines = bundle_text.splitlines()
    if not lines or lines[0].strip() != T01_TEXT_BUNDLE_BEGIN:
        raise T01TextBundleError("invalid_bundle_format", "Bundle header not found.")
    try:
        meta_index = next(index for index, line in enumerate(lines) if line.startswith(T01_TEXT_BUNDLE_META))
        payload_index = next(index for index, line in enumerate(lines) if line.strip() == T01_TEXT_BUNDLE_PAYLOAD)
        checksum_index = next(index for index, line in enumerate(lines) if line.startswith(T01_TEXT_BUNDLE_CHECKSUM))
        end_index = next(index for index, line in enumerate(lines) if line.strip() == T01_TEXT_BUNDLE_END)
    except StopIteration as exc:
        raise T01TextBundleError("invalid_bundle_format", "Bundle markers are incomplete.") from exc
    if not (meta_index < payload_index < checksum_index < end_index):
        raise T01TextBundleError("invalid_bundle_format", "Bundle section order is invalid.")

    meta = json.loads(lines[meta_index][len(T01_TEXT_BUNDLE_META) :])
    payload_text = "".join(lines[payload_index + 1 : checksum_index]).strip()
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = lines[checksum_index][len(T01_TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise T01TextBundleError("checksum_mismatch", "Bundle payload checksum validation failed.")
    if str(meta.get("bundle_version")) != T01_TEXT_BUNDLE_VERSION:
        raise T01TextBundleError("bundle_version_mismatch", f"Unsupported bundle version: {meta.get('bundle_version')}")
    if str(meta.get("bundle_type")) != T01_TEXT_BUNDLE_TYPE:
        raise T01TextBundleError("bundle_type_mismatch", f"Unsupported bundle type: {meta.get('bundle_type')}")
    return meta, payload_bytes


def _zip_bytes(files: dict[str, bytes]) -> tuple[bytes, dict[str, int]]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue()), "r") as zf:
        per_file_compressed = {info.filename: int(info.compress_size) for info in zf.infolist()}
    return buffer.getvalue(), per_file_compressed


def _assert_safe_bundle_name(name: str) -> str:
    path = Path(name)
    if path.is_absolute() or ".." in path.parts or not path.parts:
        raise T01TextBundleError("invalid_bundle_path", f"Bundle file path is not safe: {name}")
    return path.as_posix()


def _read_bundle_file(root: Path, relative_name: str) -> bytes:
    safe_name = _assert_safe_bundle_name(relative_name)
    path = root / safe_name
    if not path.is_file():
        raise T01TextBundleError("bundle_input_missing", f"Required bundle input is missing: {path}")
    return path.read_bytes()


def _collect_stage_segment_roads(root: Path) -> dict[str, bytes]:
    stage_root = root / "all_stage_segment_roads"
    if not stage_root.is_dir():
        return {}
    files: dict[str, bytes] = {}
    for path in sorted(stage_root.rglob("*")):
        if not path.is_file():
            continue
        relative_name = _assert_safe_bundle_name(path.relative_to(root).as_posix())
        files[relative_name] = path.read_bytes()
    return files


def _resolve_extra_file(root: Path, value: str | Path) -> tuple[str, bytes]:
    root_resolved = root.resolve()
    path = Path(value)
    source_path = path if path.is_absolute() else root / path
    source_resolved = source_path.resolve()
    try:
        relative_name = source_resolved.relative_to(root_resolved).as_posix()
    except ValueError as exc:
        raise T01TextBundleError(
            "extra_path_outside_root",
            f"Extra path is outside bundle root: {source_path}",
        ) from exc
    if not source_resolved.is_file():
        raise T01TextBundleError("extra_path_not_file", f"Extra path is not a file: {source_path}")
    return _assert_safe_bundle_name(relative_name), source_resolved.read_bytes()


def _collect_bundle_files(
    *,
    root: Path,
    mode: Literal["current", "baseline"],
    include_vectors: bool,
    include_stage_segment_roads: bool,
    extra_relative_paths: Sequence[str | Path],
) -> tuple[dict[str, bytes], list[str]]:
    files: dict[str, bytes] = {}
    skipped_missing: list[str] = []

    for relative_name in T01_REQUIRED_EVIDENCE_FILES_BY_MODE[mode]:
        files[relative_name] = _read_bundle_file(root, relative_name)

    optional_names = list(T01_OPTIONAL_EVIDENCE_FILES)
    if include_vectors:
        optional_names.extend(T01_VECTOR_EVIDENCE_FILES)
    for relative_name in optional_names:
        safe_name = _assert_safe_bundle_name(relative_name)
        path = root / safe_name
        if path.is_file():
            files[safe_name] = path.read_bytes()
        else:
            skipped_missing.append(safe_name)

    if include_stage_segment_roads:
        files.update(_collect_stage_segment_roads(root))
        if "all_stage_segment_roads" not in {part.split("/", 1)[0] for part in files}:
            skipped_missing.append("all_stage_segment_roads/")

    for value in extra_relative_paths:
        relative_name, content = _resolve_extra_file(root, value)
        files[relative_name] = content

    return files, sorted(set(skipped_missing))


def _build_size_report(
    *,
    bundle_size_bytes: int,
    payload_size_bytes: int,
    per_file_raw_size_bytes: dict[str, int],
    per_file_compressed_size_bytes: dict[str, int],
    skipped_missing_files: list[str],
    mode: Literal["current", "baseline"],
    include_vectors: bool,
    include_stage_segment_roads: bool,
) -> dict[str, Any]:
    evidence_file_names = [
        name
        for name in per_file_raw_size_bytes
        if name not in {T01_INTERNAL_MANIFEST_NAME, T01_INTERNAL_SIZE_REPORT_NAME}
    ]
    dominant_size_source = None
    if evidence_file_names:
        dominant_size_source = max(evidence_file_names, key=lambda name: per_file_raw_size_bytes[name])
    return {
        "bundle_version": T01_TEXT_BUNDLE_VERSION,
        "bundle_type": T01_TEXT_BUNDLE_TYPE,
        "mode": mode,
        "total_text_size_bytes": bundle_size_bytes,
        "payload_size_bytes": payload_size_bytes,
        "included_file_count": len(evidence_file_names),
        "include_vectors": include_vectors,
        "include_stage_segment_roads": include_stage_segment_roads,
        "dominant_size_source": dominant_size_source,
        "per_file_raw_size_bytes": per_file_raw_size_bytes,
        "per_file_compressed_size_bytes": per_file_compressed_size_bytes,
        "skipped_missing_files": skipped_missing_files,
    }


def _build_text_bundle(
    *,
    root: Path,
    mode: Literal["current", "baseline"],
    include_vectors: bool,
    include_stage_segment_roads: bool,
    extra_relative_paths: Sequence[str | Path],
) -> tuple[str, int, dict[str, Any]]:
    files, skipped_missing = _collect_bundle_files(
        root=root,
        mode=mode,
        include_vectors=include_vectors,
        include_stage_segment_roads=include_stage_segment_roads,
        extra_relative_paths=extra_relative_paths,
    )
    evidence_files = dict(files)
    manifest = {
        "bundle_version": T01_TEXT_BUNDLE_VERSION,
        "bundle_type": T01_TEXT_BUNDLE_TYPE,
        "mode": mode,
        "source_root": str(root.resolve()),
        "file_list": sorted(set(files).union({T01_INTERNAL_MANIFEST_NAME, T01_INTERNAL_SIZE_REPORT_NAME})),
        "checksum": {name: hashlib.sha256(content).hexdigest() for name, content in sorted(evidence_files.items())},
        "encoder_info": {
            "archive_format": "zip",
            "compression": "deflate",
            "text_encoding": "base85",
            "line_width": T01_TEXT_BUNDLE_LINE_WIDTH,
            "selection": "t01-skill-v1-compact-evidence",
        },
        "created_at": _now_text(),
    }

    size_report: dict[str, Any] = {}
    bundle_text = ""
    bundle_size_bytes = 0
    for _ in range(4):
        files[T01_INTERNAL_MANIFEST_NAME] = json.dumps(
            manifest,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        files[T01_INTERNAL_SIZE_REPORT_NAME] = json.dumps(
            size_report,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        ).encode("utf-8")
        payload_bytes, per_file_compressed = _zip_bytes(files)
        meta = {
            "bundle_version": T01_TEXT_BUNDLE_VERSION,
            "bundle_type": T01_TEXT_BUNDLE_TYPE,
            "mode": mode,
            "archive_format": "zip",
            "encoding": "base85",
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
            "created_at": _now_text(),
        }
        bundle_text, bundle_size_bytes = _build_bundle_text(meta=meta, payload_bytes=payload_bytes)
        next_report = _build_size_report(
            bundle_size_bytes=bundle_size_bytes,
            payload_size_bytes=len(payload_bytes),
            per_file_raw_size_bytes={name: len(content) for name, content in files.items()},
            per_file_compressed_size_bytes=per_file_compressed,
            skipped_missing_files=skipped_missing,
            mode=mode,
            include_vectors=include_vectors,
            include_stage_segment_roads=include_stage_segment_roads,
        )
        if next_report == size_report:
            break
        size_report = next_report

    return bundle_text, bundle_size_bytes, size_report


def run_t01_export_text_bundle(
    *,
    bundle_root: str | Path,
    out_txt: str | Path | None = None,
    mode: Literal["current", "baseline"] = "current",
    include_vectors: bool = False,
    include_stage_segment_roads: bool = False,
    extra_relative_paths: Sequence[str | Path] = (),
) -> T01TextBundleExportArtifacts:
    root = Path(bundle_root)
    out_txt_path = Path(out_txt) if out_txt is not None else root / text_bundle_name_for_mode(mode)
    size_report_path = out_txt_path.with_name(text_bundle_size_report_name_for_mode(mode))
    try:
        if mode not in T01_REQUIRED_EVIDENCE_FILES_BY_MODE:
            raise T01TextBundleError("invalid_mode", f"Unsupported T01 text bundle mode: {mode}")
        if not root.is_dir():
            raise T01TextBundleError("bundle_root_not_found", f"Bundle root does not exist: {root}")
        out_txt_path.parent.mkdir(parents=True, exist_ok=True)
        bundle_text, bundle_size_bytes, size_report = _build_text_bundle(
            root=root,
            mode=mode,
            include_vectors=include_vectors,
            include_stage_segment_roads=include_stage_segment_roads,
            extra_relative_paths=extra_relative_paths,
        )
        out_txt_path.write_text(bundle_text, encoding="utf-8")
        size_report_path.write_text(
            json.dumps(size_report, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return T01TextBundleExportArtifacts(
            success=True,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path,
            bundle_size_bytes=bundle_size_bytes,
            included_file_count=int(size_report.get("included_file_count") or 0),
        )
    except Exception as exc:
        reason = getattr(exc, "reason", "bundle_export_failed")
        detail = getattr(exc, "detail", str(exc))
        return T01TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            failure_reason=reason,
            failure_detail=detail,
        )


def _extract_and_verify_bundle(bundle_txt: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    _meta, payload_bytes = _parse_text_bundle(bundle_txt.read_text(encoding="utf-8"))
    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as zf:
        names = set(zf.namelist())
        for name in names:
            _assert_safe_bundle_name(name)
        files = {name: zf.read(name) for name in names}
    if T01_INTERNAL_MANIFEST_NAME not in files:
        raise T01TextBundleError("bundle_missing_files", f"Bundle is missing {T01_INTERNAL_MANIFEST_NAME}.")
    manifest = json.loads(files[T01_INTERNAL_MANIFEST_NAME])
    if str(manifest.get("bundle_version")) != T01_TEXT_BUNDLE_VERSION:
        raise T01TextBundleError(
            "bundle_version_mismatch",
            f"Unsupported bundle version: {manifest.get('bundle_version')}",
        )
    if str(manifest.get("bundle_type")) != T01_TEXT_BUNDLE_TYPE:
        raise T01TextBundleError("bundle_type_mismatch", f"Unsupported bundle type: {manifest.get('bundle_type')}")
    for name, expected in dict(manifest.get("checksum") or {}).items():
        if name not in files:
            raise T01TextBundleError("bundle_missing_files", f"Bundle is missing checksummed file: {name}")
        if hashlib.sha256(files[name]).hexdigest() != expected:
            raise T01TextBundleError("checksum_mismatch", f"Checksum mismatch for {name}.")
    return manifest, files


def run_t01_decode_text_bundle(
    *,
    bundle_txt: str | Path,
    out_dir: str | Path | None = None,
) -> T01TextBundleDecodeArtifacts:
    bundle_path = Path(bundle_txt)
    if not bundle_path.is_file():
        raise T01TextBundleError("bundle_not_found", f"Bundle text file does not exist: {bundle_path}")
    out_dir_path = Path(out_dir) if out_dir is not None else bundle_path.with_suffix("")
    out_dir_path.mkdir(parents=True, exist_ok=True)
    manifest, files = _extract_and_verify_bundle(bundle_path)
    for name, content in files.items():
        target_path = out_dir_path / _assert_safe_bundle_name(name)
        target_path.parent.mkdir(parents=True, exist_ok=True)
        target_path.write_bytes(content)
    manifest["decoded_output"] = {
        "decoded_at": _now_text(),
        "out_dir": str(out_dir_path.resolve()),
    }
    manifest_path = out_dir_path / T01_INTERNAL_MANIFEST_NAME
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    return T01TextBundleDecodeArtifacts(success=True, out_dir=out_dir_path, manifest_path=manifest_path)


def _build_export_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t01-export-text-bundle-dev")
    parser.add_argument("--bundle-root", required=True)
    parser.add_argument("--out-txt")
    parser.add_argument("--mode", choices=("current", "baseline"), default="current")
    parser.add_argument("--include-vectors", action="store_true")
    parser.add_argument("--include-stage-segment-roads", action="store_true")
    parser.add_argument("--extra-path", action="append", default=[])
    return parser


def _build_decode_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="t01-decode-text-bundle-dev")
    parser.add_argument("--bundle-txt", required=True)
    parser.add_argument("--out-dir")
    return parser


def run_t01_export_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_export_arg_parser().parse_args(argv)
    artifacts = run_t01_export_text_bundle(
        bundle_root=args.bundle_root,
        out_txt=args.out_txt,
        mode=args.mode,
        include_vectors=args.include_vectors,
        include_stage_segment_roads=args.include_stage_segment_roads,
        extra_relative_paths=tuple(args.extra_path or ()),
    )
    if not artifacts.success:
        print(f"T01 text bundle export failed: {artifacts.failure_detail}", file=sys.stderr)
        if artifacts.size_report_path is not None:
            print(f"size_report={artifacts.size_report_path}", file=sys.stderr)
        return 1
    print(f"T01 text bundle written to: {artifacts.bundle_txt_path}")
    print(f"bundle_size_bytes={artifacts.bundle_size_bytes}")
    print(f"included_file_count={artifacts.included_file_count}")
    if artifacts.size_report_path is not None:
        print(f"size_report={artifacts.size_report_path}")
    return 0


def run_t01_decode_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_decode_arg_parser().parse_args(argv)
    artifacts = run_t01_decode_text_bundle(bundle_txt=args.bundle_txt, out_dir=args.out_dir)
    print(f"T01 text bundle decoded to: {artifacts.out_dir}")
    print(f"manifest={artifacts.manifest_path}")
    return 0
