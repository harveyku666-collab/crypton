"""Legacy registry export/import helpers.

Usage:
  DEBUG=false python -m app.address_intel.sync_legacy export --output /tmp/legacy_addresses.json
  DEBUG=false python -m app.address_intel.sync_legacy import --input /tmp/legacy_addresses.json
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
from typing import Any

from app.address_intel.legacy_store import fetch_registry_watch_addresses
from app.address_intel.service import bulk_upsert_monitored_addresses


async def export_addresses(output_path: str, *, entity_type: str | None = None, limit: int = 1000) -> dict[str, Any]:
    items = await fetch_registry_watch_addresses(entity_type=entity_type, limit=limit)
    payload = {
        "count": len(items),
        "entity_type": entity_type,
        "items": items,
    }
    path = Path(output_path)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return {"count": len(items), "output": str(path)}


async def import_addresses(input_path: str) -> dict[str, Any]:
    path = Path(input_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    items = payload.get("items") if isinstance(payload, dict) else None
    if not isinstance(items, list):
        raise ValueError("Invalid payload: missing items list")
    return await bulk_upsert_monitored_addresses(items)


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    if args.command == "export":
        return await export_addresses(
            args.output,
            entity_type=args.entity_type,
            limit=args.limit,
        )
    if args.command == "import":
        return await import_addresses(args.input)
    raise ValueError(f"Unsupported command: {args.command}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Sync legacy address registry data")
    sub = parser.add_subparsers(dest="command", required=True)

    export_cmd = sub.add_parser("export", help="Export legacy registry addresses to JSON")
    export_cmd.add_argument("--output", required=True, help="Output JSON file path")
    export_cmd.add_argument("--entity-type", default=None, help="Optional entity type filter")
    export_cmd.add_argument("--limit", type=int, default=1000, help="Max rows to export")

    import_cmd = sub.add_parser("import", help="Import JSON into monitored_addresses")
    import_cmd.add_argument("--input", required=True, help="Input JSON file path")

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    result = asyncio.run(main_async(args))
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
