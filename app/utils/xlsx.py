from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET
from zipfile import ZipFile

_XL_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def read_xlsx_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []

    with ZipFile(path) as archive:
        sheet_xml = archive.read("xl/worksheets/sheet1.xml")

    root = ET.fromstring(sheet_xml)
    rows: list[list[str]] = []
    for row_node in root.findall(".//x:sheetData/x:row", _XL_NS):
        values: list[str] = []
        for cell in row_node.findall("x:c", _XL_NS):
            inline = cell.find("x:is/x:t", _XL_NS)
            if inline is not None:
                values.append(inline.text or "")
                continue
            value = cell.find("x:v", _XL_NS)
            values.append(value.text if value is not None else "")
        rows.append(values)

    if not rows:
        return []

    headers = [str(v or "").strip() for v in rows[0]]
    data_rows: list[dict[str, str]] = []
    for row in rows[1:]:
        padded = row + [""] * max(0, len(headers) - len(row))
        data_rows.append({headers[idx]: padded[idx] for idx in range(len(headers))})
    return data_rows
