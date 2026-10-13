"""Fetch only the India split of RDD2022 from the 13 GB Figshare archive, using HTTP Range requests.

zipfile only needs a seekable file: we read the central directory from the end of the remote archive,
then pull just the members under the India folder (~0.5 GB instead of 13 GB).

Source : https://figshare.com/articles/dataset/21431547 (sekilab, CRDDC'2022)
Licence: CC BY-SA 4.0 per the sekilab README (Figshare lists CC BY 4.0); we follow the stricter BY-SA.
Usage  : uv run python scripts/data/fetch_rdd2022_india.py [--list]
"""

from __future__ import annotations

import argparse
import datetime as dt
import io
import sys
import urllib.request
import zipfile
from pathlib import Path

URL = "https://ndownloader.figshare.com/files/38030910"
ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "raw" / "rdd2022_india"
UA = {"User-Agent": "Patchwork/0.1 (OpenCV AI Competition 2026 research project)"}


class HTTPRangeFile(io.RawIOBase):
    """Read-only, seekable view of a remote file via Range requests (redirects re-resolved per read)."""

    def __init__(self, url: str):
        self.url = url
        req = urllib.request.Request(url, headers={**UA, "Range": "bytes=0-0"})
        with urllib.request.urlopen(req, timeout=60) as r:
            self.size = int(r.headers["Content-Range"].split("/")[-1])
        self.pos = 0

    def seekable(self) -> bool:
        return True

    def readable(self) -> bool:
        return True

    def tell(self) -> int:
        return self.pos

    def seek(self, offset: int, whence: int = 0) -> int:
        self.pos = {0: offset, 1: self.pos + offset, 2: self.size + offset}[whence]
        return self.pos

    def read(self, n: int = -1) -> bytes:
        if n is None or n < 0:
            n = self.size - self.pos
        if n == 0 or self.pos >= self.size:
            return b""
        end = min(self.pos + n, self.size) - 1
        for attempt in range(5):
            try:
                req = urllib.request.Request(self.url, headers={**UA, "Range": f"bytes={self.pos}-{end}"})
                with urllib.request.urlopen(req, timeout=120) as r:
                    data = r.read()
                break
            except Exception:  # noqa: BLE001 - transient network errors
                if attempt == 4:
                    raise
        self.pos += len(data)
        return data

    def readinto(self, b) -> int:
        data = self.read(len(b))
        b[: len(data)] = data
        return len(data)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--list", action="store_true", help="only list the India members")
    args = ap.parse_args()
    f = io.BufferedReader(HTTPRangeFile(URL), buffer_size=8 << 20)
    z = zipfile.ZipFile(f)
    members = [m for m in z.infolist() if m.filename.endswith("/India.zip")]
    if not members:
        raise SystemExit(f"India.zip not found in archive: {[m.filename for m in z.infolist()]}")
    total = sum(m.file_size for m in members)
    print(f"archive {f.raw.size / 1e9:.1f} GB, {len(z.infolist())} members; fetching {members[0].filename} ({total / 1e6:.0f} MB)")
    if args.list:
        return
    OUT.mkdir(parents=True, exist_ok=True)
    data = z.read(members[0])  # stored uncompressed; ~0.5 GB in memory is fine
    with zipfile.ZipFile(io.BytesIO(data)) as inner:
        names = inner.namelist()
        inner.extractall(OUT)
    print(f"extracted {len(names)} files")
    (OUT / "SOURCE.md").write_text(
        "# RDD2022 (India split)\n\n"
        "- Source: https://figshare.com/articles/dataset/21431547 (sekilab, CRDDC'2022), member folder `India/`\n"
        "- Licence: CC BY-SA 4.0 (sekilab README); Figshare page states CC BY 4.0. Treated as CC BY-SA 4.0.\n"
        "- Citation: Arya et al., RDD2022: A multi-national image dataset for automatic road damage detection (2024)\n"
        f"- Fetched {dt.datetime.now(dt.UTC):%Y-%m-%d %H:%M} UTC via HTTP range requests (India.zip, {total / 1e6:.0f} MB, {len(names)} files)\n"
        "- Annotations: Pascal VOC bounding boxes; D40 = pothole\n")
    print(f"done -> {OUT}")


if __name__ == "__main__":
    sys.exit(main())
