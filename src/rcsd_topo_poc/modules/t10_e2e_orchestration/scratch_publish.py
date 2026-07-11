from __future__ import annotations

import base64
import json
import os
import shutil
import sqlite3
import subprocess
import time
from pathlib import Path
from typing import Any


TEXT_OUTPUT_SUFFIXES = {".csv", ".json", ".jsonl", ".log", ".md"}


def publish_t10_scratch_run(
    *,
    scratch_out_root: str | Path,
    final_out_root: str | Path,
    run_id: str,
    keep_scratch: bool = False,
    prefer_windows_tar: bool = True,
) -> dict[str, Any]:
    safe_run_id = _safe_run_id(run_id)
    scratch_root = Path(scratch_out_root).expanduser().resolve()
    final_root = Path(final_out_root).expanduser().resolve()
    source_run_root = scratch_root / safe_run_id
    final_run_root = final_root / safe_run_id
    if not source_run_root.is_dir():
        raise FileNotFoundError(f"T10 scratch run root is missing: {source_run_root}")
    if final_run_root.exists():
        raise FileExistsError(f"T10 final run root already exists: {final_run_root}")
    if source_run_root.resolve().parent != scratch_root:
        raise ValueError(f"Scratch run root escaped configured scratch root: {source_run_root}")
    if final_run_root == source_run_root:
        raise ValueError("T10 scratch and final run roots must be different.")

    started = time.perf_counter()
    source_file_count, source_size_bytes = _tree_inventory(source_run_root)
    final_root.mkdir(parents=True, exist_ok=True)
    scratch_archive = scratch_root / f".{safe_run_id}.publish.tar"
    staged_archive = final_root / f".{safe_run_id}.publish.tar"
    for archive in (scratch_archive, staged_archive):
        if archive.exists():
            raise FileExistsError(f"T10 scratch publish archive already exists: {archive}")

    try:
        _create_archive(source_run_root, scratch_archive)
        shutil.copyfile(scratch_archive, staged_archive)
        _extract_archive(
            staged_archive,
            final_root,
            prefer_windows_tar=prefer_windows_tar,
        )
    finally:
        staged_archive.unlink(missing_ok=True)
        scratch_archive.unlink(missing_ok=True)

    old_root = str(source_run_root)
    new_root = str(final_run_root)
    native_finalize = _finalize_with_windows_powershell(
        final_run_root,
        old_root=old_root,
        new_root=new_root,
    )
    if native_finalize is None:
        published_file_count, published_size_bytes = _tree_inventory(final_run_root)
        text_rebase = _rebase_text_outputs(final_run_root, old_root=old_root, new_root=new_root)
    else:
        published_file_count, published_size_bytes, changed_files, replacements = native_finalize
        text_rebase = (changed_files, replacements)
    if (published_file_count, published_size_bytes) != (source_file_count, source_size_bytes):
        raise RuntimeError(
            "T10 scratch publish inventory mismatch: "
            f"source=({source_file_count}, {source_size_bytes}) "
            f"published=({published_file_count}, {published_size_bytes})"
        )

    gpkg_rebase = _rebase_t03_surface_paths(final_run_root, old_root=old_root, new_root=new_root)
    if not keep_scratch:
        _remove_verified_scratch_run(source_run_root, scratch_root=scratch_root)

    publish_seconds = round(time.perf_counter() - started, 6)
    end_to_end_seconds = _update_run_performance(
        final_run_root,
        publish_seconds=publish_seconds,
    )
    return {
        "status": "published",
        "run_id": safe_run_id,
        "scratch_run_root": str(source_run_root),
        "final_run_root": str(final_run_root),
        "source_file_count": source_file_count,
        "source_size_bytes": source_size_bytes,
        "published_file_count": published_file_count,
        "published_size_bytes": published_size_bytes,
        "text_rebased_file_count": text_rebase[0],
        "text_replacement_count": text_rebase[1],
        "gpkg_rebased_row_count": gpkg_rebase,
        "publish_seconds": publish_seconds,
        "end_to_end_seconds": end_to_end_seconds,
        "scratch_retained": keep_scratch,
    }


def _safe_run_id(value: str) -> str:
    run_id = str(value or "").strip()
    if not run_id or run_id in {".", ".."} or Path(run_id).name != run_id:
        raise ValueError(f"Unsafe T10 run_id for scratch publish: {value!r}")
    return run_id


def _tree_inventory(root: Path) -> tuple[int, int]:
    file_count = 0
    size_bytes = 0
    for directory, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            path = Path(directory) / filename
            file_count += 1
            size_bytes += path.stat().st_size
    return file_count, size_bytes


def _create_archive(source_run_root: Path, archive_path: Path) -> None:
    subprocess.run(
        [
            "tar",
            "-C",
            str(source_run_root.parent),
            "-cf",
            str(archive_path),
            source_run_root.name,
        ],
        check=True,
    )


def _extract_archive(archive_path: Path, destination: Path, *, prefer_windows_tar: bool) -> None:
    if prefer_windows_tar and _extract_archive_with_windows_tar(archive_path, destination):
        return
    subprocess.run(
        ["tar", "-xf", str(archive_path), "-C", str(destination)],
        check=True,
    )


def _extract_archive_with_windows_tar(archive_path: Path, destination: Path) -> bool:
    if os.name != "posix" or not str(destination).startswith("/mnt/"):
        return False
    tar_exe = shutil.which("tar.exe")
    wslpath = shutil.which("wslpath")
    if not tar_exe or not wslpath:
        return False
    archive_windows = subprocess.check_output(
        [wslpath, "-w", str(archive_path)],
        text=True,
    ).strip()
    destination_windows = subprocess.check_output(
        [wslpath, "-w", str(destination)],
        text=True,
    ).strip()
    try:
        subprocess.run(
            [tar_exe, "-xf", archive_windows, "-C", destination_windows],
            check=True,
        )
    except (OSError, subprocess.CalledProcessError):
        init = Path("/init")
        if not init.is_file():
            return False
        try:
            subprocess.run(
                [
                    str(init),
                    tar_exe,
                    Path(tar_exe).name,
                    "-xf",
                    archive_windows,
                    "-C",
                    destination_windows,
                ],
                check=True,
            )
        except (OSError, subprocess.CalledProcessError):
            return False
    return True


def _finalize_with_windows_powershell(
    root: Path,
    *,
    old_root: str,
    new_root: str,
) -> tuple[int, int, int, int] | None:
    if os.name != "posix" or not str(root).startswith("/mnt/"):
        return None
    init = Path("/init")
    powershell_exe = shutil.which("powershell.exe")
    wslpath = shutil.which("wslpath")
    if not init.is_file() or not powershell_exe or not wslpath:
        return None
    root_windows = subprocess.check_output(
        [wslpath, "-w", str(root)],
        text=True,
    ).strip()
    script = _windows_finalize_script(
        root_windows=root_windows,
        old_root=old_root,
        new_root=new_root,
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    try:
        output_bytes = subprocess.check_output(
            [
                str(init),
                powershell_exe,
                Path(powershell_exe).name,
                "-NoProfile",
                "-NonInteractive",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encoded,
            ],
            stderr=subprocess.STDOUT,
        )
    except (OSError, subprocess.CalledProcessError):
        return None
    output = _decode_windows_output(output_bytes)
    marker = "T10_FINALIZE|"
    for line in reversed(output.splitlines()):
        if not line.startswith(marker):
            continue
        values = line[len(marker) :].split("|")
        if len(values) != 4:
            return None
        return tuple(int(value) for value in values)  # type: ignore[return-value]
    return None


def _windows_finalize_script(*, root_windows: str, old_root: str, new_root: str) -> str:
    root_value = _powershell_literal(root_windows)
    old_value = _powershell_literal(old_root)
    new_value = _powershell_literal(new_root)
    return f"""
$ErrorActionPreference = 'Stop'
$utf8 = New-Object System.Text.UTF8Encoding($false)
[Console]::OutputEncoding = $utf8
$OutputEncoding = $utf8
$root = {root_value}
$oldRoot = {old_value}
$newRoot = {new_value}
$suffixes = @('.csv', '.json', '.jsonl', '.log', '.md')
$files = @(Get-ChildItem -LiteralPath $root -Recurse -File)
$fileCount = $files.Count
$sizeBytes = [int64](($files | Measure-Object -Property Length -Sum).Sum)
$changedFiles = 0
$replacements = 0
foreach ($file in $files) {{
    if ($suffixes -notcontains $file.Extension.ToLowerInvariant()) {{ continue }}
    $text = [System.IO.File]::ReadAllText($file.FullName)
    $index = 0
    $count = 0
    while (($index = $text.IndexOf($oldRoot, $index, [System.StringComparison]::Ordinal)) -ge 0) {{
        $count += 1
        $index += $oldRoot.Length
    }}
    if ($count -eq 0) {{ continue }}
    [System.IO.File]::WriteAllText($file.FullName, $text.Replace($oldRoot, $newRoot), $utf8)
    $changedFiles += 1
    $replacements += $count
}}
Write-Output ('T10_FINALIZE|' + $fileCount + '|' + $sizeBytes + '|' + $changedFiles + '|' + $replacements)
"""


def _powershell_literal(value: str) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def _decode_windows_output(payload: bytes) -> str:
    for encoding in ("utf-8", "utf-16le", "gb18030", "cp1252"):
        try:
            value = payload.decode(encoding)
        except UnicodeDecodeError:
            continue
        if "T10_FINALIZE|" in value:
            return value
    return payload.decode("utf-8", errors="replace")


def _rebase_text_outputs(root: Path, *, old_root: str, new_root: str) -> tuple[int, int]:
    old_bytes = old_root.encode("utf-8")
    new_bytes = new_root.encode("utf-8")
    changed_files = 0
    replacements = 0
    for directory, _dirnames, filenames in os.walk(root):
        for filename in filenames:
            path = Path(directory) / filename
            if path.suffix.lower() not in TEXT_OUTPUT_SUFFIXES:
                continue
            payload = path.read_bytes()
            count = payload.count(old_bytes)
            if not count:
                continue
            path.write_bytes(payload.replace(old_bytes, new_bytes))
            changed_files += 1
            replacements += count
    return changed_files, replacements


def _rebase_t03_surface_paths(root: Path, *, old_root: str, new_root: str) -> int:
    updated_rows = 0
    for path in root.glob("cases/*/t03/t03/virtual_intersection_polygons.gpkg"):
        with sqlite3.connect(path) as connection:
            row = connection.execute(
                "SELECT table_name FROM gpkg_geometry_columns LIMIT 1"
            ).fetchone()
            if row is None:
                continue
            table_name = str(row[0])
            table_sql = _quote_identifier(table_name)
            columns = {
                str(item[1])
                for item in connection.execute(f"PRAGMA table_info({table_sql})")
            }
            if "source_case_dir" not in columns:
                continue
            match_count = int(
                connection.execute(
                    f"SELECT COUNT(*) FROM {table_sql} WHERE instr(source_case_dir, ?) > 0",
                    (old_root,),
                ).fetchone()[0]
            )
            if not match_count:
                continue
            triggers = connection.execute(
                "SELECT name, sql FROM sqlite_master "
                "WHERE type = 'trigger' AND tbl_name = ? AND sql IS NOT NULL",
                (table_name,),
            ).fetchall()
            for name, _sql in triggers:
                connection.execute(f"DROP TRIGGER {_quote_identifier(str(name))}")
            connection.execute(
                f"UPDATE {table_sql} "
                "SET source_case_dir = replace(source_case_dir, ?, ?) "
                "WHERE instr(source_case_dir, ?) > 0",
                (old_root, new_root, old_root),
            )
            for _name, sql in triggers:
                connection.execute(str(sql))
            connection.commit()
            updated_rows += match_count
    return updated_rows


def _quote_identifier(value: str) -> str:
    return '"' + str(value).replace('"', '""') + '"'


def _remove_verified_scratch_run(source_run_root: Path, *, scratch_root: Path) -> None:
    resolved_source = source_run_root.resolve()
    resolved_scratch = scratch_root.resolve()
    if resolved_source.parent != resolved_scratch or resolved_source == resolved_scratch:
        raise ValueError(f"Refusing unsafe T10 scratch cleanup: {resolved_source}")
    shutil.rmtree(resolved_source)


def _update_run_performance(final_run_root: Path, *, publish_seconds: float) -> float:
    summary_path = final_run_root / "t10_e2e_run_summary.json"
    manifest_path = final_run_root / "t10_e2e_run_manifest.json"
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    execution_seconds = float(summary.get("duration_seconds") or 0.0)
    end_to_end_seconds = round(execution_seconds + publish_seconds, 6)
    for path in (summary_path, manifest_path):
        payload = json.loads(path.read_text(encoding="utf-8"))
        performance = payload.get("performance")
        if not isinstance(performance, dict):
            performance = {}
        payload["performance"] = {
            **performance,
            "scratch_execution_seconds": execution_seconds,
            "scratch_publish_seconds": publish_seconds,
            "end_to_end_seconds": end_to_end_seconds,
        }
        payload["duration_seconds"] = end_to_end_seconds
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False),
            encoding="utf-8",
        )
    return end_to_end_seconds


__all__ = ["publish_t10_scratch_run"]
