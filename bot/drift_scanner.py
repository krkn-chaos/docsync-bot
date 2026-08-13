#!/usr/bin/env python3
"""Report-only parameter drift scanner for the krkn-hub and krknctl sources.

Compares each documented scenario's source files against the committed
data/params table and reports a missing table, or missing / stale / extra params,
one finding per source so it can link the exact file. It writes nothing: the
report is a rolling issue, fixed by commenting /fix <scenario> on it.
"""
import argparse
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from bot.parser import (extract_env_params, extract_krknctl_params,
                        build_skip_list, is_global, require_sources)

_MARKER_RE = re.compile(r'<krkn-hub-scenario\s+id="([^"]+)"')
_SOURCES = (("krkn-hub", "env.sh"), ("krknctl", "krknctl-input.json"))
_DEFAULT_HUB_URL = "https://github.com/krkn-chaos/krkn-hub/blob/main"
_KRKN_URL = "https://github.com/krkn-chaos/krkn/blob/main"


@dataclass
class Finding:
    scenario: str
    source: str            # "krkn-hub" | "krknctl"
    kind: str              # "missing-table" | "missing" | "stale" | "extra"
    param: str | None = None
    old: str | None = None
    new: str | None = None
    source_file: str = ""  # full krkn-hub URL
    table_file: str = ""   # website-relative path


def find_scenarios(website_root) -> list[str]:
    """Documented scenario ids from the <krkn-hub-scenario id="..."> markers."""
    root = Path(website_root) / "content/en/docs/scenarios"
    ids = set()
    for p in root.rglob("*.md"):
        ids |= set(_MARKER_RE.findall(p.read_text(encoding="utf-8")))
    return sorted(ids)


def _source_params(scn_dir: Path, source: str, filename: str, skip: dict):
    """name -> ParamRecord for one source, or None if that source is absent."""
    f = scn_dir / filename
    if not f.exists():
        return None
    recs = extract_env_params(f) if source == "krkn-hub" else extract_krknctl_params(f)
    return {r.name: r for r in recs if not is_global(r, skip)}


def _table_rows(table_path: Path):
    """Raw param rows from a committed data file, or None if it does not exist.
    Globals keep every group in one file, so callers slice these by row["group"]."""
    if not table_path.exists():
        return None
    data = yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
    return data.get("params", [])


def _table_params(table_path: Path):
    """name -> default (str|None) from a committed data/params yaml, or None if the
    file does not exist."""
    if not table_path.exists():
        return None
    data = yaml.safe_load(table_path.read_text(encoding="utf-8")) or {}
    out = {}
    for p in data.get("params", []):
        d = p.get("default")
        out[p["name"]] = None if d is None else str(d)
    return out


def scenario_findings(scenario, krkn_hub_root, website_root, hub_url=_DEFAULT_HUB_URL,
                      krkn_root="krkn"):
    krkn_hub_root, website_root = Path(krkn_hub_root), Path(website_root)
    scn_dir = krkn_hub_root / scenario
    skip = build_skip_list(krkn_hub_root, krkn_root)
    findings = []
    for source, filename in _SOURCES:
        src = _source_params(scn_dir, source, filename, skip)
        if src is None:
            continue
        source_file = f"{hub_url}/{scenario}/{filename}"
        table_file = f"data/params/{scenario}/{source}.yaml"
        table = _table_params(website_root / table_file)
        if table is None:
            findings.append(Finding(scenario, source, "missing-table",
                new=", ".join(sorted(src)), source_file=source_file, table_file=table_file))
            continue
        for name, rec in sorted(src.items()):
            sdef = None if rec.default is None else str(rec.default)
            if name not in table:
                findings.append(Finding(scenario, source, "missing", name,
                    new=sdef, source_file=source_file, table_file=table_file))
            elif table[name] != sdef:
                findings.append(Finding(scenario, source, "stale", name,
                    old=table[name], new=sdef, source_file=source_file, table_file=table_file))
        for name in sorted(table):
            if name not in src:
                findings.append(Finding(scenario, source, "extra", name,
                    old=table[name], source_file=source_file, table_file=table_file))
    return findings


def global_findings(krkn_hub_root, krkn_root, website_root,
                    hub_url=_DEFAULT_HUB_URL, krkn_url=_KRKN_URL):
    """Drift in the two global parameter pages, reported under the scenario id
    "globals" so one `/fix globals` covers every group. Each source has a single
    table holding every group, so it is read once and sliced by each row's
    group."""
    from bot.globals import GLOBAL_SCENARIO, OTHER_GROUP, build_groups

    ctl, env = build_groups(krkn_hub_root, krkn_root)
    findings = []
    for prefix, records, source_file in (
        ("krknctl", ctl, f"{krkn_url}/containers/krknctl-input.json"),
        ("krkn-hub", env, f"{hub_url}/env.sh"),
    ):
        by_group = defaultdict(list)
        for r in records:
            by_group[r.group or OTHER_GROUP].append(r)

        # One file per source now, with the group carried per row, so read it once
        # and slice it per group rather than opening a file per group.
        table_file = f"data/params/{GLOBAL_SCENARIO}/{prefix}.yaml"
        all_rows = _table_rows(Path(website_root) / table_file)

        for group, rs in sorted(by_group.items()):
            source = f"{prefix}-{group}"
            table = None if all_rows is None else {
                r["name"]: (None if r.get("default") is None else str(r["default"]))
                for r in all_rows if r.get("group") == group}
            src = {r.name: r for r in rs}
            if table is None:
                findings.append(Finding(GLOBAL_SCENARIO, source, "missing-table",
                    new=", ".join(sorted(src)), source_file=source_file,
                    table_file=table_file))
                continue
            for name, rec in sorted(src.items()):
                sdef = None if rec.default is None else str(rec.default)
                if name not in table:
                    findings.append(Finding(GLOBAL_SCENARIO, source, "missing", name,
                        new=sdef, source_file=source_file, table_file=table_file))
                elif table[name] != sdef:
                    findings.append(Finding(GLOBAL_SCENARIO, source, "stale", name,
                        old=table[name], new=sdef, source_file=source_file,
                        table_file=table_file))
            for name in sorted(table):
                if name not in src:
                    findings.append(Finding(GLOBAL_SCENARIO, source, "extra", name,
                        old=table[name], source_file=source_file, table_file=table_file))
    return findings


def scan(krkn_hub_root, website_root, scenarios=None, hub_url=_DEFAULT_HUB_URL,
         krkn_root="krkn"):
    if scenarios is None:
        scenarios = find_scenarios(website_root)
    findings = []
    for s in scenarios:
        if (Path(krkn_hub_root) / s).is_dir():
            findings.extend(scenario_findings(s, krkn_hub_root, website_root, hub_url,
                                              krkn_root))
    return findings


# --- issue rendering (Option A, no em dashes) -----------------------------

def _finding_detail(f: Finding) -> str:
    """One detail bullet for a single source finding, with its file link."""
    if f.kind == "missing-table":
        n = len(f.new.split(", ")) if f.new else 0
        return f"{f.source}: no table yet, will add {n} params ({f.new}). source: {f.source_file}"
    if f.kind == "missing":
        d = f" (default {f.new})" if f.new is not None else ""
        body = f"{f.source}: missing {f.param}{d}"
    elif f.kind == "stale":
        body = f"{f.source}: {f.param} default {f.old} -> {f.new}"
    elif f.kind == "extra":
        body = f"{f.source}: extra {f.param}"
    else:
        body = f"{f.source}: {f.kind}"
    return f"{body}. source: {f.source_file}, table: {f.table_file}"


def _scenario_summary(fs) -> str:
    """The single checkbox label for a scenario, since /fix regenerates every
    source at once. Ends with a confidence marker: everything but "extra" is
    derived from the source and safe to regenerate, while "extra" is the one kind
    where /fix deletes a documented row, so it needs a human."""
    extras = [f for f in fs if f.kind == "extra"]
    if {f.kind for f in fs} == {"missing-table"}:
        n = sum(len(f.new.split(", ")) for f in fs if f.new)
        if len(fs) > 3:
            what = f"{len(fs)} tables missing, {n} params"
        else:
            what = f"no table yet for {', '.join(sorted(f.source for f in fs))}"
    else:
        n = len(fs)
        what = f"{n} drift item{'s' if n != 1 else ''}"

    if extras:
        p = f"{len(extras)} param{'s' if len(extras) != 1 else ''}"
        return f"{what}. **Needs a look**: {p} would be removed"
    return f"{what}. Safe to regenerate"


def _detail_block(fs) -> list[str]:
    """Detail lines for one scenario. Past a few findings the per-source lists get
    unreadable in an issue, so they collapse into a <details> table and each source
    file is linked once instead of on every row."""
    if len(fs) <= 3:
        return [f"  - {_finding_detail(f)}" for f in fs]

    by_file = {}
    for f in fs:
        by_file.setdefault(f.source_file, []).append(f)

    lines = ["", "<details>", f"<summary>{len(fs)} findings, click to expand</summary>", ""]
    for source_file, group in sorted(by_file.items()):
        lines += [f"Source: {source_file}", "", "| Source | Params | Names |", "| --- | --- | --- |"]
        for f in sorted(group, key=lambda x: x.source):
            if f.kind == "missing-table":
                names = f.new or ""
                count = len(names.split(", ")) if names else 0
            else:
                names = f.param or ""
                count = 1
            if len(names) > 90:
                names = names[:90].rsplit(", ", 1)[0] + ", ..."
            lines.append(f"| {f.source} | {count} | {names} |")
        lines.append("")
    lines += ["</details>", ""]
    return lines


def _ticked_scenarios(prev_body: str) -> dict[str, str]:
    """Scenario id -> the label it was ticked against, for each ticked checkbox in
    the previous issue body. Keyed on the <!-- drift:scn --> marker so a tick
    applies to that scenario only, never to another with the same label."""
    ticked, cur = {}, None
    for line in prev_body.splitlines():
        m = re.match(r"<!-- drift:(\S+) -->", line)
        if m:
            cur = m.group(1)
        elif cur and line.startswith("- ["):
            if line.startswith("- [x] "):
                ticked[cur] = line[len("- [x] "):].strip()
            cur = None
    return ticked


def format_report(findings, prev_body="") -> str:
    """Render Option A, one checkbox per scenario (the unit /fix acts on) with the
    per-source findings as detail bullets. Preserves a ticked checkbox whose label
    is unchanged. Emits no em dash characters."""
    if not findings:
        return "### Docs drift report\n\nNo drift found.\n"
    ticked = _ticked_scenarios(prev_body)
    by_scn = defaultdict(list)
    for f in findings:
        by_scn[f.scenario].append(f)
    n = len(by_scn)
    lines = ["### Docs drift report", "",
             f"Drift in {n} scenario{'s' if n != 1 else ''}. "
             "Tick a box when handled, or comment `/fix <scenario>` for a draft PR.", ""]
    for scn in sorted(by_scn):
        fs = by_scn[scn]
        label = f"{_scenario_summary(fs)}. Fix with `/fix {scn}`"
        # A tick means "I handled what this said". New drift changes the label,
        # so it comes back unticked rather than hiding behind the old tick.
        box = "x" if ticked.get(scn) == label else " "
        lines.append(f"<!-- drift:{scn} -->")
        lines.append(f"#### {scn}")
        lines.append(f"- [{box}] {label}")
        lines.extend(_detail_block(fs))
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan krkn-hub for documentation drift")
    ap.add_argument("--krkn-hub", required=True, help="Path to krkn-hub repo root")
    ap.add_argument("--website", required=True, help="Path to website repo root")
    ap.add_argument("--repo", help="owner/repo to open the rolling drift issue on")
    ap.add_argument("--hub-url", default=_DEFAULT_HUB_URL, help="krkn-hub blob base URL")
    ap.add_argument("--krkn", default="krkn", help="Path to krkn repo root (global params)")
    ap.add_argument("--krkn-url", default=_KRKN_URL, help="krkn blob base URL")
    args = ap.parse_args()

    require_sources(args.krkn_hub, args.krkn)
    findings = scan(args.krkn_hub, args.website, hub_url=args.hub_url, krkn_root=args.krkn)
    findings += global_findings(args.krkn_hub, args.krkn, args.website,
                                hub_url=args.hub_url, krkn_url=args.krkn_url)

    if not args.repo:
        print(format_report(findings))
        return

    from bot.github_client import get_open_drift_body, create_or_update_drift_issue
    prev = get_open_drift_body(args.repo)
    body = format_report(findings, prev_body=prev)
    url = create_or_update_drift_issue(args.repo, "Docs drift report", body)
    print(f"Drift issue: {url}")


if __name__ == "__main__":
    main()
