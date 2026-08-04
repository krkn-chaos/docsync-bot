#!/usr/bin/env python3
"""Generate the two global parameter pages from their sources.

krknctl globals come from krkn/containers/krknctl-input.json, which carries a
"group" field and is displayed by CLI flag name. krkn-hub globals come from
krkn-hub/env.sh, which has no grouping of its own: it borrows one by joining each
export name against the krknctl "variable" field. Exports that do not join land
in a single "other" group.

Section headings and their order live in the website page, not here.
"""
import argparse
from collections import defaultdict
from dataclasses import replace
from pathlib import Path

from bot.parser import extract_env_params, extract_krknctl_params
from bot.emitter import emit_data_file, load_descriptions
from bot.descriptions import resolve_descriptions

GLOBAL_SCENARIO = "globals"
OTHER_GROUP = "other"
_KRKNCTL_REL = "containers/krknctl-input.json"


def build_groups(krkn_hub_root, krkn_root):
    """(krknctl_records, env_records), both with .group populated.
    The krknctl page renders CLI flags, so those records swap in the flag as the
    name. env records keep the variable name and borrow the group, and a
    description, from the matching krknctl entry when they have none."""
    records = extract_krknctl_params(Path(krkn_root) / _KRKNCTL_REL)
    by_var = {r.name: r for r in records}
    # An entry with no flag falls back to its variable name rather than vanishing.
    ctl = [replace(r, name=r.flag) if r.flag else r for r in records]

    env_path = Path(krkn_hub_root) / "env.sh"
    env = extract_env_params(env_path) if env_path.exists() else []
    for r in env:
        match = by_var.get(r.name)
        r.group = match.group if match and match.group else OTHER_GROUP
        # An inline comment in env.sh is krkn-hub's own wording, so it wins.
        if not r.description and match and match.description:
            r.description = match.description
            r.description_source = "krknctl"
    return ctl, env


def _by_group(records):
    out = defaultdict(list)
    for r in records:
        out[r.group or OTHER_GROUP].append(r)
    return out


def _no_descriptions(scenario, names):
    """Globals take their wording from the sources or from the existing file, and
    the gh-aw agent fills any residue. Same as the per-scenario path."""
    return {}


def emit(website_root, krkn_hub_root, krkn_root, source_ref="HEAD"):
    """Write data/params/globals/<source>.yaml, one file per source. Returns the
    paths written. Every param carries its group and the page's shortcode filters
    on it, so a new upstream group costs no new file."""
    ctl, env = build_groups(krkn_hub_root, krkn_root)
    written = []
    for source, records in (("krknctl", ctl), ("krkn-hub", env)):
        # Group order is stable so regenerating twice is byte identical.
        ordered = [r for _, rs in sorted(_by_group(records).items()) for r in rs]
        existing = load_descriptions(
            Path(website_root) / "data/params" / GLOBAL_SCENARIO / f"{source}.yaml")
        descs, _ = resolve_descriptions(GLOBAL_SCENARIO, ordered, existing, _no_descriptions)
        written.append(
            emit_data_file(website_root, GLOBAL_SCENARIO, source, ordered, descs, source_ref))
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate global parameter data files")
    ap.add_argument("--krkn-hub", required=True, help="Path to the krkn-hub repo root")
    ap.add_argument("--krkn", required=True, help="Path to the krkn repo root")
    ap.add_argument("--website", default=".", help="Path to the website repo root")
    ap.add_argument("--source-ref", default="HEAD")
    args = ap.parse_args()
    for path in emit(args.website, args.krkn_hub, args.krkn, args.source_ref):
        print(path)


if __name__ == "__main__":
    main()
