from bot.report import NEW

_NO_SOURCE = "no description in any source and no published row"

# Declared by 25 scenarios, described by none. Checked last, above the model, so
# any source that starts describing them takes over on its own.
BUILT_IN = {
    "SCENARIO_TYPE": "Plugin key krkn dispatches the scenario on. Fixed by the "
                     "container image, not a knob to change.",
    "SCENARIO_FILE": "Path to the scenario file baked into the container image. "
                     "Fixed by the image, not a knob to change.",
}


def resolve_descriptions(scenario, records, existing, llm_fn, published=None,
                         borrow_source="krknctl", doc=None):
    """Return (descriptions_by_name, gaps), gaps being (name, filled_from, text,
    note) for each description not taken from a source file. `note` is filled in
    later by attach_reasons; nothing here knows why a row needs a look.
    Priority: source -> published table -> existing file -> scenario doc ->
    other source -> LLM.
    The published table is human-written, so it ranks second and wins only once:
    the run that reads it also removes it."""
    published = published or {}
    doc = doc or {}
    out, gaps, residual = {}, [], []
    for r in records:
        if r.description:
            out[r.name] = r.description
        elif published.get(r.name):
            out[r.name] = published[r.name]
            r.description_source = "published-table"
            gaps.append((r.name, "published-table", out[r.name], ""))
        elif existing.get(r.name):
            out[r.name] = existing[r.name]
        elif doc.get(r.name):
            # krkn-hub documents most params in docs/<scenario>.md, not beside
            # the export. Below the published table, above the model.
            out[r.name] = doc[r.name]
            r.description_source = "hub-doc"
            gaps.append((r.name, "hub-doc", out[r.name], ""))
        elif r.borrowed_description:
            # Not this row's own source, so curated page prose outranks it. The
            # label names where it came from: krknctl, or a CRD column's field.
            out[r.name] = r.borrowed_description
            r.description_source = borrow_source
        elif BUILT_IN.get(r.name):
            out[r.name] = BUILT_IN[r.name]
            r.description_source = "built-in"
        else:
            residual.append(r.name)
    # First time these reach a table, so name who supplied the text.
    for r in records:
        if r.name in BUILT_IN:
            origin = "the bot" if r.description_source == "built-in" else "source comment"
            gaps.append((r.name, NEW, out[r.name], origin))
    if residual:
        generated = llm_fn(scenario, residual)
        by_name = {r.name: r for r in records}
        for name in residual:
            # Blank, not a placeholder. "Configures port." reads as finished
            # while saying nothing, which hides the gap.
            out[name] = generated.get(name, "")
            if out[name]:
                by_name[name].description_source = "llm"
                gaps.append((name, "llm", out[name], ""))
            else:
                gaps.append((name, "", _NO_SOURCE, ""))
    return out, gaps


def attach_reasons(gaps, reasons):
    """A blank row carries the reason as its text; a published row carries it as
    a review note, so the model's output is never withheld. A NEW row already
    uses the note for where its text came from, so it passes through."""
    return [(n, f, t, o) if f == NEW
            else (n, f, reasons.get(n, t), "") if f == ""
            else (n, f, t, reasons.get(n, ""))
            for n, f, t, o in gaps]
