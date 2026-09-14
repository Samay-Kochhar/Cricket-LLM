from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def compose(base: list[dict[str, Any]], replacements: list[list[dict[str, Any]]]) -> list[dict[str, Any]]:
    by_id = {str(row["id"]): row for rows in replacements for row in rows}
    return [by_id.get(str(row["id"]), row) for row in base]


def main() -> int:
    parser = argparse.ArgumentParser(description="Compose a complete benchmark capture from targeted recaptures.")
    parser.add_argument("--base", type=Path, required=True)
    parser.add_argument("--replacement", type=Path, action="append", default=[])
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    records = compose(load_jsonl(args.base), [load_jsonl(path) for path in args.replacement])
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text("".join(json.dumps(row, sort_keys=True) + "\n" for row in records), encoding="utf-8")
    print(f"Wrote {len(records)} records to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
