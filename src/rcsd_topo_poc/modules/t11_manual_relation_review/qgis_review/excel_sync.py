from __future__ import annotations

import json
import re
import shutil
import uuid
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET


MANUAL_FIELDS = ("manual_relation_type", "selected_ids", "comment")
_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
_REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
ET.register_namespace("", _NS)
ET.register_namespace("r", _REL_NS)


@dataclass(frozen=True)
class XlsxRow:
    workbook_path: Path
    sheet_name: str
    excel_row: int
    values: dict[str, str]


@dataclass(frozen=True)
class WorkbookWriteResult:
    workbook_path: Path
    excel_row: int
    backup_path: Path | None
    updated_fields: tuple[str, ...]


def read_xlsx_rows(path: Path) -> list[XlsxRow]:
    path = Path(path)
    with zipfile.ZipFile(path) as archive:
        strings = _read_shared_strings(archive)
        sheet_name = _read_first_sheet_name(archive)
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")
    root = ET.fromstring(sheet_xml)
    table = _sheet_table(root, strings)
    if not table:
        return []
    headers = [_text(value) for value in table[0][1]]
    rows: list[XlsxRow] = []
    for excel_row, values in table[1:]:
        if not any(_text(value) for value in values):
            continue
        row = {
            header: _text(values[index]) if index < len(values) else ""
            for index, header in enumerate(headers)
            if header
        }
        rows.append(XlsxRow(workbook_path=path, sheet_name=sheet_name, excel_row=excel_row, values=row))
    return rows


def check_workbook_writable(path: Path) -> tuple[bool, str]:
    path = Path(path)
    if not path.is_file():
        return False, f"workbook not found: {path}"
    try:
        with path.open("rb+"):
            pass
        with zipfile.ZipFile(path) as archive:
            archive.getinfo("xl/worksheets/sheet1.xml")
    except Exception as exc:
        return False, f"{type(exc).__name__}: {exc}"
    return True, ""


def assert_workbook_writable(path: Path) -> None:
    writable, reason = check_workbook_writable(path)
    if not writable:
        raise PermissionError(reason)


def create_workbook_backup(path: Path, backup_dir: Path | None = None) -> Path:
    path = Path(path)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = backup_dir or path.parent / "_t11_qgis_backups"
    root.mkdir(parents=True, exist_ok=True)
    backup = root / f"{path.stem}_{timestamp}_{uuid.uuid4().hex[:8]}{path.suffix}"
    shutil.copy2(path, backup)
    return backup


def update_manual_fields(
    *,
    workbook_path: Path,
    excel_row: int,
    values: dict[str, Any],
    backup: bool = False,
    backup_dir: Path | None = None,
) -> WorkbookWriteResult:
    path = Path(workbook_path)
    assert_workbook_writable(path)
    manual_values = {field: _text(values.get(field, "")) for field in MANUAL_FIELDS if field in values}
    if not manual_values:
        raise ValueError("no manual fields to update")
    backup_path = create_workbook_backup(path, backup_dir=backup_dir) if backup else None

    with zipfile.ZipFile(path) as archive:
        entries = [(info, archive.read(info.filename)) for info in archive.infolist()]
        entry_map = {info.filename: data for info, data in entries}
    strings = _read_shared_strings_from_bytes(entry_map)
    root = ET.fromstring(entry_map["xl/worksheets/sheet1.xml"])
    header_row = _row_values(_find_row(root, 1), strings) if _find_row(root, 1) is not None else []
    headers = [_text(value) for value in header_row]
    missing = [field for field in manual_values if field not in headers]
    if missing:
        raise KeyError(f"manual fields missing from workbook: {missing}")

    row = _ensure_row(root, excel_row)
    for field, value in manual_values.items():
        col_index = headers.index(field)
        cell = _ensure_cell(row, col_index, excel_row)
        _set_cell_text(cell, value, strings)

    new_sheet = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    new_shared = _shared_strings_xml(strings)
    _rewrite_xlsx(path, entries, {"xl/worksheets/sheet1.xml": new_sheet, "xl/sharedStrings.xml": new_shared})
    _write_last_sync_marker(path, excel_row, tuple(manual_values))
    return WorkbookWriteResult(
        workbook_path=path,
        excel_row=excel_row,
        backup_path=backup_path,
        updated_fields=tuple(manual_values),
    )


def _write_last_sync_marker(path: Path, excel_row: int, fields: tuple[str, ...]) -> None:
    marker = {
        "workbook_path": str(path),
        "excel_row": excel_row,
        "updated_fields": list(fields),
        "updated_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    (path.parent / f".{path.name}.t11_qgis_last_sync.json").write_text(
        json.dumps(marker, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _rewrite_xlsx(path: Path, entries: list[tuple[zipfile.ZipInfo, bytes]], replacements: dict[str, bytes]) -> None:
    tmp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as archive:
            seen: set[str] = set()
            for info, data in entries:
                archive.writestr(info, replacements.get(info.filename, data))
                seen.add(info.filename)
            for name, payload in replacements.items():
                if name not in seen:
                    archive.writestr(name, payload)
        tmp.replace(path)
    finally:
        if tmp.exists():
            tmp.unlink()


def _read_first_sheet_name(archive: zipfile.ZipFile) -> str:
    try:
        workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    except Exception:
        return "Sheet1"
    sheet = workbook.find(f".//{{{_NS}}}sheet")
    return sheet.attrib.get("name", "Sheet1") if sheet is not None else "Sheet1"


def _sheet_table(root: ET.Element, strings: list[str]) -> list[tuple[int, list[str]]]:
    table: list[tuple[int, list[str]]] = []
    for row in root.findall(f".//{{{_NS}}}sheetData/{{{_NS}}}row"):
        row_number = int(row.attrib.get("r", len(table) + 1))
        table.append((row_number, _row_values(row, strings)))
    return table


def _row_values(row: ET.Element | None, strings: list[str]) -> list[str]:
    if row is None:
        return []
    values: dict[int, str] = {}
    for cell in row.findall(f"{{{_NS}}}c"):
        col = _cell_column_index(cell.attrib.get("r", ""))
        if col is None:
            continue
        values[col] = _cell_text(cell, strings)
    width = max(values) + 1 if values else 0
    return [values.get(index, "") for index in range(width)]


def _find_row(root: ET.Element, row_number: int) -> ET.Element | None:
    return root.find(f".//{{{_NS}}}sheetData/{{{_NS}}}row[@r='{row_number}']")


def _ensure_row(root: ET.Element, row_number: int) -> ET.Element:
    row = _find_row(root, row_number)
    if row is not None:
        return row
    sheet_data = root.find(f".//{{{_NS}}}sheetData")
    if sheet_data is None:
        sheet_data = ET.SubElement(root, f"{{{_NS}}}sheetData")
    row = ET.Element(f"{{{_NS}}}row", {"r": str(row_number)})
    for index, existing in enumerate(list(sheet_data)):
        try:
            existing_row = int(existing.attrib.get("r", "0"))
        except ValueError:
            existing_row = 0
        if existing_row > row_number:
            sheet_data.insert(index, row)
            return row
    sheet_data.append(row)
    return row


def _ensure_cell(row: ET.Element, col_index: int, row_number: int) -> ET.Element:
    ref = f"{_excel_col(col_index + 1)}{row_number}"
    for cell in row.findall(f"{{{_NS}}}c"):
        if cell.attrib.get("r") == ref:
            return cell
    cell = ET.Element(f"{{{_NS}}}c", {"r": ref})
    for index, existing in enumerate(list(row)):
        existing_col = _cell_column_index(existing.attrib.get("r", ""))
        if existing_col is not None and existing_col > col_index:
            row.insert(index, cell)
            return cell
    row.append(cell)
    return cell


def _set_cell_text(cell: ET.Element, value: str, strings: list[str]) -> None:
    for child in list(cell):
        cell.remove(child)
    if not value:
        cell.attrib.pop("t", None)
        return
    cell.attrib["t"] = "s"
    if value not in strings:
        strings.append(value)
    ET.SubElement(cell, f"{{{_NS}}}v").text = str(strings.index(value))


def _cell_text(cell: ET.Element, strings: list[str]) -> str:
    value = cell.find(f"{{{_NS}}}v")
    if value is None or value.text is None:
        inline = cell.find(f"{{{_NS}}}is/{{{_NS}}}t")
        return _text(inline.text if inline is not None else "")
    if cell.attrib.get("t") == "s":
        try:
            return strings[int(value.text)]
        except (ValueError, IndexError):
            return ""
    return _text(value.text)


def _read_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    try:
        return _parse_shared_strings(archive.read("xl/sharedStrings.xml"))
    except KeyError:
        return []


def _read_shared_strings_from_bytes(entries: dict[str, bytes]) -> list[str]:
    return _parse_shared_strings(entries.get("xl/sharedStrings.xml", b""))


def _parse_shared_strings(data: bytes) -> list[str]:
    if not data:
        return []
    root = ET.fromstring(data)
    strings: list[str] = []
    for item in root.findall(f"{{{_NS}}}si"):
        parts = [node.text or "" for node in item.findall(f".//{{{_NS}}}t")]
        strings.append("".join(parts))
    return strings


def _shared_strings_xml(strings: list[str]) -> bytes:
    root = ET.Element(f"{{{_NS}}}sst", {"count": str(len(strings)), "uniqueCount": str(len(strings))})
    for value in strings:
        item = ET.SubElement(root, f"{{{_NS}}}si")
        text = ET.SubElement(item, f"{{{_NS}}}t")
        if value != value.strip():
            text.attrib["{http://www.w3.org/XML/1998/namespace}space"] = "preserve"
        text.text = value
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def _cell_column_index(ref: str) -> int | None:
    match = re.match(r"([A-Z]+)", ref.upper())
    if not match:
        return None
    value = 0
    for char in match.group(1):
        value = value * 26 + ord(char) - ord("A") + 1
    return value - 1


def _excel_col(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result or "A"


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value != value:
        return ""
    return str(value).strip()
