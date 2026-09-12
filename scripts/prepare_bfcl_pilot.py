"""Download exact pinned public BFCL sources, then freeze a bounded pilot."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.request import urlopen

from app.public_benchmarks.bfcl import SOURCE_HASHES, SOURCE_SHA, prepare_pilot


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--per-category", type=int, default=25)
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    if args.download:
        for relative, expected in SOURCE_HASHES.items():
            destination = args.root / "upstream" / relative
            if destination.exists():
                raw = destination.read_bytes()
            else:
                url = f"https://raw.githubusercontent.com/ShishirPatil/gorilla/{SOURCE_SHA}/{relative}"
                with urlopen(url, timeout=60) as response:
                    raw = response.read(16 * 1024 * 1024)
                if hashlib.sha256(raw).hexdigest() != expected:
                    raise ValueError(f"download_hash_mismatch:{relative}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                with destination.open("xb") as stream:
                    stream.write(raw)
            if hashlib.sha256(raw).hexdigest() != expected:
                raise ValueError(f"existing_source_hash_mismatch:{relative}")
    print(json.dumps(prepare_pilot(args.root, args.per_category), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
