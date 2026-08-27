#!/usr/bin/env python3
"""Generate the two global parameter pages from their sources.

krknctl globals come from krknctl-input.json, carry a "group", and display by
CLI flag. krkn-hub globals come from env.sh, which has no grouping: it joins each
export against the krknctl "variable" field and unmatched ones land in "other".
Section headings and their order live in the website page, not here.
"""
import argparse
from collections import Counter, defaultdict
from dataclasses import replace
from pathlib import Path

from bot.parser import extract_env_params, extract_krknctl_params, require_sources
from bot.emitter import emit_data_file, load_previous
from bot.describe import describe_fn
from bot.descriptions import attach_reasons, resolve_descriptions
from bot.report import TABLE, malformed_descriptions, write_report

GLOBAL_SCENARIO = "globals"
OTHER_GROUP = "other"
_KRKNCTL_REL = "containers/krknctl-input.json"


def _page_groups(website_root):
    """{param: section slug} for the krkn-hub page: its sections, then the groups
    the last run recorded. A converted section has no rows left to read, so
    without the data file every param would collapse into "other" on run two."""
    if website_root is None:
        return {}
    from bot.scaffold import page_section_groups
    page = Path(website_root) / dict(_PAGES)["krkn-hub"]
    out = {n: p["group"] for n, p in load_previous(
        Path(website_root) / "data/params" / GLOBAL_SCENARIO / "krkn-hub.yaml").items()
        if p.get("group")}
    if page.exists():
        out.update(page_section_groups(page.read_text(encoding="utf-8")))
    return out


def _group_bridge(page_groups, by_var):
    """krknctl group -> page section slug, learned from params already placed.
    Without it a new kubevirt param opens a "Kubevirt" section beside the
    "Virt Checks" one holding its eight siblings."""
    votes = defaultdict(Counter)
    for name, slug in page_groups.items():
        match = by_var.get(name)
        if match and match.group:
            votes[match.group][slug] += 1
    return {g: min(c.items(), key=lambda kv: (-kv[1], kv[0]))[0] for g, c in votes.items()}


def build_groups(krkn_hub_root, krkn_root, website_root=None):
    """(krknctl_records, env_records), both with .group populated.
    The krknctl page renders CLI flags, so those records swap the flag into name.
    env records keep the variable name and borrow group, and a description, from
    the matching krknctl entry when they have none."""
    records = extract_krknctl_params(Path(krkn_root) / _KRKNCTL_REL)
    by_var = {r.name: r for r in records}
    # No flag falls back to the variable name, no group joins "other". A row
    # without a group matches no filtered call, so it would drop off the page.
    ctl = [replace(r, name=r.flag or r.name, group=r.group or OTHER_GROUP)
           for r in records]

    env_path = Path(krkn_hub_root) / "env.sh"
    env = extract_env_params(env_path) if env_path.exists() else []
    page = _page_groups(website_root)
    bridge = _group_bridge(page, by_var)
    for r in env:
        match = by_var.get(r.name)
        # The page's own sections group env.sh, which has no grouping. krknctl's
        # groups describe the other page, so they only cover a param new here.
        ctl_group = match.group if match else None
        r.group = (page.get(r.name) or bridge.get(ctl_group) or ctl_group
                   or OTHER_GROUP)
        # An inline comment in env.sh is krkn-hub's own wording, so it wins.
        if not r.description and match and match.description:
            r.borrowed_description = match.description
    return ctl, env


def _by_group(records):
    out = defaultdict(list)
    for r in records:
        out[r.group or OTHER_GROUP].append(r)
    return out


def _published_globals(website_root):
    """{source: {param: description}} from the two global pages. Each carries
    nine tables, one per group, which published_table already handles."""
    from bot.scaffold import published_cell, published_table
    out = {}
    for source, rel in _PAGES:
        page = Path(website_root) / rel
        rows = published_table(page.read_text(encoding="utf-8")) if page.exists() else {}
        out[source] = {k: published_cell(rows, k, "description") for k in rows
                       if published_cell(rows, k, "description")}
    return out


def emit(website_root, krkn_hub_root, krkn_root, source_ref="HEAD"):
    """Write data/params/globals/<source>.yaml, one file per source. Returns
    (paths written, gaps). Every param carries its group and the page's shortcode
    filters on it, so a new upstream group costs no new file."""
    ctl, env = build_groups(krkn_hub_root, krkn_root, website_root)
    published = _published_globals(website_root)
    written, gaps = [], []
    for source, records in (("krknctl", ctl), ("krkn-hub", env)):
        # Group order is stable so regenerating twice is byte identical.
        ordered = [r for _, rs in sorted(_by_group(records).items()) for r in rs]
        prev = load_previous(
            Path(website_root) / "data/params" / GLOBAL_SCENARIO / f"{source}.yaml")
        # A borrow is re-derived every run, so a curated page row can still
        # overtake it. Kept, it would freeze krknctl's wording forever.
        existing = {n: p.get("description", "") for n, p in prev.items()
                    if p.get("description_source") != "krknctl"}
        # The published table is read once, by the run that replaces it. Without
        # this the provenance marker vanishes on the next run.
        for r in ordered:
            if not r.description_source:
                r.description_source = prev.get(r.name, {}).get("description_source")
        reasons = {}
        descs, g = resolve_descriptions(
            GLOBAL_SCENARIO, ordered, existing,
            describe_fn(krkn_hub_root, ordered, reasons), published=published[source])
        g = attach_reasons(g, reasons)
        gaps += [(GLOBAL_SCENARIO, source) + x for x in g]
        # A published row no source produces is a whole row dropped. The
        # per-scenario path reports these; without this the globals pages did not.
        names = {r.name for r in ordered}
        gaps += [(GLOBAL_SCENARIO, source, k, "orphan", "", "")
                 for k in published[source] if k not in names]
        gaps += [(GLOBAL_SCENARIO, source) + x
                 for x in malformed_descriptions(descs)]
        written.append(
            emit_data_file(website_root, GLOBAL_SCENARIO, source, ordered, descs, source_ref))
    return written, gaps


_PAGES = (
    ("krknctl", "content/en/docs/scenarios/all-scenario-env-krknctl.md"),
    ("krkn-hub", "content/en/docs/scenarios/all-scenario-env.md"),
)


def scaffold(website_root, krkn_hub_root, krkn_root):
    """Replace the tables on the two global pages with group-filtered param-table
    calls, one report line per table. The group comes from each table's own rows,
    so no marker or heading map is needed. A table spanning groups, or whose group
    another table on the page claims, is left alone rather than guessed at."""
    from bot.scaffold import inject_global_shortcodes

    # Same website_root as emit(): the data file's groups and the injected
    # calls must agree, or a section filters on a group nothing carries.
    ctl, env = build_groups(krkn_hub_root, krkn_root, website_root)
    by_source = {"krknctl": ctl, "krkn-hub": env}
    report = []
    for source, rel in _PAGES:
        page = Path(website_root) / rel
        if not page.exists():
            continue
        text = page.read_text(encoding="utf-8")
        out, lines = inject_global_shortcodes(
            text, source, {r.name: r.group for r in by_source[source]})
        if out != text:
            page.write_text(out, encoding="utf-8")
        report += [f"{Path(rel).name}: {line}" for line in lines]
    return report


def _table_gap(line):
    """A scaffold line, "<page>: <what happened>", as a gap row. Split once: a
    page name has no ": " in it, but a reason can."""
    page, _, what = line.partition(": ")
    return ("globals", "", page, TABLE, what, "")


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate global parameter data files")
    ap.add_argument("--krkn-hub", required=True, help="Path to the krkn-hub repo root")
    ap.add_argument("--krkn", required=True, help="Path to the krkn repo root")
    ap.add_argument("--website", default=".", help="Path to the website repo root")
    ap.add_argument("--source-ref", default="HEAD")
    ap.add_argument("--scaffold", action="store_true",
                    help="Also replace the tables on the two global pages with "
                         "param-table calls")
    args = ap.parse_args()
    require_sources(args.krkn_hub, args.krkn)
    written, gaps = emit(args.website, args.krkn_hub, args.krkn, args.source_ref)
    for path in written:
        print(path)
    write_report(gaps)
    if args.scaffold:
        lines = scaffold(args.website, args.krkn_hub, args.krkn)
        for line in lines:
            print(line)
        # Stdout only reaches the Actions log. A table the bot left alone is
        # still on the page, so the reason belongs in the commit message.
        write_report([_table_gap(line) for line in lines])


if __name__ == "__main__":
    main()
