"""Bounded parsing. Workbooks are data, never executable instructions."""

import hashlib
import io
import struct
import zipfile
from datetime import datetime
from pathlib import Path, PurePosixPath
from uuid import uuid4

import olefile
import openpyxl
import pandas as pd
import xlrd

from .store import dumps


def check_archive(body, maximum_uncompressed=150_000_000):
    try:
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            infos = archive.infolist()
            if len(infos) > 5000 or sum(i.file_size for i in infos) > maximum_uncompressed:
                raise ValueError("Workbook archive exceeds the expanded-size limit.")
            for item in infos:
                name = PurePosixPath(item.filename.replace("\\", "/"))
                if name.is_absolute() or ".." in name.parts or item.flag_bits & 1:
                    raise ValueError("Unsafe or encrypted archive entry.")
                if item.file_size > 1_000_000 and item.file_size / max(item.compress_size, 1) > 200:
                    raise ValueError("Suspicious compression ratio.")
                lower = str(name).lower()
                if any(
                    token in lower for token in ["vbaproject", "macrosheet", "externallinks", "embeddings/"]
                ):
                    raise ValueError("Macros, embedded objects and external workbook links are not accepted.")
    except zipfile.BadZipFile as exc:
        raise ValueError("Invalid XLSX archive.") from exc


def check_legacy(body):
    if not olefile.isOleFile(io.BytesIO(body)):
        raise ValueError("XLS must be an unencrypted OLE workbook.")
    with olefile.OleFileIO(io.BytesIO(body)) as ole:
        names = ["/".join(parts).lower() for parts in ole.listdir()]
        if any(any(marker in name for marker in ["vba", "macro", "objectpool"]) for name in names):
            raise ValueError("Legacy workbook contains macro or embedded object streams.")
        name = "Workbook" if ole.exists("Workbook") else "Book"
        stream = ole.openstream(name).read()
        offset = 0
        while offset + 4 <= len(stream):
            record, length = struct.unpack_from("<HH", stream, offset)
            content = stream[offset + 4 : offset + 4 + length]
            if record == 0x002F:
                raise ValueError("Encrypted XLS is not supported.")
            if record == 0x0085 and len(content) >= 6 and content[5] != 0:
                raise ValueError("Only ordinary worksheets are accepted in legacy XLS.")
            if record == 0x0006:
                raise ValueError("Export workbook formulas as values before uploading.")
            offset += 4 + length


def validate_headers(values, max_columns):
    headers = [str(value).strip() if value is not None else "" for value in values]
    if len(headers) > max_columns or not headers or any(not v for v in headers):
        raise ValueError("Every column needs a nonempty header; check the column limit.")
    if len(set(headers)) != len(headers):
        raise ValueError("Duplicate column headers must be renamed in the source file.")
    if any(h.startswith(("_", "raw__")) for h in headers):
        raise ValueError("Headers beginning with '_' or 'raw__' are reserved.")
    return headers


def read_tables(body, extension, settings):
    tables = {}
    remaining = settings.max_rows
    if extension == ".csv":
        text = body.decode("utf-8-sig", errors="strict")
        import csv

        try:
            dialect = csv.Sniffer().sniff(text[:8192], delimiters=",;\t|")
            delimiter = dialect.delimiter
        except csv.Error:
            delimiter = ","
        rows = csv.reader(io.StringIO(text), delimiter=delimiter)
        headers = validate_headers(next(rows, []), settings.max_columns)
        frame = pd.read_csv(
            io.StringIO(text),
            sep=delimiter,
            dtype="string",
            keep_default_na=False,
            nrows=remaining + 1,
            on_bad_lines="error",
        )
        frame.columns = headers
        tables["CSV"] = frame.replace("", pd.NA)
    elif extension == ".xlsx":
        check_archive(body)
        book = openpyxl.load_workbook(io.BytesIO(body), read_only=True, data_only=False, keep_links=False)
        try:
            if len(book.worksheets) > 30:
                raise ValueError("At most 30 worksheets are supported.")
            for sheet in book.worksheets:
                if sheet.max_row > remaining + 1 or sheet.max_column > settings.max_columns:
                    raise ValueError("Worksheet exceeds row or column limits.")
                rows = sheet.iter_rows()
                first = next(rows, None)
                if first is None or all(c.value is None for c in first):
                    continue
                if any(cell.data_type == "f" for cell in first):
                    raise ValueError("Column headers cannot contain formulas.")
                headers = validate_headers([cell.value for cell in first], settings.max_columns)
                values = []
                for cells in rows:
                    if any(cell.data_type == "f" for cell in cells):
                        raise ValueError("Export formulas as values before uploading the workbook.")
                    if len(values) >= remaining:
                        raise ValueError("Workbook exceeds the total row limit.")
                    values.append(
                        [
                            cell.value.date().isoformat()
                            if isinstance(cell.value, datetime)
                            and cell.value.time().isoformat() == "00:00:00"
                            else cell.value
                            for cell in cells
                        ]
                    )
                remaining -= len(values)
                tables[sheet.title] = (
                    pd.DataFrame(values, columns=headers).astype("string").replace("", pd.NA)
                )
        finally:
            book.close()
    elif extension == ".xls":
        check_legacy(body)
        book = xlrd.open_workbook(file_contents=body, on_demand=True)
        try:
            if book.nsheets > 30:
                raise ValueError("At most 30 worksheets are supported.")
            for sheet in book.sheets():
                if sheet.nrows < 1:
                    continue
                if sheet.nrows - 1 > remaining or sheet.ncols > settings.max_columns:
                    raise ValueError("Workbook exceeds row or column limits.")
                headers = validate_headers(sheet.row_values(0), settings.max_columns)
                values = []
                for number in range(1, sheet.nrows):
                    row = []
                    for cell in sheet.row(number):
                        value = cell.value
                        if cell.ctype == xlrd.XL_CELL_DATE:
                            value = xlrd.xldate_as_datetime(value, book.datemode).isoformat(sep=" ")
                        elif cell.ctype == xlrd.XL_CELL_NUMBER and float(value).is_integer():
                            value = str(int(value))
                        row.append(value)
                    values.append(row)
                remaining -= len(values)
                tables[sheet.name] = pd.DataFrame(values, columns=headers).astype("string").replace("", pd.NA)
        finally:
            book.release_resources()
    else:
        raise ValueError("Supported file types: .csv, .xlsx and restricted .xls.")
    if not tables or any(len(frame) > settings.max_rows for frame in tables.values()):
        raise ValueError("Empty file or too many rows.")
    if sum(len(frame) for frame in tables.values()) == 0:
        raise ValueError("The file contains no data rows.")
    return tables


def ingest(store, settings, filename, body):
    if not body or len(body) > settings.max_upload_mb * 1024 * 1024:
        raise ValueError("Empty file or upload exceeds the configured size limit.")
    # Client filenames are metadata only; never concatenate them into storage paths.
    extension = Path(filename.replace("\\", "/")).suffix.lower()
    tables = read_tables(body, extension, settings)
    meta = {
        "filename": Path(filename.replace("\\", "/")).name[:200],
        "extension": extension,
        "content_hash": hashlib.sha256(body).hexdigest(),
        "state": "uploaded",
        "sheets": {},
    }
    dataset_id = store.create(meta)
    directory = store.directory(dataset_id)
    (directory / f"original{extension}").write_bytes(body)
    for index, (name, frame) in enumerate(tables.items()):
        path = f"sheet_{index}.parquet"
        frame.to_parquet(directory / path, index=False)
        meta["sheets"][name] = {"path": path, "rows": len(frame), "columns": list(frame.columns)}
    store.update(dataset_id, meta, 0)
    store.audit(dataset_id, "upload", {"content_hash": meta["content_hash"], "sheets": list(tables)})
    return store.get(dataset_id)


def raw_sheet(store, dataset_id, sheet):
    data = store.get(dataset_id)
    if sheet not in data["meta"]["sheets"]:
        raise ValueError("Unknown sheet.")
    return pd.read_parquet(store.directory(dataset_id) / data["meta"]["sheets"][sheet]["path"])


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(f".{path.name}.{uuid4().hex}.tmp")
    temporary.write_text(dumps(value), encoding="utf-8")
    temporary.replace(path)
