import re
from collections import Counter
from pathlib import Path

_ID_RE = re.compile(r'<krkn-hub-scenario\s+id="([^"]+)"')

# Kept local rather than imported from bot.globals, which imports this module.
GLOBAL_SCENARIO = "globals"


def _is_table_separator(line):
    # The pipe is required: "---" alone is a frontmatter fence.
    s = line.strip().strip("|").strip()
    return "|" in line and bool(s) and "-" in s and all(c in "|-: " for c in s)


def _call(scenario, source):
    # krkn-hub params are env vars and take no prefix.
    prefix = ' prefix="--"' if source == "krknctl" else ""
    return f'{{{{< param-table scenario="{scenario}" source="{source}"{prefix} >}}}}'


def inject_shortcode(text, scenario, source):
    """Replace the parameter table with the param-table shortcode call.
    Idempotent: returns text unchanged if a param-table call is already present."""
    if "param-table" in text:
        return text
    lines = text.splitlines(keepends=True)
    for header, end, _rows in _tables(lines):
        # Not just the first table: a tab can open with prerequisites, and
        # replacing that one deletes it and strands the real table.
        if _is_param_table(lines[header]):
            return "".join(lines[:header] + [_call(scenario, source) + "\n"] + lines[end:])
    return text


def _row_cells(line):
    r"""Cells of a table row, as written, keeping a \| inside its cell.
    Backticks are left alone so a trailing code span survives; use _bare() for
    a column that holds one identifier."""
    body = line.strip().strip("|")
    return [c.strip().replace(r"\|", "|")
            for c in re.split(r"(?<!\\)\|", body)]


def _bare(cell):
    """A cell as an identifier: `NAME` -> NAME. Only for columns that hold one
    token, never for prose."""
    return cell.strip().strip("`").strip()


_PARAM_HEADERS = ("parameter", "argument")


def _is_param_table(header_line):
    """All 52 published tables head their first column Parameter or Argument."""
    cells = _row_cells(header_line)
    return bool(cells) and _bare(cells[0]).lower() in _PARAM_HEADERS


def _first_cell(line):
    """Parameter name from a table row, or None. A CLI flag's leading -- is
    stripped so it matches the source name."""
    cells = _row_cells(line)
    if not cells:
        return None
    cell = _bare(cells[0])
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


def published_table(text):
    """{parameter: (lowercased headers, cells)} for every table on the page.
    Every table, not just the first: the global pages carry one per group. Headers
    travel per row because two tables on a page need not match."""
    lines = text.splitlines()
    out = {}
    for header, _end, row_indexes in _tables(lines):
        # Headers are lookup keys for published_cell, so they must be bare even
        # if the page writes them as `Parameter`.
        headers = [_bare(h).lower() for h in _row_cells(lines[header])]
        for i in row_indexes:
            name = _first_cell(lines[i])
            if name and name not in out:
                out[name] = (headers, _row_cells(lines[i]))
    return out


def published_cell(rows, name, column):
    """The cell under `column` for `name`, or "" when the row or the column is
    absent. The global pages have no Type column, so a miss is normal."""
    headers, cells = rows.get(name, ([], []))
    i = headers.index(column) if column in headers else -1
    return cells[i] if 0 <= i < len(cells) else ""


def _group_call(source, group):
    # krknctl stores bare flag names but a reader types --telemetry-enabled.
    prefix = ' prefix="--"' if source == "krknctl" else ""
    return (f'{{{{< param-table scenario="{GLOBAL_SCENARIO}" '
            f'source="{source}" group="{group}"{prefix} >}}}}')


def _slug(heading):
    return re.sub(r"[^a-z0-9]+", "_", heading.strip().lower()).strip("_")


def page_section_groups(text):
    """{parameter: section slug} for every hand-written table on a global page.
    env.sh carries no grouping, so the krkn-hub page's own sections supply it.
    krknctl groups describe the other page's layout."""
    lines = text.splitlines()
    heads = {i: _slug(ln[3:]) for i, ln in enumerate(lines) if ln.startswith("## ")}
    out = {}
    for header, _end, rows in _tables(lines):
        above = [i for i in heads if i < header]
        if not above:
            continue
        slug = heads[max(above)]
        for r in rows:
            name = _first_cell(lines[r])
            if name:
                out.setdefault(name, slug)
    return out


def inject_global_shortcodes(text, source, name_to_group):
    """Replace each parameter table on a global page with a group-filtered
    param-table call, returning (new_text, report). Replaced only when every row
    resolves to one known group and exactly one table claims it: Kraken and
    Tunings both draw from "general", so injecting either would duplicate the
    other's rows while that section still lists them."""
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
        # A row no source produces is a dropped param, reported separately. It
        # must not veto the table, or one stale row freezes a whole section.
        known = [n for n in names if n in name_to_group]
        if not known:
            resolved.append((header, end, names, None,
                             f"no known params, left alone: {', '.join(names[:4])}"))
            continue
        groups = {name_to_group[n] for n in known}
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
        edits.append((header, end, _group_call(source, group) + "\n"))
        report.append(f"{group}: replaced {len(names)} rows")

    for header, end, call in reversed(edits):
        lines[header:end] = [call]

    # A group no section renders is a param the reader never sees. Appending a
    # section is the whole point of the bot: surface the drift, do not hide it.
    shown = set(re.findall(r'group="([^"]+)"', text)) | set(claims)
    stranded = {n for _, _, ns, g, why in resolved if why for n in ns}
    for group in sorted(set(name_to_group.values()) - shown):
        if any(name_to_group.get(n) == group for n in stranded):
            continue
        lines += ["\n---\n\n", f"## {group.replace('_', ' ').title()}\n\n",
                  "Parameters found in the source that no section above covers.\n\n",
                  _group_call(source, group) + "\n"]
        report.append(f"{group}: added a section, no table claimed it")
    return "".join(lines), report


def _find_scenario_dir(website_root, scenario):
    """Directory of the page for this scenario, by declared <krkn-hub-scenario id>
    then by directory name: page dirs diverge from scenario names, so the id is
    the link. Sorted, so the answer does not depend on the runner's filesystem
    order. Raises on a duplicate id, since picking either page plants the
    shortcode on the wrong one and leaves the real one stale."""
    root = Path(website_root) / "content/en/docs/scenarios"
    indexes = sorted(root.rglob("_index.md"))
    matches = [i.parent for i in indexes
               if (m := _ID_RE.search(i.read_text(encoding="utf-8", errors="replace")))
               and m.group(1) == scenario]
    if len(matches) > 1:
        raise ValueError(f"{scenario} is claimed by {len(matches)} pages: "
                         + ", ".join(str(p) for p in matches))
    if matches:
        return matches[0]
    return next((i.parent for i in indexes if i.parent.name == scenario), None)


def find_tab(website_root, scenario, source):
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
    """Inject the param-table shortcode into the tab files for sources that have
    generated data. Creates the page if the scenario has none, for those sources
    only, so a source with no data never gets an empty tab."""
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
            tab.write_text(_call(scenario, source) + "\n", encoding="utf-8")
            continue
        original = tab.read_text(encoding="utf-8")
        new = inject_shortcode(original, scenario, source)
        if new != original:
            tab.write_text(new, encoding="utf-8")
