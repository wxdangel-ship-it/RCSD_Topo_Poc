from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import sys
import tempfile
import zipfile
from collections import deque
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

import fiona
from shapely.affinity import translate
from shapely.geometry import shape
from shapely.geometry.base import BaseGeometry

from rcsd_topo_poc.modules.p01_arm_build.io import load_dataset, normalise_id
from rcsd_topo_poc.modules.p01_arm_build.models import DATASETS, DatasetInput, LoadedDataset, NodeRecord, RoadRecord
from rcsd_topo_poc.modules.p01_arm_build.topology import build_node_groups, resolve_junction_members, semantic_group_id
from rcsd_topo_poc.modules.t00_utility_toolbox.common import write_vector


P01_TEXT_BUNDLE_VERSION = "1"
P01_TEXT_BUNDLE_LIMIT_BYTES = 250 * 1024
P01_TEXT_BUNDLE_BEGIN = "BEGIN_P01_ARM_BUNDLE"
P01_TEXT_BUNDLE_PAYLOAD = "payload:"
P01_TEXT_BUNDLE_META = "meta: "
P01_TEXT_BUNDLE_CHECKSUM = "checksum: "
P01_TEXT_BUNDLE_END = "END_P01_ARM_BUNDLE"
P01_TEXT_BUNDLE_LINE_WIDTH = 120
P01_BUNDLE_FILES = (
    "manifest.json",
    "size_report.json",
    "SWSD/nodes.gpkg",
    "SWSD/roads.gpkg",
    "RCSD/nodes.gpkg",
    "RCSD/roads.gpkg",
    "FRCSD/nodes.gpkg",
    "FRCSD/roads.gpkg",
)


class P01TextBundleError(ValueError):
    def __init__(self, reason: str, detail: str) -> None:
        super().__init__(detail)
        self.reason = reason
        self.detail = detail


@dataclass(frozen=True)
class P01TextBundleExportArtifacts:
    success: bool
    bundle_txt_path: Path
    size_report_path: Path | None
    bundle_size_bytes: int
    failure_reason: str | None = None
    failure_detail: str | None = None


@dataclass(frozen=True)
class P01TextBundleDecodeArtifacts:
    success: bool
    out_dir: Path
    manifest_path: Path


def _now_text() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _wrap_payload_text(text: str, *, width: int = P01_TEXT_BUNDLE_LINE_WIDTH) -> str:
    return "\n".join(text[index : index + width] for index in range(0, len(text), width))


def _build_bundle_text(*, meta: dict[str, Any], payload_bytes: bytes) -> tuple[str, int]:
    payload_text = base64.b85encode(payload_bytes).decode("ascii")
    checksum = hashlib.sha256(payload_bytes).hexdigest()
    lines = [
        P01_TEXT_BUNDLE_BEGIN,
        P01_TEXT_BUNDLE_META + json.dumps(meta, ensure_ascii=False, separators=(",", ":"), allow_nan=False),
        P01_TEXT_BUNDLE_PAYLOAD,
        _wrap_payload_text(payload_text),
        P01_TEXT_BUNDLE_CHECKSUM + checksum,
        P01_TEXT_BUNDLE_END,
        "",
    ]
    text = "\n".join(lines)
    return text, len(text.encode("utf-8"))


def _zip_bytes(files: dict[str, bytes]) -> tuple[bytes, dict[str, int]]:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as zf:
        for name in sorted(files):
            zf.writestr(name, files[name])
    with zipfile.ZipFile(io.BytesIO(buffer.getvalue()), "r") as zf:
        per_file_compressed = {info.filename: int(info.compress_size) for info in zf.infolist()}
    return buffer.getvalue(), per_file_compressed


def _parse_text_bundle(bundle_text: str) -> tuple[dict[str, Any], bytes]:
    lines = bundle_text.splitlines()
    if not lines or lines[0].strip() != P01_TEXT_BUNDLE_BEGIN:
        raise P01TextBundleError("invalid_bundle_format", "Bundle header not found.")
    try:
        meta_index = next(index for index, line in enumerate(lines) if line.startswith(P01_TEXT_BUNDLE_META))
        payload_index = next(index for index, line in enumerate(lines) if line.strip() == P01_TEXT_BUNDLE_PAYLOAD)
        checksum_index = next(index for index, line in enumerate(lines) if line.startswith(P01_TEXT_BUNDLE_CHECKSUM))
        end_index = next(index for index, line in enumerate(lines) if line.strip() == P01_TEXT_BUNDLE_END)
    except StopIteration as exc:
        raise P01TextBundleError("invalid_bundle_format", "Bundle markers are incomplete.") from exc
    if not (meta_index < payload_index < checksum_index < end_index):
        raise P01TextBundleError("invalid_bundle_format", "Bundle section order is invalid.")

    meta = json.loads(lines[meta_index][len(P01_TEXT_BUNDLE_META) :])
    payload_text = "".join(lines[payload_index + 1 : checksum_index]).strip()
    payload_bytes = base64.b85decode(payload_text.encode("ascii"))
    checksum = lines[checksum_index][len(P01_TEXT_BUNDLE_CHECKSUM) :].strip()
    if hashlib.sha256(payload_bytes).hexdigest() != checksum:
        raise P01TextBundleError("checksum_mismatch", "Bundle payload checksum validation failed.")
    if str(meta.get("bundle_version")) != P01_TEXT_BUNDLE_VERSION:
        raise P01TextBundleError("bundle_version_mismatch", f"Unsupported bundle version: {meta.get('bundle_version')}")
    return meta, payload_bytes


def _parse_junction_group(value: str) -> dict[str, str]:
    parts = [normalise_id(part) for part in value.split(",")]
    if len(parts) != 3 or any(not part for part in parts):
        raise P01TextBundleError("invalid_junction_group", f"Invalid junction group: {value}")
    return {"SWSD": parts[0], "RCSD": parts[1], "FRCSD": parts[2]}


def _dataset_inputs_from_paths(
    *,
    swsd_nodes: str | Path,
    swsd_roads: str | Path,
    rcsd_nodes: str | Path,
    rcsd_roads: str | Path,
    frcsd_nodes: str | Path,
    frcsd_roads: str | Path,
) -> dict[str, DatasetInput]:
    return {
        "SWSD": DatasetInput("SWSD", Path(swsd_nodes), Path(swsd_roads)),
        "RCSD": DatasetInput("RCSD", Path(rcsd_nodes), Path(rcsd_roads)),
        "FRCSD": DatasetInput("FRCSD", Path(frcsd_nodes), Path(frcsd_roads)),
    }


def _crs_text(layer: Any) -> str | None:
    if layer.crs_wkt:
        return str(layer.crs_wkt)
    if layer.crs:
        return str(layer.crs)
    return None


def _road_endpoint_groups(loaded: LoadedDataset, road: RoadRecord) -> tuple[str, str]:
    return semantic_group_id(loaded.nodes.get(road.snodeid), road.snodeid), semantic_group_id(loaded.nodes.get(road.enodeid), road.enodeid)


def _select_bfs_context(
    loaded: LoadedDataset,
    *,
    junction_id: str,
    bfs_depth: int,
) -> tuple[set[str], set[str], dict[str, Any]]:
    resolved_group_id, member_node_ids, input_flags = resolve_junction_members(loaded.nodes, junction_id=junction_id)
    groups, _ = build_node_groups(loaded.nodes)
    adjacency: dict[str, list[tuple[str, str]]] = {}
    road_groups: dict[str, tuple[str, str]] = {}
    for road in loaded.roads.values():
        start_group, end_group = _road_endpoint_groups(loaded, road)
        road_groups[road.road_id] = (start_group, end_group)
        if start_group == end_group:
            continue
        adjacency.setdefault(start_group, []).append((end_group, road.road_id))
        adjacency.setdefault(end_group, []).append((start_group, road.road_id))

    group_depths: dict[str, int] = {resolved_group_id: 0}
    queue: deque[str] = deque([resolved_group_id])
    while queue:
        group_id = queue.popleft()
        current_depth = group_depths[group_id]
        if current_depth >= bfs_depth:
            continue
        for next_group_id, _road_id in adjacency.get(group_id, []):
            if next_group_id in group_depths:
                continue
            group_depths[next_group_id] = current_depth + 1
            queue.append(next_group_id)

    selected_road_ids: set[str] = set()
    selected_node_ids: set[str] = set(member_node_ids)
    for group_id in group_depths:
        selected_node_ids.update(groups.get(group_id, (group_id,)))

    for road_id, (start_group, end_group) in road_groups.items():
        if start_group in group_depths or end_group in group_depths:
            selected_road_ids.add(road_id)
            selected_node_ids.update(groups.get(start_group, (start_group,)))
            selected_node_ids.update(groups.get(end_group, (end_group,)))
            road = loaded.roads[road_id]
            selected_node_ids.add(road.snodeid)
            selected_node_ids.add(road.enodeid)

    selected_node_ids = {node_id for node_id in selected_node_ids if node_id in loaded.nodes}
    audit = {
        "junction_id": junction_id,
        "resolved_group_id": resolved_group_id,
        "input_issue_flags": tuple(sorted(set(input_flags))),
        "bfs_depth": bfs_depth,
        "visited_group_count": len(group_depths),
        "selected_node_count": len(selected_node_ids),
        "selected_road_count": len(selected_road_ids),
        "group_depths": dict(sorted(group_depths.items(), key=lambda item: (item[1], item[0]))),
    }
    return selected_node_ids, selected_road_ids, audit


def _geometry_origin(geometries: Iterable[BaseGeometry]) -> tuple[float, float]:
    non_empty = [geometry for geometry in geometries if geometry is not None and not geometry.is_empty]
    if not non_empty:
        return 0.0, 0.0
    min_x = min(float(geometry.bounds[0]) for geometry in non_empty)
    min_y = min(float(geometry.bounds[1]) for geometry in non_empty)
    return round(min_x, 1), round(min_y, 1)


def _localized_geometry(geometry: BaseGeometry, *, origin_x: float, origin_y: float) -> BaseGeometry:
    return translate(geometry, xoff=-origin_x, yoff=-origin_y)


def _node_feature(node: NodeRecord, *, origin_x: float, origin_y: float) -> dict[str, Any]:
    return {
        "properties": {
            "id": node.node_id,
            "mainnodeid": node.mainnodeid,
            "kind": node.kind,
        },
        "geometry": _localized_geometry(node.geometry, origin_x=origin_x, origin_y=origin_y),
    }


def _road_feature(road: RoadRecord, *, origin_x: float, origin_y: float) -> dict[str, Any]:
    return {
        "properties": {
            "id": road.road_id,
            "snodeid": road.snodeid,
            "enodeid": road.enodeid,
            "direction": road.direction,
            "formway": road.formway,
        },
        "geometry": _localized_geometry(road.geometry, origin_x=origin_x, origin_y=origin_y),
    }


def _vector_bytes(filename: str, features: list[dict[str, Any]], *, crs_text: str | None) -> bytes:
    with tempfile.TemporaryDirectory() as temp_dir:
        vector_path = Path(temp_dir) / filename
        write_vector(vector_path, features, crs_text=crs_text, layer_name=vector_path.stem)
        return vector_path.read_bytes()


def _prepare_dataset_files(
    loaded: LoadedDataset,
    *,
    junction_id: str,
    bfs_depth: int,
) -> tuple[dict[str, bytes], dict[str, Any]]:
    node_ids, road_ids, audit = _select_bfs_context(loaded, junction_id=junction_id, bfs_depth=bfs_depth)
    selected_nodes = [loaded.nodes[node_id] for node_id in sorted(node_ids)]
    selected_roads = [loaded.roads[road_id] for road_id in sorted(road_ids)]
    origin_x, origin_y = _geometry_origin(
        [node.geometry for node in selected_nodes] + [road.geometry for road in selected_roads]
    )
    node_features = [_node_feature(node, origin_x=origin_x, origin_y=origin_y) for node in selected_nodes]
    road_features = [_road_feature(road, origin_x=origin_x, origin_y=origin_y) for road in selected_roads]
    files = {
        f"{loaded.dataset}/nodes.gpkg": _vector_bytes("nodes.gpkg", node_features, crs_text=_crs_text(loaded.node_layer)),
        f"{loaded.dataset}/roads.gpkg": _vector_bytes("roads.gpkg", road_features, crs_text=_crs_text(loaded.road_layer)),
    }
    audit.update(
        {
            "local_origin": {"x": origin_x, "y": origin_y},
            "node_crs": _crs_text(loaded.node_layer),
            "road_crs": _crs_text(loaded.road_layer),
        }
    )
    return files, audit


def _build_size_report(
    *,
    total_text_size_bytes: int,
    payload_size_bytes: int,
    per_file_raw_size_bytes: dict[str, int],
    per_file_compressed_size_bytes: dict[str, int],
    dataset_audits: dict[str, Any],
    limit_bytes: int,
) -> dict[str, Any]:
    dominant_size_source = None
    if per_file_compressed_size_bytes:
        dominant_size_source = max(per_file_compressed_size_bytes.items(), key=lambda item: item[1])[0]
    return {
        "total_text_size_bytes": total_text_size_bytes,
        "payload_size_bytes": payload_size_bytes,
        "per_file_raw_size_bytes": per_file_raw_size_bytes,
        "per_file_compressed_size_bytes": per_file_compressed_size_bytes,
        "dominant_size_source": dominant_size_source,
        "dataset_audits": dataset_audits,
        "within_limit": total_text_size_bytes <= limit_bytes,
        "limit_bytes": limit_bytes,
    }


def _out_size_report_path(out_txt: Path) -> Path:
    return out_txt.with_suffix(out_txt.suffix + ".size_report.json")


def run_p01_export_text_bundle(
    *,
    swsd_nodes: str | Path,
    swsd_roads: str | Path,
    rcsd_nodes: str | Path,
    rcsd_roads: str | Path,
    frcsd_nodes: str | Path,
    frcsd_roads: str | Path,
    junction_group: str,
    out_txt: str | Path,
    bfs_depth: int = 2,
    max_text_size_bytes: int = P01_TEXT_BUNDLE_LIMIT_BYTES,
) -> P01TextBundleExportArtifacts:
    out_txt_path = Path(out_txt)
    out_txt_path.parent.mkdir(parents=True, exist_ok=True)
    if out_txt_path.exists():
        out_txt_path.unlink()
    size_report_path = _out_size_report_path(out_txt_path)
    if size_report_path.exists():
        size_report_path.unlink()

    try:
        if bfs_depth < 0:
            raise P01TextBundleError("invalid_bfs_depth", "bfs_depth must be >= 0.")
        junction_ids = _parse_junction_group(junction_group)
        dataset_inputs = _dataset_inputs_from_paths(
            swsd_nodes=swsd_nodes,
            swsd_roads=swsd_roads,
            rcsd_nodes=rcsd_nodes,
            rcsd_roads=rcsd_roads,
            frcsd_nodes=frcsd_nodes,
            frcsd_roads=frcsd_roads,
        )
        files: dict[str, bytes] = {}
        dataset_audits: dict[str, Any] = {}
        for dataset in DATASETS:
            loaded = load_dataset(dataset_inputs[dataset])
            dataset_files, audit = _prepare_dataset_files(
                loaded,
                junction_id=junction_ids[dataset],
                bfs_depth=bfs_depth,
            )
            files.update(dataset_files)
            dataset_audits[dataset] = {
                **audit,
                "input_nodes_path": str(dataset_inputs[dataset].nodes_path),
                "input_roads_path": str(dataset_inputs[dataset].roads_path),
            }

        manifest = {
            "bundle_version": P01_TEXT_BUNDLE_VERSION,
            "bundle_type": "p01_arm_build_single_junction_bfs_context",
            "junction_group": junction_ids,
            "bfs_depth": bfs_depth,
            "datasets": dataset_audits,
            "file_list": list(P01_BUNDLE_FILES),
            "checksum": {},
            "encoder_info": {
                "archive_format": "zip",
                "compression": "deflate",
                "text_encoding": "base85",
                "line_width": P01_TEXT_BUNDLE_LINE_WIDTH,
                "max_text_size_bytes": max_text_size_bytes,
                "selection": "semantic-road-topology-bfs",
                "decoded_vector_format": "GeoPackage",
            },
            "created_at": _now_text(),
        }

        files["size_report.json"] = b"{}"
        files["manifest.json"] = b"{}"
        bundle_text = ""
        bundle_size_bytes = 0
        size_report: dict[str, Any] | None = None
        for _ in range(4):
            manifest["checksum"] = {
                name: hashlib.sha256(content).hexdigest()
                for name, content in files.items()
                if name != "manifest.json"
            }
            files["manifest.json"] = json.dumps(manifest, ensure_ascii=False, separators=(",", ":"), allow_nan=False).encode("utf-8")
            payload_bytes, per_file_compressed = _zip_bytes(files)
            meta = {
                "bundle_version": P01_TEXT_BUNDLE_VERSION,
                "bundle_type": manifest["bundle_type"],
                "junction_group": junction_ids,
                "archive_format": "zip",
                "encoding": "base85",
                "payload_sha256": hashlib.sha256(payload_bytes).hexdigest(),
                "created_at": _now_text(),
            }
            bundle_text, bundle_size_bytes = _build_bundle_text(meta=meta, payload_bytes=payload_bytes)
            next_size_report = _build_size_report(
                total_text_size_bytes=bundle_size_bytes,
                payload_size_bytes=len(payload_bytes),
                per_file_raw_size_bytes={name: len(content) for name, content in files.items()},
                per_file_compressed_size_bytes=per_file_compressed,
                dataset_audits=dataset_audits,
                limit_bytes=max_text_size_bytes,
            )
            next_bytes = json.dumps(next_size_report, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8")
            if next_size_report == size_report:
                break
            size_report = next_size_report
            files["size_report.json"] = next_bytes

        if bundle_size_bytes > max_text_size_bytes:
            assert size_report is not None
            size_report_path.write_text(json.dumps(size_report, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
            return P01TextBundleExportArtifacts(
                success=False,
                bundle_txt_path=out_txt_path,
                size_report_path=size_report_path,
                bundle_size_bytes=bundle_size_bytes,
                failure_reason="bundle_too_large",
                failure_detail=f"Bundle text size {bundle_size_bytes} exceeds limit {max_text_size_bytes}.",
            )

        out_txt_path.write_text(bundle_text, encoding="utf-8")
        return P01TextBundleExportArtifacts(
            success=True,
            bundle_txt_path=out_txt_path,
            size_report_path=None,
            bundle_size_bytes=bundle_size_bytes,
        )
    except Exception as exc:
        reason = getattr(exc, "reason", "bundle_export_failed")
        detail = getattr(exc, "detail", str(exc))
        return P01TextBundleExportArtifacts(
            success=False,
            bundle_txt_path=out_txt_path,
            size_report_path=size_report_path if size_report_path.exists() else None,
            bundle_size_bytes=0,
            failure_reason=reason,
            failure_detail=detail,
        )


def _restore_vector_file(
    *,
    source_path: Path,
    target_path: Path,
    origin_x: float,
    origin_y: float,
    crs_text: str | None,
) -> None:
    features: list[dict[str, Any]] = []
    with fiona.open(source_path) as src:
        for feature in src:
            geometry_payload = feature.get("geometry")
            geometry = None if geometry_payload is None else translate(shape(geometry_payload), xoff=origin_x, yoff=origin_y)
            features.append({"properties": dict(feature.get("properties") or {}), "geometry": geometry})
    write_vector(target_path, features, crs_text=crs_text, layer_name=target_path.stem)


def _extract_and_verify_bundle(bundle_txt: Path) -> tuple[dict[str, Any], dict[str, bytes]]:
    _meta, payload_bytes = _parse_text_bundle(bundle_txt.read_text(encoding="utf-8"))
    with zipfile.ZipFile(io.BytesIO(payload_bytes), "r") as zf:
        names = set(zf.namelist())
        missing = [name for name in P01_BUNDLE_FILES if name not in names]
        if missing:
            raise P01TextBundleError("bundle_missing_files", f"Bundle is missing required files: {','.join(missing)}")
        files = {name: zf.read(name) for name in P01_BUNDLE_FILES}
    manifest = json.loads(files["manifest.json"])
    checksums = dict(manifest.get("checksum") or {})
    for name, content in files.items():
        if name == "manifest.json":
            continue
        expected = checksums.get(name)
        if expected and hashlib.sha256(content).hexdigest() != expected:
            raise P01TextBundleError("checksum_mismatch", f"Checksum mismatch for {name}.")
    return manifest, files


def run_p01_decode_text_bundle(
    *,
    bundle_txt: str | Path,
    out_dir: str | Path | None = None,
) -> P01TextBundleDecodeArtifacts:
    bundle_path = Path(bundle_txt)
    if not bundle_path.is_file():
        raise P01TextBundleError("bundle_not_found", f"Bundle text file does not exist: {bundle_path}")
    out_dir_path = Path(out_dir) if out_dir is not None else bundle_path.with_suffix("")
    out_dir_path.mkdir(parents=True, exist_ok=True)
    manifest, files = _extract_and_verify_bundle(bundle_path)

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_root = Path(temp_dir)
        for name, content in files.items():
            temp_path = temp_root / name
            temp_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path.write_bytes(content)
        for dataset in DATASETS:
            dataset_meta = manifest["datasets"][dataset]
            origin = dataset_meta["local_origin"]
            dataset_dir = out_dir_path / dataset
            dataset_dir.mkdir(parents=True, exist_ok=True)
            _restore_vector_file(
                source_path=temp_root / dataset / "nodes.gpkg",
                target_path=dataset_dir / "nodes.gpkg",
                origin_x=float(origin["x"]),
                origin_y=float(origin["y"]),
                crs_text=dataset_meta.get("node_crs"),
            )
            _restore_vector_file(
                source_path=temp_root / dataset / "roads.gpkg",
                target_path=dataset_dir / "roads.gpkg",
                origin_x=float(origin["x"]),
                origin_y=float(origin["y"]),
                crs_text=dataset_meta.get("road_crs"),
            )

    manifest["decoded_output"] = {
        "vector_coordinates": "absolute_source_coordinates",
        "bundle_internal_vectors_localized": True,
        "decoded_at": _now_text(),
    }
    manifest_path = out_dir_path / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8")
    (out_dir_path / "size_report.json").write_bytes(files["size_report.json"])
    return P01TextBundleDecodeArtifacts(success=True, out_dir=out_dir_path, manifest_path=manifest_path)


def _build_export_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p01-export-text-bundle-dev")
    parser.add_argument("--swsd-nodes", required=True)
    parser.add_argument("--swsd-roads", required=True)
    parser.add_argument("--rcsd-nodes", required=True)
    parser.add_argument("--rcsd-roads", required=True)
    parser.add_argument("--frcsd-nodes", required=True)
    parser.add_argument("--frcsd-roads", required=True)
    parser.add_argument("--junction-group", required=True)
    parser.add_argument("--out-txt", required=True)
    parser.add_argument("--bfs-depth", type=int, default=2)
    parser.add_argument("--max-text-size-bytes", type=int, default=P01_TEXT_BUNDLE_LIMIT_BYTES)
    return parser


def _build_decode_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="p01-decode-text-bundle-dev")
    parser.add_argument("--bundle-txt", required=True)
    parser.add_argument("--out-dir")
    return parser


def run_p01_export_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_export_arg_parser().parse_args(argv)
    artifacts = run_p01_export_text_bundle(
        swsd_nodes=args.swsd_nodes,
        swsd_roads=args.swsd_roads,
        rcsd_nodes=args.rcsd_nodes,
        rcsd_roads=args.rcsd_roads,
        frcsd_nodes=args.frcsd_nodes,
        frcsd_roads=args.frcsd_roads,
        junction_group=args.junction_group,
        out_txt=args.out_txt,
        bfs_depth=args.bfs_depth,
        max_text_size_bytes=args.max_text_size_bytes,
    )
    if not artifacts.success:
        print(f"P01 text bundle export failed: {artifacts.failure_detail}", file=sys.stderr)
        if artifacts.size_report_path is not None:
            print(f"size_report={artifacts.size_report_path}", file=sys.stderr)
        return 1
    print(f"P01 text bundle written to: {artifacts.bundle_txt_path}")
    print(f"bundle_size_bytes={artifacts.bundle_size_bytes}")
    return 0


def run_p01_decode_text_bundle_from_args(argv: list[str] | None = None) -> int:
    args = _build_decode_arg_parser().parse_args(argv)
    artifacts = run_p01_decode_text_bundle(bundle_txt=args.bundle_txt, out_dir=args.out_dir)
    print(f"P01 text bundle decoded to: {artifacts.out_dir}")
    print(f"manifest={artifacts.manifest_path}")
    return 0
