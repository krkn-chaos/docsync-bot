"""Commit-message sections for descriptions the bot did not take from source.
The commit message is written by a shell step and never passes through the agent."""
import json
import os
import re
from pathlib import Path

# The fix lives in a different file per source, so one hint would misdirect
# whoever picks up a gap from any other one.
_FIX_HINTS = {
    "krkn-hub": ("add a trailing comment in env.sh, e.g. "
                 "`export BLOCK_SIZE=${BLOCK_SIZE:=1024}   # Size of each block`"),
    "krknctl": 'set `"description"` on the parameter in `krknctl-input.json`',
    "spec": "add a Go doc comment in `api/v1alpha1`, then run `make manifests`",
    "status": "add a Go doc comment in `api/v1alpha1`, then run `make manifests`",
    "columns": ("give the printcolumn a `description=`, or describe the field "
                "its jsonPath names"),
}


def _fix_hint(blank):
    by_hint = {}
    for row in blank:
        hint = _FIX_HINTS.get(row[1])
        if hint:
            by_hint.setdefault(hint, set()).add(row[1])
    lines = ["These render as an empty cell."]
    lines += [f"- {', '.join(sorted(s))}: {h}" for h, s in sorted(by_hint.items())]
    return "\n".join(lines) + "\n"

# Written by a human, just not in this row's own source file.
FILLED = ("published-table", "hub-doc")
MODEL = "llm"
ORPHAN = "orphan"
EXCLUDED = "excluded"


def _cell(text):
    """Table cell. A newline or a pipe in the text would break the row."""
    return re.sub(r"\s+", " ", text or "").replace("|", r"\|").strip()


def _once(rows):
    """A param on both tabs produces a row per source. The reader wants it once,
    and a note from either tab survives even if its row sorts second."""
    kept = {}
    for row in sorted(rows):
        key = (row[0], row[2], row[3], row[4])
        if key not in kept:
            kept[key] = row
        elif row[5] and row[5] != kept[key][5]:
            prior = kept[key][5]
            note = row[5] if not prior else "; ".join(sorted({prior, row[5]}))
            kept[key] = kept[key][:5] + (note,)
    return list(kept.values())


def render(gaps):
    """gaps is (scenario, source, param, filled_from, text, note); filled_from is
    "" for a blank, with the reason in text. Sorted so reruns are byte identical."""
    filled = _once(g for g in gaps if g[3] in FILLED)
    model = _once(g for g in gaps if g[3] == MODEL)
    blank = _once(g for g in gaps if g[3] == "")
    excluded = _once(g for g in gaps if g[3] == EXCLUDED)
    # Orphans keep their source: which tab lost the row is the useful part.
    orphan = sorted(set(g for g in gaps if g[3] == ORPHAN))
    out = []
    if filled:
        out += [f"### Descriptions not taken from source ({len(filled)})\n",
                "| Scenario | Parameter | Filled from | Text |",
                "| --- | --- | --- | --- |"]
        out += [f"| {s} | {p} | {src} | {_cell(t)} |" for s, _, p, src, t, _n in filled]
        out.append("")
    if model:
        # Everything the model wrote is published as written, so the reviewer
        # decides. Rows the validator flagged sort first.
        model.sort(key=lambda g: (not g[5], g[0], g[2]))
        flagged = sum(1 for g in model if g[5])
        head = f"### Written by the model, review before merge ({len(model)})"
        if flagged:
            head += f", {flagged} flagged"
        out += [head + "\n",
                "| Scenario | Parameter | Text | Check |",
                "| --- | --- | --- | --- |"]
        out += [f"| {s} | {p} | {_cell(t)} | {_cell(n) or '-'} |"
                for s, _, p, _f, t, n in model]
        out.append("")
    if blank:
        out += [f"### Still blank ({len(blank)})\n",
                "| Scenario | Parameter | Why |",
                "| --- | --- | --- |"]
        out += [f"| {s} | {p} | {_cell(why)} |" for s, _, p, _f, why, _n in blank]
        out += ["", _fix_hint(blank)]
    if orphan:
        out += [f"### Dropped, not in any source ({len(orphan)})\n",
                "| Scenario | Source | Parameter |",
                "| --- | --- | --- |"]
        out += [f"| {s} | {sr} | {p} |" for s, sr, p, _f, _t, _n in orphan]
        out.append("")
    if excluded:
        out += [f"### Not on this page ({len(excluded)})\n",
                "| Scenario | Parameter | Why |",
                "| --- | --- | --- |"]
        out += [f"| {s} | {p} | {_cell(why)} |" for s, _, p, _f, why, _n in excluded]
        out.append("")
    return "\n".join(out)


def write_report(gaps):
    """Append raw rows, not rendered markdown: the workflow runs the bot once per
    target, and rendering per target would repeat every section heading."""
    d = os.environ.get("GH_AW_REPORT_DIR")
    if not d:
        return
    with Path(d, "gaps.jsonl").open("a", encoding="utf-8") as fh:
        for g in gaps:
            fh.write(json.dumps(g) + "\n")


def main():
    """Render every target's rows into one gaps.md. Run after the generate loop."""
    d = Path(os.environ.get("GH_AW_REPORT_DIR", "."))
    raw = d / "gaps.jsonl"
    gaps = [tuple(json.loads(l)) for l in raw.read_text(encoding="utf-8").splitlines()
            if l.strip()] if raw.exists() else []
    (d / "gaps.md").write_text(render(gaps), encoding="utf-8")


if __name__ == "__main__":
    main()
