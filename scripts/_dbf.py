"""Minimal stdlib dBase III/IV .dbf reader (no third-party deps needed)."""
import struct


def read_dbf(path, limit=None):
    with open(path, "rb") as f:
        header = f.read(32)
        header_size = struct.unpack("<H", header[8:10])[0]
        record_size = struct.unpack("<H", header[10:12])[0]

        fields = []
        f.seek(32)
        while True:
            field_header = f.read(32)
            if field_header[0:1] == b"\r":
                break
            name = field_header[0:11].rstrip(b"\x00").decode("latin-1")
            ftype = field_header[11:12].decode("latin-1")
            flen = field_header[16]
            fields.append((name, ftype, flen))

        f.seek(header_size)
        records = []
        count = 0
        while True:
            if limit is not None and count >= limit:
                break
            rec = f.read(record_size)
            if len(rec) < record_size:
                break
            if rec[0:1] == b"*":
                continue
            offset = 1
            row = {}
            for name, ftype, flen in fields:
                raw = rec[offset:offset + flen].decode("latin-1", errors="replace").strip()
                offset += flen
                if ftype in ("N", "F"):
                    try:
                        row[name] = float(raw) if raw else None
                        if row[name] is not None and row[name] == int(row[name]):
                            row[name] = int(row[name])
                    except ValueError:
                        row[name] = None
                elif ftype == "L":
                    row[name] = raw in ("T", "t", "Y", "y")
                else:
                    row[name] = raw
            records.append(row)
            count += 1
        return fields, records
