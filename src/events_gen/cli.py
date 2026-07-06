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

from .models import TimeWindow
from .registry import (
    RegistryError,
    add_city,
    get_city,
    load_cities,
    load_event_types,
)


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


def _cmd_fetch(args: argparse.Namespace) -> int:
    from .sources import aggregator
    from .timewindow import compute_window

    try:
        city = get_city(args.city)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    all_types = load_event_types()
    if args.types:
        wanted = set(args.types)
        types = [t for t in all_types if t.slug in wanted]
        unknown = wanted - {t.slug for t in types}
        if unknown:
            print(f"error: unknown event type(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
    else:
        types = []  # all types

    window = compute_window(TimeWindow(args.window), city.timezone)
    events = aggregator.fetch(city, window, types, count=args.count)

    print(f"{city.name}: {args.window} window {window.start.date()} → {window.end.date()}")
    print(f"{len(events)} event(s):\n")
    for e in events:
        when = e.start.strftime("%a %d %b %H:%M")
        venue = f" @ {e.venue}" if e.venue else ""
        print(f"  [{e.source}] {when}  {e.title}{venue}")
    return 0


def _cmd_render(args: argparse.Namespace) -> int:
    from pathlib import Path

    from .content.builder import build_content
    from .render import get_format, render_video
    from .sources import aggregator
    from .timewindow import compute_window

    try:
        city = get_city(args.city)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    all_types = load_event_types()
    types = [t for t in all_types if t.slug in set(args.types)] if args.types else []

    window = compute_window(TimeWindow(args.window), city.timezone)
    events = aggregator.fetch(city, window, types, count=args.count)
    if not events:
        print("no events found", file=sys.stderr)
        return 1

    draft_id = f"cli-{city.slug}"
    content = build_content(city, events, types or all_types, args.window, draft_id=draft_id)

    fmt = get_format(args.format)
    out_path = Path(args.output) if args.output else Path(f"data/output/{draft_id}/{fmt.name}.mp4")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"rendering {fmt.name} ({fmt.width}x{fmt.height}) for {city.name}, {len(events)} events..."
    )
    result = render_video(content, events, out_path, fmt)
    print(f"done: {result} ({result.stat().st_size / 1024:.0f} KB)")
    return 0


def _cmd_generate_content(args: argparse.Namespace) -> int:
    from .content.builder import build_content
    from .sources import aggregator
    from .timewindow import compute_window

    try:
        city = get_city(args.city)
    except RegistryError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    all_types = load_event_types()
    types = [t for t in all_types if t.slug in set(args.types)] if args.types else []

    window = compute_window(TimeWindow(args.window), city.timezone)
    events = aggregator.fetch(city, window, types, count=args.count)
    if not events:
        print("no events found", file=sys.stderr)
        return 1

    content = build_content(
        city, events, types or all_types, args.window, draft_id=f"cli-{city.slug}"
    )
    print(f"TITLE:    {content.title}\n")
    print(content.caption)
    print(f"\nHASHTAGS: {' '.join(content.hashtags)}")
    print(f"\nBACKGROUND: {content.background_image_path}")
    print(f"MUSIC:      {content.music_path or '(none — silent)'}")
    return 0


def _cmd_publish(args: argparse.Namespace) -> int:
    from . import pipeline, publish
    from .models import Platform

    targets = [Platform(t) for t in args.targets]
    try:
        draft = pipeline.run(
            city_slug=args.city,
            window=TimeWindow(args.window),
            event_types=args.types,
            count=args.count,
            render_format=args.format,
            targets=targets,
            progress=lambda m: print(f"  … {m}"),
        )
    except (RegistryError, pipeline.PipelineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    mode = "DRY-RUN" if not args.live else "LIVE"
    print(f"\npublishing draft {draft.id} [{mode}] to: {', '.join(t.value for t in targets)}")
    results = publish.publish_draft(draft, targets=targets, dry_run=not args.live)
    exit_code = 0
    for r in results:
        if r.success:
            print(f"  ✅ {r.platform.value}: {r.url}")
        else:
            print(f"  ❌ {r.platform.value}: {r.error}", file=sys.stderr)
            exit_code = 1
    return exit_code


def _cmd_demo(args: argparse.Namespace) -> int:
    """End-to-end smoke: generate a draft and dry-run publish it, no keys needed."""
    from . import pipeline, publish
    from .models import Platform

    print("Events-Gen demo — full pipeline, no API keys required.\n")
    try:
        draft = pipeline.run(
            city_slug=args.city,
            window=TimeWindow(args.window),
            count=args.count,
            render_format=args.format,
            targets=[Platform.YOUTUBE, Platform.INSTAGRAM],
            progress=lambda m: print(f"  … {m}"),
        )
    except (RegistryError, pipeline.PipelineError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print("\nGenerated draft:")
    print(f"  id:     {draft.id}")
    print(f"  title:  {draft.content.title if draft.content else '(none)'}")
    print(f"  events: {len(draft.events)}")
    print(f"  video:  {draft.video_path}")

    print("\nDry-run publish (no accounts touched):")
    results = publish.publish_draft(draft, dry_run=True)
    for r in results:
        print(f"  ✅ {r.platform.value}: {r.url}")

    print("\nDemo complete. Set API keys in .env to use live sources/publishing.")
    return 0


def _cmd_schedule(args: argparse.Namespace) -> int:
    from .models import Platform, Schedule, ScheduleCadence
    from .scheduler import run_schedule
    from .settings import get_settings
    from .storage import Storage

    storage = Storage(get_settings().db_path)

    if args.action == "list":
        schedules = storage.list_schedules()
        if not schedules:
            print("no schedules configured")
            return 0
        for s in schedules:
            state = "enabled" if s.enabled else "disabled"
            pub = "auto-publish" if s.auto_publish else "review"
            print(f"{s.id[:8]}  {s.city_slug:<14} {s.cadence.value:<8} {state:<9} {pub}")
        return 0

    if args.action == "add":
        try:
            get_city(args.city)
        except RegistryError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 1
        sched = storage.save_schedule(
            Schedule(
                city_slug=args.city,
                cadence=ScheduleCadence(args.cadence),
                window=TimeWindow(args.window),
                event_types=args.types or [],
                event_count=args.count,
                targets=[Platform(t) for t in (args.targets or [])],
                auto_publish=args.auto_publish,
                enabled=True,
            )
        )
        print(f"created schedule {sched.id[:8]} for {sched.city_slug} ({sched.cadence.value})")
        return 0

    if args.action == "run":
        found = storage.get_schedule(args.id) if args.id else None
        if found is None:
            # allow matching by short id prefix
            found = next(
                (s for s in storage.list_schedules() if s.id.startswith(args.id or "")), None
            )
        if found is None:
            print(f"error: no schedule matching {args.id!r}", file=sys.stderr)
            return 1
        print(f"running schedule {found.id[:8]} for {found.city_slug}…")
        job = run_schedule(found, storage=storage)
        print(f"  {job.status.value}: {job.detail or job.error}")
        return 0 if job.status.value == "succeeded" else 1

    return 1


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

    fetch = sub.add_parser("fetch", help="Discover events for a city")
    fetch.add_argument("city", help="City slug (see list-cities)")
    fetch.add_argument(
        "--window", choices=["week", "month"], default="week", help="Time window (default: week)"
    )
    fetch.add_argument(
        "--types", nargs="*", default=None, help="Event-type slugs to filter (default: all)"
    )
    fetch.add_argument("--count", type=int, default=5, help="Max events (default: 5)")
    fetch.set_defaults(func=_cmd_fetch)

    gen = sub.add_parser("generate-content", help="Generate captions/image/music for a city")
    gen.add_argument("city", help="City slug (see list-cities)")
    gen.add_argument("--window", choices=["week", "month"], default="week")
    gen.add_argument("--types", nargs="*", default=None, help="Event-type slugs (default: all)")
    gen.add_argument("--count", type=int, default=5, help="Max events (default: 5)")
    gen.set_defaults(func=_cmd_generate_content)

    rnd = sub.add_parser("render", help="Render a video for a city's events")
    rnd.add_argument("city", help="City slug (see list-cities)")
    rnd.add_argument("--window", choices=["week", "month"], default="week")
    rnd.add_argument("--types", nargs="*", default=None, help="Event-type slugs (default: all)")
    rnd.add_argument("--count", type=int, default=5, help="Max events (default: 5)")
    rnd.add_argument(
        "--format",
        choices=["reel", "landscape"],
        default="reel",
        help="Video format (default: reel/9:16)",
    )
    rnd.add_argument(
        "--output", "-o", default=None, help="Output path (default: data/output/<id>/)"
    )
    rnd.set_defaults(func=_cmd_render)

    pub = sub.add_parser("publish", help="Generate a draft and publish it (dry-run by default)")
    pub.add_argument("city", help="City slug (see list-cities)")
    pub.add_argument("--window", choices=["week", "month"], default="week")
    pub.add_argument("--types", nargs="*", default=None, help="Event-type slugs (default: all)")
    pub.add_argument("--count", type=int, default=5, help="Max events (default: 5)")
    pub.add_argument("--format", choices=["reel", "landscape"], default="reel")
    pub.add_argument(
        "--targets",
        nargs="+",
        choices=["youtube", "instagram"],
        default=["youtube", "instagram"],
        help="Destinations (default: both)",
    )
    pub.add_argument(
        "--live",
        action="store_true",
        help="Actually publish (default is a dry-run that touches no accounts)",
    )
    pub.set_defaults(func=_cmd_publish)

    demo = sub.add_parser("demo", help="End-to-end demo: generate + dry-run publish (no keys)")
    demo.add_argument("city", nargs="?", default="new-york", help="City slug (default: new-york)")
    demo.add_argument("--window", choices=["week", "month"], default="week")
    demo.add_argument("--count", type=int, default=3, help="Max events (default: 3)")
    demo.add_argument("--format", choices=["reel", "landscape"], default="reel")
    demo.set_defaults(func=_cmd_demo)

    sched = sub.add_parser("schedule", help="Manage automation schedules (M7)")
    sched_sub = sched.add_subparsers(dest="action", required=True)

    sched_sub.add_parser("list", help="List configured schedules").set_defaults(func=_cmd_schedule)

    sadd = sched_sub.add_parser("add", help="Add a schedule for a city")
    sadd.add_argument("city", help="City slug")
    sadd.add_argument("--cadence", choices=["weekly", "monthly"], default="weekly")
    sadd.add_argument("--window", choices=["week", "month"], default="week")
    sadd.add_argument("--types", nargs="*", default=None, help="Event-type slugs (default: all)")
    sadd.add_argument("--count", type=int, default=5)
    sadd.add_argument("--targets", nargs="*", choices=["youtube", "instagram"], default=None)
    sadd.add_argument(
        "--auto-publish",
        action="store_true",
        help="Auto-publish (default: generate draft only, review required)",
    )
    sadd.set_defaults(func=_cmd_schedule)

    srun = sched_sub.add_parser("run", help="Trigger a schedule immediately")
    srun.add_argument("id", help="Schedule id (or unique prefix; see 'schedule list')")
    srun.set_defaults(func=_cmd_schedule)

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    result: int = args.func(args)
    return result


if __name__ == "__main__":
    raise SystemExit(main())
