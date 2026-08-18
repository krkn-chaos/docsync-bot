_NO_SOURCE = "no description in any source and no published row"


def resolve_descriptions(scenario, records, existing, llm_fn, published=None,
                         borrow_source="krknctl"):
    """Return (descriptions_by_name, gaps), gaps being (name, filled_from, text)
    for each description not taken from a source file.
    Priority: source -> published table -> existing file -> other source -> LLM.
    The published table is human-written, so it ranks second and wins only once:
    the run that reads it also removes it."""
    published = published or {}
    out, gaps, residual = {}, [], []
    for r in records:
        if r.description:
            out[r.name] = r.description
        elif published.get(r.name):
            out[r.name] = published[r.name]
            r.description_source = "published-table"
            gaps.append((r.name, "published-table", out[r.name]))
        elif existing.get(r.name):
            out[r.name] = existing[r.name]
        elif r.borrowed_description:
            # Not this row's own source, so curated page prose outranks it. The
            # label names where it came from: krknctl, or a CRD column's field.
            out[r.name] = r.borrowed_description
            r.description_source = borrow_source
        else:
            residual.append(r.name)
    if residual:
        generated = llm_fn(scenario, residual)
        by_name = {r.name: r for r in records}
        for name in residual:
            # Blank, not a placeholder. "Configures port." reads as finished
            # while saying nothing, which hides the gap.
            out[name] = generated.get(name, "")
            if out[name]:
                by_name[name].description_source = "llm"
                gaps.append((name, "llm", out[name]))
            else:
                gaps.append((name, "", _NO_SOURCE))
    return out, gaps
