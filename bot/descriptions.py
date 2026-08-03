def resolve_descriptions(scenario, records, existing, llm_fn):
    """Return (descriptions_by_name, names_sent_to_llm).

    Priority: source desc -> existing file desc -> LLM (residual only).

    The old order put existing first, to protect hand-edits. But the file it
    protected is stamped "Do not edit by hand", so all it did was freeze wording
    at first generation: a better description in krknctl-input.json never
    reached the docs. Every other field already takes the source as truth.

    Existing stays as a fallback for params neither source describes.
    """
    out = {}
    residual = []
    for r in records:
        if r.description:
            out[r.name] = r.description
        elif r.name in existing and existing[r.name]:
            out[r.name] = existing[r.name]
        else:
            residual.append(r.name)
    if residual:
        generated = llm_fn(scenario, residual)
        for name in residual:
            # Blank, not a placeholder. "Configures port." reads as finished
            # while saying nothing, which hides the gap.
            out[name] = generated.get(name, "")
    return out, residual
