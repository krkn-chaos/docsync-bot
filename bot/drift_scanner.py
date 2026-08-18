#!/usr/bin/env python3
"""Report-only parameter drift scanner for the krkn-hub and krknctl sources.

Compares each documented scenario's source files against the committed
data/params table and reports a missing table, or missing / stale / extra params,
one finding per source so it can link the exact file. It writes nothing: the
report is a rolling issue, fixed by commenting /fix <scenario> on it.
"""
import argparse
import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import yaml

from bot.parser import (extract_env_params, extract_krknctl_params,
                        build_skip_list, is_global, require_sources)
from bot.targets import OPERATOR

# Emoji, not $\color{red}$: these have to render in a collapsed <summary>, in a
# notification email and on mobile, and none of those run a math renderer.
_HUMAN = "🔴 **Maintainer needed:**"
_REVIEW = "⚠️ **Review first:**"

_MARKER_RE = re.compile(r'<krkn-hub-scenario\s+id="([^"]+)"')
_SOURCES = (("krkn-hub", "env.sh"), ("krknctl", "krknctl-input.json"))
_DEFAULT_HUB_URL = "https://github.com/krkn-chaos/krkn-hub/blob/main"
_KRKN_URL = "https://github.com/krkn-chaos/krkn/blob/main"


@dataclass
class Finding:
    scenario: str
    source: str            # "krkn-hub" | "krknctl" | a CRD section | "page"
    # "missing-table" | "missing" | "stale" | "extra" | "missing-link" | "unlinked"
    # Only "unlinked" needs a person; "missing-link" is a link /fix does add.
    kind: str
    param: str | None = None
    # These two are read per kind, as they already are for stale and missing-table.
    old: str | None = None    # on "unlinked", the fix for that specific blocker
    new: str | None = None    # on "unlinked", why no /fix can add the link
    source_file: str = ""  # full krkn-hub URL
    table_file: str = ""   # website-relative path
    # The /fix target when it is not the scenario: a CRD plural groups the report
    # but is not something bot.doc_bot could regenerate.
    target: str | None = None


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
    elif f.kind == "missing-link":
        return (f"nothing links to this reference yet. `/fix operator` adds the "
                f"crd-ref call. page: {f.table_file}")
    elif f.kind == "unlinked":
        # The checkbox already carries the reason, so this line carries the fix.
        # Which of the three it is decides the fix, so it is never generic.
        return f"{f.old}. page: {f.table_file}"
    else:
        body = f"{f.source}: {f.kind}"
    return f"{body}. source: {f.source_file}, table: {f.table_file}"


def _scenario_summary(fs) -> str:
    """The single checkbox label for a scenario, since /fix regenerates every
    source at once. Ends at one of three honesty levels: silent when /fix just
    does it, REVIEW when /fix would delete a documented row, HUMAN when /fix
    provably cannot act. Understating the bot is as wrong as overstating it."""
    extras = [f for f in fs if f.kind == "extra"]
    unlinked = [f for f in fs if f.kind == "unlinked"]
    kinds = {f.kind for f in fs}
    if kinds == {"unlinked"}:
        return f"reference page exists but nothing links to it. {_HUMAN} {fs[0].new}"
    if kinds <= {"missing-table", "missing-link"}:
        tables = [f for f in fs if f.kind == "missing-table"]
        n = sum(len(f.new.split(", ")) for f in tables if f.new)
        if len(tables) > 3:
            what = f"{len(tables)} tables missing, {n} params"
        else:
            what = f"no table yet for {', '.join(sorted(f.source for f in tables))}"
    else:
        # Counted apart: /fix regenerates tables, and it cannot add this link.
        n = sum(1 for f in fs if f.kind != "unlinked")
        what = f"{n} drift item{'s' if n != 1 else ''}"

    if unlinked:
        return f"{what}, and one link `/fix` cannot add. {_HUMAN} {unlinked[0].new}"
    if extras:
        p = f"{len(extras)} param{'s' if len(extras) != 1 else ''}"
        return f"{what}. {_REVIEW} {p} would be removed"
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


_CRD_REF_RE = re.compile(r'crd-ref\s+crd="([^"]+)"')
_OPERATOR_URL = "https://github.com/krkn-chaos/krkn-operator/blob/main"


def _linked_crds(website_root) -> set[str]:
    """Plurals a hand-written operator page points at with a crd-ref call. The
    reference pages themselves are skipped: they are the link target.

    A call anywhere counts, including on a page that does not describe that kind.
    Judging whether a page is the right home is editorial, and link_pages still
    writes the mapped page, so a misplaced call costs a stray link, not a broken
    one. Documented in the guides as a known boundary."""
    from bot.operator import PAGES_ROOT
    root = Path(website_root) / PAGES_ROOT
    if not root.exists():
        return set()
    return {c for p in root.rglob("*.md") if "api-reference" not in p.parts
            for c in _CRD_REF_RE.findall(p.read_text(encoding="utf-8"))}


def operator_findings(operator_root, website_root, operator_url=_OPERATOR_URL):
    """CRDs against the committed api-reference tables, plus a reference page
    nothing links to. Writes nothing, like the rest of the scan."""
    from bot.crd_parser import crd_columns, crd_fields, crd_meta, load_crd
    from bot.operator import CRD_GLOB, SECTION, SOURCES, link_blocker

    website_root = Path(website_root)
    linked, findings = _linked_crds(website_root), []
    for path in sorted(Path(operator_root).glob(CRD_GLOB)):
        doc = load_crd(path)
        plural = crd_meta(doc)["plural"]
        spec, status = crd_fields(doc, "spec"), crd_fields(doc, "status")
        by = {"spec": {r.name: r for r in spec}, "status": {r.name: r for r in status}}
        records = {"spec": spec, "status": status, "columns": crd_columns(doc, by)}
        source_file = f"{operator_url}/config/crd/bases/{path.name}"
        for source in SOURCES:
            if not records[source]:
                continue
            table_file = f"data/params/{plural}/{source}.yaml"
            table = _table_params(website_root / table_file)
            src = {r.name: (None if r.default is None else str(r.default))
                   for r in records[source]}
            if table is None:
                findings.append(Finding(plural, source, "missing-table",
                    new=", ".join(sorted(src)), source_file=source_file,
                    table_file=table_file))
                continue
            for name, default in sorted(src.items()):
                if name not in table:
                    findings.append(Finding(plural, source, "missing", name,
                        new=default, source_file=source_file, table_file=table_file))
                elif table[name] != default:
                    findings.append(Finding(plural, source, "stale", name,
                        old=table[name], new=default, source_file=source_file,
                        table_file=table_file))
            for name in sorted(table):
                if name not in src:
                    findings.append(Finding(plural, source, "extra", name,
                        old=table[name], source_file=source_file,
                        table_file=table_file))
        # Two different things, and conflating them told maintainers to hand-edit
        # Python for a link the bot adds itself. Ask what link_pages will do, not
        # merely whether a link exists today.
        if plural not in linked:
            reason, remedy = link_blocker(website_root, plural) or (None, None)
            findings.append(Finding(plural, "page",
                "unlinked" if reason else "missing-link", new=reason, old=remedy,
                source_file=source_file, table_file=f"{SECTION}/{plural}.md"))
    # Set once so a finding kind added later cannot forget it.
    for f in findings:
        f.target = OPERATOR
    return findings


# Fixed order, so the issue body only changes when the findings do.
_GROUP_ORDER = ("krkn-hub scenarios", "Global parameters", "krkn-operator CRDs")


def _group_of(fs) -> str:
    """Which source a scenario's findings came from, for the collapsed sections."""
    if any(f.target == OPERATOR for f in fs):
        return "krkn-operator CRDs"
    return "Global parameters" if fs[0].scenario == "globals" else "krkn-hub scenarios"


def format_report(findings, prev_body="") -> str:
    """One checkbox per scenario (the unit /fix acts on), the per-source findings as
    detail bullets, and the scenarios collapsed under the source they came from:
    every source drifting at once is otherwise hundreds of lines to scroll.
    Preserves a ticked checkbox whose label is unchanged. Emits no em dashes."""
    if not findings:
        return "### Docs drift report\n\nNo drift found.\n"
    ticked = _ticked_scenarios(prev_body)
    by_scn = defaultdict(list)
    for f in findings:
        by_scn[f.scenario].append(f)
    grouped = defaultdict(list)
    for scn, fs in by_scn.items():
        grouped[_group_of(fs)].append(scn)
    n = len(by_scn)
    lines = ["### Docs drift report", "",
             f"Drift in {n} place{'s' if n != 1 else ''}, across "
             f"{len(grouped)} source{'s' if len(grouped) != 1 else ''}. "
             "Expand a source, then tick a box when handled or run the `/fix` it names.", ""]
    for group in _GROUP_ORDER:
        scns = sorted(grouped.get(group, ()))
        if not scns:
            continue
        # A marker inside a collapsed group is invisible, which is the whole
        # point of having collapsed it, so the count rides on the header.
        k = sum(1 for s in scns if any(f.kind == "unlinked" for f in by_scn[s]))
        need = f" · 🔴 {k} need{'s' if k == 1 else ''} a maintainer" if k else ""
        # Blank lines around the body, or GitHub renders the markdown as literal text.
        lines += [f"<details><summary><b>{group}</b> ({len(scns)}){need}</summary>", ""]
        for scn in scns:
            fs = by_scn[scn]
            # A scenario of only unlinked findings gets guidance, not a command
            # that would silently do nothing.
            target = next((f.target or f.scenario
                           for f in fs if f.kind != "unlinked"), None)
            label = _scenario_summary(fs)
            if target:
                label += f". Fix with `/fix {target}`"
            # A tick means "I handled what this said". New drift changes the label,
            # so it comes back unticked rather than hiding behind the old tick.
            box = "x" if ticked.get(scn) == label else " "
            lines.append(f"<!-- drift:{scn} -->")
            lines.append(f"#### {scn}")
            lines.append(f"- [{box}] {label}")
            lines.extend(_detail_block(fs))
            lines.append("")
        lines += ["</details>", ""]
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description="Scan krkn-hub for documentation drift")
    ap.add_argument("--krkn-hub", required=True, help="Path to krkn-hub repo root")
    ap.add_argument("--website", required=True, help="Path to website repo root")
    ap.add_argument("--repo", help="owner/repo to open the rolling drift issue on")
    ap.add_argument("--hub-url", default=_DEFAULT_HUB_URL, help="krkn-hub blob base URL")
    ap.add_argument("--krkn", default="krkn", help="Path to krkn repo root (global params)")
    ap.add_argument("--krkn-url", default=_KRKN_URL, help="krkn blob base URL")
    ap.add_argument("--operator", help="Path to krkn-operator repo root (CRD source)")
    ap.add_argument("--operator-url", default=_OPERATOR_URL, help="krkn-operator blob base URL")
    args = ap.parse_args()

    require_sources(args.krkn_hub, args.krkn)
    findings = scan(args.krkn_hub, args.website, hub_url=args.hub_url, krkn_root=args.krkn)
    findings += global_findings(args.krkn_hub, args.krkn, args.website,
                                hub_url=args.hub_url, krkn_url=args.krkn_url)
    # Optional: the scan still runs without a krkn-operator checkout.
    if args.operator:
        findings += operator_findings(args.operator, args.website, args.operator_url)

    if not args.repo:
        # The report carries emoji markers, and a Windows console defaults to
        # cp1252, which cannot encode them. CI is UTF-8; a maintainer's laptop
        # is not, and a preview run should not die on its own output.
        sys.stdout.reconfigure(encoding="utf-8")
        print(format_report(findings))
        return

    from bot.github_client import get_open_drift_body, create_or_update_drift_issue
    prev = get_open_drift_body(args.repo)
    body = format_report(findings, prev_body=prev)
    url = create_or_update_drift_issue(args.repo, "Docs drift report", body)
    print(f"Drift issue: {url}")


if __name__ == "__main__":
    main()
