from __future__ import annotations

import base64
import hashlib
import json
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


T10_TEXT_BUNDLE_BEGIN = "BEGIN_T10_CASE_EVIDENCE_BUNDLE"
T10_TEXT_BUNDLE_META = "meta: "
T10_TEXT_BUNDLE_PAYLOAD = "payload:"
T10_TEXT_BUNDLE_CHECKSUM = "checksum: "
T10_TEXT_BUNDLE_END = "END_T10_CASE_EVIDENCE_BUNDLE"
T10_TEXT_BUNDLE_LINE_WIDTH = 120
T10_TEXT_BUNDLE_LIMIT_BYTES = 250 * 1024


@dataclass(frozen=True)
class T10TextBundleExportArtifacts:
    bundle_txt_path: Path
    part_txt_paths: tuple[Path, ...]
    bundle_size_bytes: int
    max_part_size_bytes: int


@dataclass(frozen=True)
class T10TextBundleDecodeArtifacts:
    out_dir: Path
    manifest_path: Path


class T10TextBundleError(ValueError):
    pass


def export_t10_case_evidence_text_bundle(
    *,
    package_dir: str | Path,
    out_txt: str | Path,
    max_text_size_bytes: int = T10_TEXT_BUNDLE_LIMIT_BYTES,
) -> T10TextBundleExportArtifacts:
    package_root = Path(package_dir).expanduser().resolve()
    if not package_root.is_dir():
        raise T10TextBundleError(f"package_dir is not a directory: {package_root}")
    target = Path(out_txt).expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload_bytes = _zip_directory(package_root)
    meta = {
        "bundle_type": "t10_case_evidence",
        "bundle_version": "1",
        "created_at_utc": _now_text(),
        "package_dir_name": package_root.name,
    }
    parts = _split_payload_bundle_texts(
        out_txt=target,
        meta=meta,
        payload_bytes=payload_bytes,
        max_text_size_bytes=max_text_size_bytes,
    )
    _remove_existing_bundle_outputs(target)
    for path, text, _size in parts:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return T10TextBundleExportArtifacts(
        bundle_txt_path=parts[0][0],
        part_txt_paths=tuple(part[0] for part in parts),
        bundle_size_bytes=sum(part[2] for part in parts),
        max_part_size_bytes=max(part[2] for part in parts),
    )


def decode_t10_case_evidence_text_bundle(*, bundle_txt: str | Path, out_dir: str | Path) -> T10TextBundleDecodeArtifacts:
    first_part = Path(bundle_txt).expanduser().resolve()
    meta, payload_bytes = _parse_bundle_part(first_part)
    split = meta.get("split_bundle") if isinstance(meta, dict) else None
    if isinstance(split, dict) and split.get("enabled"):
        filenames = split.get("part_filenames") or []
        parts = [_parse_bundle_part(first_part.parent / str(filename)) for filename in filenames]
        parts.sort(key=lambda item: int(item[0]["split_bundle"]["part_index"]))
        payload_bytes = b"".join(part_payload for _part_meta, part_payload in parts)
        expected = str(split.get("full_payload_sha256") or "")
        if hashlib.sha256(payload_bytes).hexdigest() != expected:
            raise T10TextBundleError("split bundle checksum mismatch.")

    destination = Path(out_dir).expanduser().resolve()
    destination.mkdir(parents=True, exist_ok=True)
    _extract_zip_safely(payload_bytes, destination)
    manifest_path = destination / "t10_multi_case_evidence_manifest.json"
    if not manifest_path.is_file():
        manifest_path = destination / "t10_multi_segment_evidence_manifest.json"
    if not manifest_path.is_file():
        manifest_path = destination / "t10_case_evidence_manifest.json"
    return T10TextBundleDecodeArtifacts(out_dir=destination, manifest_path=manifest_path)


def _zip_directory(package_root: Path) -> bytes:
    import io

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(item for item in package_root.rglob("*") if item.is_file()):
            archive.write(path, path.relative_to(package_root).as_posix())
    return buffer.getvalue()


def _extract_zip_safely(payload_bytes: bytes, destination: Path) -> None:
    import io

    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as archive:
        for info in archive.infolist():
            name = Path(info.filename)
            if name.is_absolute() or ".." in name.parts:
                raise T10TextBundleError(f"unsafe archive member: {info.filename}")
            archive.extract(info, destination)


def _build_bundle_text(*, meta: dict[str, Any], payload_bytes: bytes) -> tuple[str, int]:
    payload_text = base64.b85encode(payload_bytes).decode("ascii")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    lines = [
        T10_TEXT_BUNDLE_BEGIN,
        T10_TEXT_BUNDLE_META + json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        T10_TEXT_BUNDLE_PAYLOAD,
        _wrap_payload_text(payload_text),
        T10_TEXT_BUNDLE_CHECKSUM + checksum,
        T10_TEXT_BUNDLE_END,
        "",
    ]
    text = "\n".join(lines)
    return text, len(text.encode("utf-8"))


def _split_payload_bundle_texts(
    *,
    out_txt: Path,
    meta: dict[str, Any],
    payload_bytes: bytes,
    max_text_size_bytes: int,
) -> tuple[tuple[Path, str, int], ...]:
    if max_text_size_bytes <= 0:
        raise T10TextBundleError("max_text_size_bytes must be > 0.")
    text, size = _build_bundle_text(meta={**meta, "split_bundle": {"enabled": False}}, payload_bytes=payload_bytes)
    if size <= max_text_size_bytes:
        return ((out_txt, text, size),)

    full_sha = hashlib.sha256(payload_bytes).hexdigest()

    def build_parts(chunk_size: int) -> tuple[tuple[Path, str, int], ...]:
        chunks = [payload_bytes[index : index + chunk_size] for index in range(0, len(payload_bytes), chunk_size)]
        paths = _part_txt_paths(out_txt, len(chunks))
        filenames = [path.name for path in paths]
        parts: list[tuple[Path, str, int]] = []
        for index, chunk in enumerate(chunks, start=1):
            part_meta = {
                **meta,
                "split_bundle": {
                    "enabled": True,
                    "part_index": index,
                    "part_count": len(chunks),
                    "part_filenames": filenames,
                    "full_payload_sha256": full_sha,
                },
            }
            part_text, part_size = _build_bundle_text(meta=part_meta, payload_bytes=chunk)
            parts.append((paths[index - 1], part_text, part_size))
        return tuple(parts)

    low, high = 1, max(1, len(payload_bytes))
    best: tuple[tuple[Path, str, int], ...] | None = None
    while low <= high:
        mid = (low + high) // 2
        parts = build_parts(mid)
        if max(part[2] for part in parts) <= max_text_size_bytes:
            best = parts
            low = mid + 1
        else:
            high = mid - 1
    if best is None:
        raise T10TextBundleError("max_text_size_bytes is too small for bundle metadata.")
    return best


def _parse_bundle_part(path: Path) -> tuple[dict[str, Any], bytes]:
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if not lines or lines[0] != T10_TEXT_BUNDLE_BEGIN or lines[-1] != T10_TEXT_BUNDLE_END:
        raise T10TextBundleError(f"invalid T10 text bundle: {path}")
    meta_line = next((line for line in lines if line.startswith(T10_TEXT_BUNDLE_META)), "")
    checksum_line = next((line for line in lines if line.startswith(T10_TEXT_BUNDLE_CHECKSUM)), "")
    if not meta_line or not checksum_line:
        raise T10TextBundleError(f"missing T10 bundle metadata: {path}")
    payload_start = lines.index(T10_TEXT_BUNDLE_PAYLOAD) + 1
    checksum_index = lines.index(checksum_line)
    payload_text = "".join(lines[payload_start:checksum_index])
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = checksum_line[len(T10_TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise T10TextBundleError(f"payload checksum mismatch: {path}")
    return json.loads(meta_line[len(T10_TEXT_BUNDLE_META) :]), payload_bytes


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
        if path.is_file():
            path.unlink()


def _wrap_payload_text(text: str, *, width: int = T10_TEXT_BUNDLE_LINE_WIDTH) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def _now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
