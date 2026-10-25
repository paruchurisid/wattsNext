"""Minimal stdlib .xlsx reader (no third-party deps needed)."""
import zipfile
import re
from xml.etree import ElementTree as ET

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _col_to_idx(cellref):
    m = re.match(r"([A-Z]+)(\d+)", cellref)
    col = m.group(1)
    idx = 0
    for ch in col:
        idx = idx * 26 + (ord(ch) - ord("A") + 1)
    return idx - 1


def read_xlsx(path):
    z = zipfile.ZipFile(path)
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            texts = si.findall(".//m:t", NS)
            shared.append("".join(t.text or "" for t in texts))

    sheet_names = sorted(n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml"))
    results = {}
    for sn in sheet_names:
        root = ET.fromstring(z.read(sn))
        rows_out = []
        for row in root.findall(".//m:sheetData/m:row", NS):
            rowdict = {}
            maxcol = -1
            for c in row.findall("m:c", NS):
                ref = c.get("r")
                ctype = c.get("t")
                v = c.find("m:v", NS)
                val = v.text if v is not None else None
                if ctype == "s" and val is not None:
                    val = shared[int(val)]
                colidx = _col_to_idx(ref)
                rowdict[colidx] = val
                maxcol = max(maxcol, colidx)
            rows_out.append([rowdict.get(i) for i in range(maxcol + 1)])
        results[sn] = rows_out
    return results
