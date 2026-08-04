import re
from collections import Counter
from pathlib import Path

_ID_RE = re.compile(r'<krkn-hub-scenario\s+id="([^"]+)"')

# Kept local rather than imported from bot.globals, which imports this module.
GLOBAL_SCENARIO = "globals"


def _is_table_separator(line):
    s = line.strip().strip("|").strip()
    return bool(s) and "-" in s and all(c in "|-: " for c in s)


def inject_shortcode(text, scenario, source):
    """Replace the first markdown parameter table with the param-table shortcode call.
    Idempotent: returns text unchanged if a param-table call is already present."""
    call = f'{{{{< param-table scenario="{scenario}" source="{source}" >}}}}'
    if "param-table" in text:
        return text
    lines = text.splitlines(keepends=True)
    sep = end = None
    for i, line in enumerate(lines):
        if sep is None and _is_table_separator(line) and i > 0 and "|" in lines[i - 1]:
            sep = i
        elif sep is not None and "|" not in line:
            end = i
            break
    if sep is None:
        return text
    if end is None:
        end = len(lines)
    header = sep - 1
    return "".join(lines[:header] + [call + "\n"] + lines[end:])


def _first_cell(line):
    """Parameter name from a table row, or None. Handles both page styles:
    "| `--flag` | ... |" on the krknctl page and "`NAME` | ... " on the krkn-hub
    page. A CLI flag's leading -- is stripped so it matches the source name."""
    parts = line.strip().strip("|").split("|")
    if not parts:
        return None
    cell = parts[0].strip().strip("`").strip()
    if cell.startswith("--"):
        cell = cell[2:]
    return cell or None


def _tables(lines):
    """(header_index, end_index, row_indexes) for each markdown table."""
    out, i = [], 0
    while i < len(lines):
        if _is_table_separator(lines[i]) and i > 0 and "|" in lines[i - 1]:
            end = i + 1
            while end < len(lines) and "|" in lines[end]:
                end += 1
            out.append((i - 1, end, list(range(i + 1, end))))
            i = end
        else:
            i += 1
    return out


def inject_global_shortcodes(text, source, name_to_group):
    """Replace each parameter table on a global page with a group-filtered
    param-table call, deriving the group from the table's own rows.
    Returns (new_text, report). A table is replaced only when every row resolves
    to the same known group and exactly one table on the page claims that group.
    Two sections can draw from one group: Kraken and Tunings both take from
    "general". Injecting either would pull the other's params in while that
    section still lists them, so a split group is left alone on every table."""
    lines = text.splitlines(keepends=True)
    report, edits = [], []

    # Pass 1: resolve every table to a group, or to a reason it cannot be.
    resolved = []
    for header, end, rows in _tables(lines):
        if "param-table" in "".join(lines[header:end]):
            continue
        names = [n for n in (_first_cell(lines[r]) for r in rows) if n]
        if not names:
            continue
        unknown = [n for n in names if n not in name_to_group]
        if unknown:
            resolved.append((header, end, names, None,
                             f"unknown params, left alone: {', '.join(unknown[:4])}"))
            continue
        groups = {name_to_group[n] for n in names}
        if len(groups) != 1:
            resolved.append((header, end, names, None,
                             f"mixed groups {sorted(groups)}, left alone"))
            continue
        resolved.append((header, end, names, groups.pop(), None))

    claims = Counter(g for _, _, _, g, _ in resolved if g)

    # Pass 2: inject only the groups exactly one table claims.
    for header, end, names, group, reason in resolved:
        if reason:
            report.append(reason)
            continue
        if claims[group] > 1:
            report.append(f"group {group} split across {claims[group]} sections, "
                          "left alone to avoid showing params twice")
            continue
        # krknctl stores bare flag names but a reader types --telemetry-enabled.
        # krkn-hub params are env vars and take no prefix.
        prefix = ' prefix="--"' if source == "krknctl" else ""
        call = (f'{{{{< param-table scenario="{GLOBAL_SCENARIO}" '
                f'source="{source}" group="{group}"{prefix} >}}}}\n')
        edits.append((header, end, call))
        report.append(f"{group}: replaced {len(names)} rows")

    for header, end, call in reversed(edits):
        lines[header:end] = [call]
    return "".join(lines), report


def _find_scenario_dir(website_root, scenario):
    """Directory of the page for this scenario. Website page dir names diverge
    from source scenario names (node-cpu-hog -> hog-scenarios/cpu-hog-scenario),
    so the declared <krkn-hub-scenario id> is the reliable link. Falls back to an
    exact dir-name match for pages whose id is missing or disagrees with the
    source (e.g. id="pvc-scenarios" for source pvc-scenario)."""
    root = Path(website_root) / "content/en/docs/scenarios"
    for index in root.rglob("_index.md"):
        m = _ID_RE.search(index.read_text(encoding="utf-8"))
        if m and m.group(1) == scenario:
            return index.parent
    for index in root.rglob("_index.md"):
        if index.parent.name == scenario:
            return index.parent
    return None


def _find_tab(website_root, scenario, source):
    scn_dir = _find_scenario_dir(website_root, scenario)
    if scn_dir is None:
        return None
    tab = scn_dir / f"_tab-{source}.md"
    return tab if tab.exists() else None


# TODO: confirm the new-page frontmatter format with maintainers before relying
# on it (weight, description, and overview prose are placeholders).
_PAGE_HEAD = '''---
title: __TITLE__
description:
weight: 50
---

<krkn-hub-scenario id="__SCENARIO__">

TODO: scenario overview.

</krkn-hub-scenario>

'''

_TAB_HEADERS = {"krkn-hub": "**Krkn-hub**", "krknctl": "**Krknctl**"}


def _tabpane(sources):
    lines = ["{{< tabpane text=true >}}"]
    for s in sources:
        lines += [
            '  {{< tab header="%s" lang="%s" >}}' % (_TAB_HEADERS[s], s),
            '{{< readfile file="_tab-%s.md" >}}' % s,
            "  {{< /tab >}}",
        ]
    lines.append("{{< /tabpane >}}")
    return "\n".join(lines) + "\n"


def _create_scenario_page(website_root, scenario, sources):
    d = Path(website_root) / "content/en/docs/scenarios" / scenario
    d.mkdir(parents=True, exist_ok=True)
    title = scenario.replace("-", " ").title()
    head = _PAGE_HEAD.replace("__TITLE__", title).replace("__SCENARIO__", scenario)
    (d / "_index.md").write_text(head + _tabpane(sources), encoding="utf-8")
    return d


def scaffold_scenario(scenario, website_root):
    """Inject the param-table shortcode into the tab files for the sources that
    actually have generated data (data/params/<scenario>/<source>.yaml). If the
    scenario has no website page yet, create one (index plus stub tabs) for just
    those sources, so a source with no data never gets an empty tab."""
    root = Path(website_root)
    sources = [s for s in ("krkn-hub", "krknctl")
               if (root / "data" / "params" / scenario / f"{s}.yaml").exists()]
    if not sources:
        return
    scn_dir = _find_scenario_dir(website_root, scenario)
    if scn_dir is None:
        scn_dir = _create_scenario_page(website_root, scenario, sources)
    for source in sources:
        tab = scn_dir / f"_tab-{source}.md"
        if not tab.exists():
            tab.write_text(f'{{{{< param-table scenario="{scenario}" source="{source}" >}}}}\n',
                           encoding="utf-8")
            continue
        original = tab.read_text(encoding="utf-8")
        new = inject_shortcode(original, scenario, source)
        if new != original:
            tab.write_text(new, encoding="utf-8")
