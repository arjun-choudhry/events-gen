"""Command-line entry point for inspecting and managing the registry.

Usage:
    python -m events_gen.cli list-cities
    python -m events_gen.cli list-types
    python -m events_gen.cli add-city --name "Paris" --country France \\
        --country-code FR --timezone Europe/Paris --lat 48.8566 --lon 2.3522

More subcommands are added as later milestones land (fetch, render, publish).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from .registry import RegistryError, add_city, load_cities, load_event_types


def _cmd_list_cities(_: argparse.Namespace) -> int:
    cities = load_cities()
    print(f"{'slug':<14} {'name':<18} {'country':<18} timezone")
    print("-" * 64)
    for c in sorted(cities, key=lambda c: c.slug):
        print(f"{c.slug:<14} {c.name:<18} {c.country:<18} {c.timezone}")
    print(f"\n{len(cities)} cities")
    return 0


def _cmd_list_types(_: argparse.Namespace) -> int:
    types = load_event_types()
    print(f"{'slug':<12} name")
    print("-" * 40)
    for t in types:
        print(f"{t.slug:<12} {t.name}")
    print(f"\n{len(types)} event types")
    return 0


def _cmd_add_city(args: argparse.Namespace) -> int:
    try:
        city = add_city(
            name=args.name,
            country=args.country,
            country_code=args.country_code,
            timezone=args.timezone,
            latitude=args.lat,
            longitude=args.lon,
            slug=args.slug,
        )
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(f"added city '{city.slug}' ({city.name}, {city.country})")
    print(f"asset folder: assets/{city.default_image and city.default_image.rsplit('/', 1)[0]}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="events-gen", description="Events-Gen registry CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("list-cities", help="List all configured cities").set_defaults(
        func=_cmd_list_cities
    )
    sub.add_parser("list-types", help="List all event types").set_defaults(func=_cmd_list_types)

    add = sub.add_parser("add-city", help="Add a new city to the registry")
    add.add_argument("--name", required=True)
    add.add_argument("--country", required=True)
    add.add_argument("--country-code", required=True, help="ISO 3166-1 alpha-2, e.g. FR")
    add.add_argument("--timezone", required=True, help="IANA tz, e.g. Europe/Paris")
    add.add_argument("--lat", type=float, required=True)
    add.add_argument("--lon", type=float, required=True)
    add.add_argument("--slug", default=None, help="Optional; derived from name if omitted")
    add.set_defaults(func=_cmd_add_city)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
