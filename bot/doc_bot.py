#!/usr/bin/env python3
import argparse
import json
import os
from pathlib import Path

from bot.parser import extract_env_params, extract_krknctl_params, build_skip_list
from bot.descriptions import resolve_descriptions
from bot.emitter import emit_data_file, load_descriptions


# Descriptions for new params are written by the gh-aw agent, so extraction stays
# deterministic and leaves them blank here.
def _no_descriptions(scenario, names):
    return {}


def _krknctl_desc_map(scn):
    """Param name -> maintainer-written description from krknctl-input.json, used
    to fill env.sh params that carry no description of their own."""
    f = scn / "krknctl-input.json"
    if not f.exists():
        return {}
    return {r.name: r.description for r in extract_krknctl_params(f) if r.description}


def _emit_one(scenario, source, records, website_root, source_ref):
    out = website_root / "data" / "params" / scenario / f"{source}.yaml"
    existing = load_descriptions(out)
    descs, _ = resolve_descriptions(scenario, records, existing, _no_descriptions)
    emit_data_file(website_root, scenario, source, records, descs, source_ref)


def run(scenario, krkn_hub_root, website_root, source_ref="HEAD"):
    krkn_hub_root, website_root = Path(krkn_hub_root), Path(website_root)
    scn = krkn_hub_root / scenario
    if not scn.exists():
        raise ValueError(f"Scenario directory not found: {scn}")
    skip = build_skip_list(website_root / "content/en/docs/scenarios/all-scenario-env.md")

    if (scn / "env.sh").exists():
        recs = [r for r in extract_env_params(scn / "env.sh") if r.name not in skip]
        if recs:
            kdesc = _krknctl_desc_map(scn)
            for r in recs:
                if not r.description and r.name in kdesc:
                    r.description = kdesc[r.name]
            _emit_one(scenario, "krkn-hub", recs, website_root, source_ref)
    if (scn / "krknctl-input.json").exists():
        recs = [r for r in extract_krknctl_params(scn / "krknctl-input.json") if r.name not in skip]
        if recs:
            _emit_one(scenario, "krknctl", recs, website_root, source_ref)


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
    scenario = args.scenario
    if not scenario and args.payload:
        scenario = json.loads(args.payload)["scenario"]
    if not scenario:
        p.error("a scenario is required (via --scenario or payload)")

    run(scenario, krkn_hub_root, website_root)
    if args.scaffold:
        from bot.scaffold import scaffold_scenario
        scaffold_scenario(scenario, website_root)


if __name__ == "__main__":
    main()
