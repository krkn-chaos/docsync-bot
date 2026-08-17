#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

from bot.parser import (extract_env_params, extract_krknctl_params,
                        build_skip_list, is_global, require_sources)
from bot.describe import describe_fn
from bot.descriptions import resolve_descriptions
from bot.emitter import emit_data_file, load_previous
from bot.report import write_report




def _krknctl_records(scn):
    """Param name -> krknctl record, to fill env.sh params that carry no
    description or type. env.sh has no type information at all."""
    f = scn / "krknctl-input.json"
    if not f.exists():
        return {}
    return {r.name: r for r in extract_krknctl_params(f)}


def _published(website_root, scenario, source):
    """description and type cells from the table the shortcode is about to
    replace. Page directory names diverge from scenario names, hence find_tab."""
    from bot.scaffold import find_tab, published_cell, published_table
    tab = find_tab(website_root, scenario, source)
    if tab is None:
        return {}, {}
    rows = published_table(tab.read_text(encoding="utf-8"))

    def col(c):
        return {k: published_cell(rows, k, c) for k in rows
                if published_cell(rows, k, c)}
    return col("description"), col("type")


def _emit_one(scenario, source, records, website_root, source_ref, scn, memo):
    out = website_root / "data" / "params" / scenario / f"{source}.yaml"
    prev = load_previous(out)
    pub_desc, pub_type = _published(website_root, scenario, source)
    for r in records:
        if r.type is None:
            # The krknctl page lists --action while the record is keyed ACTION.
            r.type = prev.get(r.name, {}).get("type") or pub_type.get(r.flag or r.name)
        if not r.description_source:
            r.description_source = prev.get(r.name, {}).get("description_source")
    published = {r.name: pub_desc[r.flag or r.name] for r in records
                 if (r.flag or r.name) in pub_desc}
    # A borrow is re-derived every run so a curated page row can overtake it.
    existing = {n: p.get("description", "") for n, p in prev.items()
                if p.get("description_source") != "krknctl"}
    reasons = {}
    descs, gaps = resolve_descriptions(scenario, records, existing,
                                       describe_fn(scn, records, reasons, memo),
                                       published=published)
    emit_data_file(website_root, scenario, source, records, descs, source_ref)
    # A rejection reason beats "nothing described it": the two need opposite fixes.
    gaps = [(n, f, reasons.get(n, t) if f == "" else t) for n, f, t in gaps]
    # A published row no source produces is a whole row dropped, not a cell.
    ids = {r.flag or r.name for r in records}
    orphans = [(scenario, source, k, "orphan", "") for k in pub_desc if k not in ids]
    return [(scenario, source) + g for g in gaps] + orphans


def run(scenario, krkn_hub_root, website_root, krkn_root: str | Path = "krkn",
        source_ref="HEAD"):
    krkn_hub_root, website_root = Path(krkn_hub_root), Path(website_root)
    scn = krkn_hub_root / scenario
    if not scn.exists():
        raise ValueError(f"Scenario directory not found: {scn}")
    skip = build_skip_list(krkn_hub_root, krkn_root)
    # Shared across both sources: a param on both tabs gets one description.
    gaps, memo = [], {}

    env_comments = {}
    if (scn / "env.sh").exists():
        recs = [r for r in extract_env_params(scn / "env.sh") if not is_global(r, skip)]
        if recs:
            # Only the inline comments: what env.sh itself says, before this tab
            # resolves anything. The other tab borrows these below.
            env_comments = {r.name: r.description for r in recs if r.description}
            kctl = _krknctl_records(scn)
            for r in recs:
                match = kctl.get(r.name)
                if match is None:
                    continue
                if not r.description and match.description:
                    r.borrowed_description = match.description
                if r.type is None:
                    r.type = match.type
            gaps += _emit_one(scenario, "krkn-hub", recs, website_root, source_ref, scn, memo)
    if (scn / "krknctl-input.json").exists():
        recs = [r for r in extract_krknctl_params(scn / "krknctl-input.json")
                if not is_global(r, skip)]
        if recs:
            # Symmetric with the borrow above. Without it a param described only
            # by an env.sh comment renders on one tab and blank on the other.
            for r in recs:
                if not r.description and env_comments.get(r.name):
                    r.borrowed_description = env_comments[r.name]
            gaps += _emit_one(scenario, "krknctl", recs, website_root, source_ref, scn, memo)
    return gaps


def main():
    p = argparse.ArgumentParser()
    p.add_argument("payload", nargs="?", help="JSON payload from repository_dispatch")
    p.add_argument("--scenario", help="Scenario name")
    p.add_argument("--format", choices=["data"], default="data")
    p.add_argument("--scaffold", action="store_true",
                   help="Also inject the shortcode into the tab file")
    args = p.parse_args()

    website_root = Path(os.environ.get("WEBSITE_ROOT", "."))
    krkn_hub_root = Path(os.environ.get("KRKN_HUB_PATH", "krkn-hub"))
    krkn_root = Path(os.environ.get("KRKN_PATH", "krkn"))
    scenario = args.scenario
    if not scenario and args.payload:
        scenario = json.loads(args.payload)["scenario"]
    if not scenario:
        p.error("a scenario is required (via --scenario or payload)")

    require_sources(krkn_hub_root, krkn_root)
    gaps = run(scenario, krkn_hub_root, website_root, krkn_root)
    write_report(gaps)
    if args.scaffold:
        from bot.scaffold import scaffold_scenario
        scaffold_scenario(scenario, website_root)


if __name__ == "__main__":
    main()
