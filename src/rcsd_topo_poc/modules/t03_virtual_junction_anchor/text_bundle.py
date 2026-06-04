from __future__ import annotations

import argparse
import hashlib
import json
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from rcsd_topo_poc.modules.t02_junction_anchor.text_bundle import (
    TEXT_BUNDLE_VERSION,
    TextBundleError,
    _build_bundle_text,
    _normalize_mainnodeids,
    _parse_text_bundle,
    run_t02_decode_text_bundle,
    run_t02_export_text_bundle,
)


DEFAULT_MAX_TEXT_SIZE_BYTES = 250 * 1024
UNSPLIT_BUILD_LIMIT_BYTES = 2_147_483_647
SUPPORTED_MODULE_NAMES = frozenset({"t03", "t04"})


@dataclass(frozen=True)
class T03T04TextBundleExportArtifacts:
    success: bool
    bundle_txt_path: Path
    size_report_path: Path | None
    bundle_size_bytes: int
    module_name: str
    requested_mainnodeids: tuple[str, ...] = ()
    successful_mainnodeids: tuple[str, ...] = ()
    failed_mainnodeids: tuple[str, ...] = ()
    case_failures: tuple[dict[str, str], ...] = ()
    part_txt_paths: tuple[Path, ...] = ()
    max_part_size_bytes: int = 0
    failure_reason: str | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class T03T04TextBundleDecodeArtifacts:
    success: bool
    out_dir: Path
    manifest_path: Path
    module_name: str
    case_dirs: tuple[Path, ...] = ()
    split_bundle: dict[str, Any] | None = None


def _resolve_module_name(module_name: str | None) -> str:
    resolved = str(module_name or "t03").strip().lower()
    if resolved not in SUPPORTED_MODULE_NAMES:
        raise ValueError(f"unsupported text bundle module_name: {module_name!r}")
    return resolved


def _part_txt_paths(out_txt: Path, part_count: int) -> tuple[Path, ...]:
    if part_count <= 1:
        return (out_txt,)
    suffix = out_txt.suffix or ".txt"
    return tuple(
        out_txt if index == 1 else out_txt.with_name(f"{out_txt.stem}.part_{index:04d}_of_{part_count:04d}{suffix}")
        for index in range(1, part_count + 1)
    )


def _remove_existing_bundle_outputs(out_txt: Path) -> None:
    if out_txt.exists():
        out_txt.unlink()
    suffix = out_txt.suffix or ".txt"
    for path in out_txt.parent.glob(f"{out_txt.stem}.part_*_of_*{suffix}"):
        if path != out_txt and path.is_file():
            path.unlink()


def _split_payload_bundle_texts(
    *,
    out_txt: Path,
    meta: dict[str, Any],
    payload_bytes: bytes,
    max_text_size_bytes: int,
) -> tuple[tuple[Path, str, int], ...]:
    if max_text_size_bytes <= 0:
        raise TextBundleError("invalid_max_text_size", "max_text_size_bytes must be > 0.")

    full_payload_sha256 = hashlib.sha256(payload_bytes).hexdigest()

    def build_parts(chunk_size: int) -> tuple[tuple[Path, str, int], ...]:
        chunks = [payload_bytes[index : index + chunk_size] for index in range(0, len(payload_bytes), chunk_size)]
        part_paths = _part_txt_paths(out_txt, len(chunks))
        part_filenames = [path.name for path in part_paths]
        parts: list[tuple[Path, str, int]] = []
        for index, chunk in enumerate(chunks, start=1):
            part_meta = {
                **meta,
                "split_bundle": {
                    "enabled": True,
                    "bundle_id": full_payload_sha256,
                    "part_index": index,
                    "part_count": len(chunks),
                    "part_filenames": part_filenames,
                    "full_payload_sha256": full_payload_sha256,
                },
            }
            text, size = _build_bundle_text(meta=part_meta, payload_bytes=chunk)
            parts.append((part_paths[index - 1], text, size))
        return tuple(parts)

    low, high = 1, max(1, len(payload_bytes))
    best: tuple[tuple[Path, str, int], ...] | None = None
    while low <= high:
        mid = (low + high) // 2
        parts = build_parts(mid)
        if max(size for _path, _text, size in parts) <= max_text_size_bytes:
            best = parts
            low = mid + 1
        else:
            high = mid - 1
    if best is None:
        raise TextBundleError(
            "bundle_part_too_large",
            f"Bundle part metadata cannot fit limit {max_text_size_bytes}.",
        )
    return best


def _write_split_bundle(
    *,
    out_txt_path: Path,
    bundle_text: str,
    size_report: dict[str, Any],
    max_text_size_bytes: int,
) -> tuple[tuple[Path, ...], int, dict[str, Any]]:
    meta, payload_bytes, _checksum = _parse_text_bundle(bundle_text)
    parts = _split_payload_bundle_texts(
        out_txt=out_txt_path,
        meta=meta,
        payload_bytes=payload_bytes,
        max_text_size_bytes=max_text_size_bytes,
    )
    for path, text, _size in parts:
        path.write_text(text, encoding="utf-8")
    split_report = {
        "enabled": True,
        "part_count": len(parts),
        "part_files": [str(path) for path, _text, _size in parts],
        "part_size_bytes": {path.name: size for path, _text, size in parts},
        "max_part_size_bytes": max(size for _path, _text, size in parts),
    }
    size_report = dict(size_report)
    size_report["split_bundle"] = split_report
    return tuple(path for path, _text, _size in parts), int(split_report["max_part_size_bytes"]), size_report


def _payload_from_text_bundle_file(bundle_txt: Path) -> tuple[bytes, dict[str, Any] | None]:
    meta, payload_bytes, _checksum = _parse_text_bundle(bundle_txt.read_text(encoding="utf-8"))
    split_meta = meta.get("split_bundle") or {}
    if not split_meta.get("enabled"):
        return payload_bytes, None

    part_count = int(split_meta.get("part_count") or 0)
    part_filenames = [str(name) for name in split_meta.get("part_filenames") or ()]
    full_payload_sha256 = str(split_meta.get("full_payload_sha256") or split_meta.get("bundle_id") or "")
    if part_count <= 0 or len(part_filenames) != part_count or not full_payload_sha256:
        raise TextBundleError("invalid_split_bundle", "Split bundle metadata is incomplete.")

    chunks: dict[int, bytes] = {}
    for filename in part_filenames:
        part_path = bundle_txt.parent / filename
        if not part_path.is_file():
            raise TextBundleError("bundle_part_missing", f"Split bundle part missing: {part_path}")
        part_meta, part_payload, _part_checksum = _parse_text_bundle(part_path.read_text(encoding="utf-8"))
        part_split = part_meta.get("split_bundle") or {}
        if str(part_split.get("full_payload_sha256") or part_split.get("bundle_id") or "") != full_payload_sha256:
            raise TextBundleError("split_bundle_mismatch", f"Split bundle id mismatch: {part_path}")
        if int(part_split.get("part_count") or 0) != part_count:
            raise TextBundleError("split_bundle_mismatch", f"Split bundle part count mismatch: {part_path}")
        part_index = int(part_split.get("part_index") or 0)
        if part_index < 1 or part_index > part_count or part_index in chunks:
            raise TextBundleError("invalid_split_bundle", f"Invalid split bundle part index: {part_path}")
        chunks[part_index] = part_payload

    if len(chunks) != part_count:
        raise TextBundleError("bundle_part_missing", "Split bundle parts are incomplete.")
    full_payload = b"".join(chunks[index] for index in range(1, part_count + 1))
    if hashlib.sha256(full_payload).hexdigest() != full_payload_sha256:
        raise TextBundleError("checksum_mismatch", "Split bundle full payload checksum validation failed.")
    split_report = {
        "enabled": True,
        "part_count": part_count,
        "part_files": [str(bundle_txt.parent / filename) for filename in part_filenames],
        "part_size_bytes": {filename: (bundle_txt.parent / filename).stat().st_size for filename in part_filenames},
        "max_part_size_bytes": max((bundle_txt.parent / filename).stat().st_size for filename in part_filenames),
    }
    return full_payload, split_report


def _write_size_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")


def run_t03_export_text_bundle(
    *,
    nodes_path,
    roads_path,
    drivezone_path,
    divstripzone_path,
    rcsdroad_path,
    rcsdnode_path,
    mainnodeid,
    out_txt,
    module_name: str = "t03",
    nodes_layer: str | None = None,
    roads_layer: str | None = None,
    drivezone_layer: str | None = None,
    divstripzone_layer: str | None = None,
    rcsdroad_layer: str | None = None,
    rcsdnode_layer: str | None = None,
    nodes_crs: str | None = None,
    roads_crs: str | None = None,
    drivezone_crs: str | None = None,
    divstripzone_crs: str | None = None,
    rcsdroad_crs: str | None = None,
    rcsdnode_crs: str | None = None,
    buffer_m: float = 100.0,
    patch_size_m: float = 200.0,
    resolution_m: float = 0.2,
    max_text_size_bytes: int = DEFAULT_MAX_TEXT_SIZE_BYTES,
    allow_partial_cases: bool = False,
) -> T03T04TextBundleExportArtifacts:
    resolved_module = _resolve_module_name(module_name)
    out_txt_path = Path(out_txt)
    size_report_path = out_txt_path.with_suffix(out_txt_path.suffix + ".size_report.json")
    requested_mainnodeids = tuple(_normalize_mainnodeids(mainnodeid))
    try:
        out_txt_path.parent.mkdir(parents=True, exist_ok=True)
        _remove_existing_bundle_outputs(out_txt_path)
        if size_report_path.exists():
            size_report_path.unlink()
        with tempfile.TemporaryDirectory() as temp_dir_text:
            temp_bundle_path = Path(temp_dir_text) / out_txt_path.name
            base_artifacts = run_t02_export_text_bundle(
                nodes_path=nodes_path,
                roads_path=roads_path,
                drivezone_path=drivezone_path,
                divstripzone_path=divstripzone_path,
                rcsdroad_path=rcsdroad_path,
                rcsdnode_path=rcsdnode_path,
                mainnodeid=mainnodeid,
                out_txt=temp_bundle_path,
                nodes_layer=nodes_layer,
                roads_layer=roads_layer,
                drivezone_layer=drivezone_layer,
                divstripzone_layer=divstripzone_layer,
                rcsdroad_layer=rcsdroad_layer,
                rcsdnode_layer=rcsdnode_layer,
                nodes_crs=nodes_crs,
                roads_crs=roads_crs,
                drivezone_crs=drivezone_crs,
                divstripzone_crs=divstripzone_crs,
                rcsdroad_crs=rcsdroad_crs,
                rcsdnode_crs=rcsdnode_crs,
                buffer_m=buffer_m,
                patch_size_m=patch_size_m,
                resolution_m=resolution_m,
                max_text_size_bytes=UNSPLIT_BUILD_LIMIT_BYTES,
                allow_partial_cases=allow_partial_cases,
            )
            if not base_artifacts.success:
                return T03T04TextBundleExportArtifacts(
                    success=False,
                    bundle_txt_path=out_txt_path,
                    size_report_path=base_artifacts.size_report_path,
                    bundle_size_bytes=base_artifacts.bundle_size_bytes,
                    module_name=resolved_module,
                    requested_mainnodeids=requested_mainnodeids,
                    successful_mainnodeids=base_artifacts.successful_mainnodeids,
                    failed_mainnodeids=base_artifacts.failed_mainnodeids,
                    case_failures=base_artifacts.case_failures,
                    failure_reason=base_artifacts.failure_reason,
                    failure_detail=base_artifacts.failure_detail,
                )

            bundle_text = temp_bundle_path.read_text(encoding="utf-8")
            bundle_size_bytes = len(bundle_text.encode("utf-8"))
            base_size_report = (
                json.loads(base_artifacts.size_report_path.read_text(encoding="utf-8"))
                if base_artifacts.size_report_path is not None and base_artifacts.size_report_path.is_file()
                else {}
            )
            size_report = {
                **base_size_report,
                "module_name": resolved_module,
                "t03_t04_common_bundle": True,
                "source_bundle_format": "t02_text_bundle_case_package",
                "max_text_size_bytes": int(max_text_size_bytes),
                "bundle_size_bytes": bundle_size_bytes,
                "within_limit": bundle_size_bytes <= max_text_size_bytes,
            }

            if bundle_size_bytes <= max_text_size_bytes:
                out_txt_path.write_text(bundle_text, encoding="utf-8")
                _write_size_report(size_report_path, size_report)
                return T03T04TextBundleExportArtifacts(
                    success=True,
                    bundle_txt_path=out_txt_path,
                    size_report_path=size_report_path,
                    bundle_size_bytes=bundle_size_bytes,
                    module_name=resolved_module,
                    requested_mainnodeids=requested_mainnodeids,
                    successful_mainnodeids=base_artifacts.successful_mainnodeids,
                    failed_mainnodeids=base_artifacts.failed_mainnodeids,
                    case_failures=base_artifacts.case_failures,
                    max_part_size_bytes=bundle_size_bytes,
                )

            part_paths, max_part_size_bytes, split_size_report = _write_split_bundle(
                out_txt_path=out_txt_path,
                bundle_text=bundle_text,
                size_report=size_report,
                max_text_size_bytes=max_text_size_bytes,
            )
            _write_size_report(size_report_path, split_size_report)
            return T03T04TextBundleExportArtifacts(
                success=True,
                bundle_txt_path=out_txt_path,
                size_report_path=size_report_path,
                bundle_size_bytes=bundle_size_bytes,
                module_name=resolved_module,
                requested_mainnodeids=requested_mainnodeids,
                successful_mainnodeids=base_artifacts.successful_mainnodeids,
                failed_mainnodeids=base_artifacts.failed_mainnodeids,
                case_failures=base_artifacts.case_failures,
                part_txt_paths=part_paths,
                max_part_size_bytes=max_part_size_bytes,
            )
    except Exception as exc:
        reason = getattr(exc, "reason", "bundle_export_failed")
        detail = getattr(exc, "detail", str(exc))
        return T03T04TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            module_name=resolved_module,
            requested_mainnodeids=requested_mainnodeids,
            failure_reason=reason,
            failure_detail=detail,
        )


def run_t04_export_text_bundle(**kwargs) -> T03T04TextBundleExportArtifacts:
    return run_t03_export_text_bundle(module_name="t04", **kwargs)


def run_t03_decode_text_bundle(
    *,
    bundle_txt,
    out_dir=None,
    module_name: str = "t03",
) -> T03T04TextBundleDecodeArtifacts:
    resolved_module = _resolve_module_name(module_name)
    bundle_path = Path(bundle_txt)
    if not bundle_path.is_file():
        raise TextBundleError("bundle_not_found", f"Bundle text file does not exist: {bundle_path}")
    payload_bytes, split_report = _payload_from_text_bundle_file(bundle_path)
    if split_report is None:
        artifacts = run_t02_decode_text_bundle(bundle_txt=bundle_path, out_dir=out_dir)
    else:
        meta = {
            "bundle_version": TEXT_BUNDLE_VERSION,
            "bundle_mode": "split_reassembled",
            "archive_format": "zip",
            "encoding": "base85",
            "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
        }
        full_text, _size = _build_bundle_text(meta=meta, payload_bytes=payload_bytes)
        with tempfile.TemporaryDirectory() as temp_dir_text:
            temp_bundle_path = Path(temp_dir_text) / bundle_path.name
            temp_bundle_path.write_text(full_text, encoding="utf-8")
            artifacts = run_t02_decode_text_bundle(bundle_txt=temp_bundle_path, out_dir=out_dir)
    return T03T04TextBundleDecodeArtifacts(
        success=artifacts.success,
        out_dir=artifacts.out_dir,
        manifest_path=artifacts.manifest_path,
        module_name=resolved_module,
        case_dirs=artifacts.case_dirs,
        split_bundle=split_report,
    )


def run_t04_decode_text_bundle(**kwargs) -> T03T04TextBundleDecodeArtifacts:
    return run_t03_decode_text_bundle(module_name="t04", **kwargs)


def _print_export_result(artifacts: T03T04TextBundleExportArtifacts) -> None:
    label = artifacts.module_name.upper()
    print(f"{label} text bundle written to: {artifacts.bundle_txt_path}")
    print(f"bundle_size_bytes={artifacts.bundle_size_bytes}")
    if artifacts.size_report_path is not None:
        print(f"size_report_path={artifacts.size_report_path}")
    if artifacts.part_txt_paths:
        print(f"bundle_part_count={len(artifacts.part_txt_paths)}")
        print(f"max_part_size_bytes={artifacts.max_part_size_bytes}")
        for path in artifacts.part_txt_paths:
            print(f"bundle_part={path}")


def run_t03_export_text_bundle_cli(args: argparse.Namespace) -> int:
    artifacts = run_t03_export_text_bundle(
        nodes_path=args.nodes_path,
        roads_path=args.roads_path,
        drivezone_path=args.drivezone_path,
        divstripzone_path=args.divstripzone_path,
        rcsdroad_path=args.rcsdroad_path,
        rcsdnode_path=args.rcsdnode_path,
        mainnodeid=args.mainnodeid,
        out_txt=args.out_txt,
        module_name=getattr(args, "module_name", "t03"),
        nodes_layer=args.nodes_layer,
        roads_layer=args.roads_layer,
        drivezone_layer=args.drivezone_layer,
        divstripzone_layer=args.divstripzone_layer,
        rcsdroad_layer=args.rcsdroad_layer,
        rcsdnode_layer=args.rcsdnode_layer,
        nodes_crs=args.nodes_crs,
        roads_crs=args.roads_crs,
        drivezone_crs=args.drivezone_crs,
        divstripzone_crs=args.divstripzone_crs,
        rcsdroad_crs=args.rcsdroad_crs,
        rcsdnode_crs=args.rcsdnode_crs,
        buffer_m=args.buffer_m,
        patch_size_m=args.patch_size_m,
        resolution_m=args.resolution_m,
        max_text_size_bytes=args.max_text_size_bytes,
        allow_partial_cases=args.allow_partial_cases,
    )
    if not artifacts.success:
        detail = artifacts.failure_detail or artifacts.failure_reason or "bundle export failed"
        if artifacts.size_report_path is not None:
            detail = f"{detail} (size report: {artifacts.size_report_path})"
        raise ValueError(detail)
    _print_export_result(artifacts)
    return 0


def run_t04_export_text_bundle_cli(args: argparse.Namespace) -> int:
    args.module_name = "t04"
    return run_t03_export_text_bundle_cli(args)


def run_t03_decode_text_bundle_cli(args: argparse.Namespace) -> int:
    artifacts = run_t03_decode_text_bundle(
        bundle_txt=args.bundle_txt,
        out_dir=args.out_dir,
        module_name=getattr(args, "module_name", "t03"),
    )
    print(f"{artifacts.module_name.upper()} text bundle decoded to: {artifacts.out_dir}")
    if artifacts.case_dirs:
        print(f"case_count={len(artifacts.case_dirs)}")
    if artifacts.split_bundle is not None:
        print(f"split_part_count={artifacts.split_bundle.get('part_count')}")
    return 0


def run_t04_decode_text_bundle_cli(args: argparse.Namespace) -> int:
    args.module_name = "t04"
    return run_t03_decode_text_bundle_cli(args)
