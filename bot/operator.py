#!/usr/bin/env python3
"""Generate the krkn-operator API reference from its CRDs.

One data file per kind per section, and one page per kind. Every CRD field is
described at source, so the model is never called: the chain is wired anyway so
the day an undescribed field lands, the report says so instead of publishing a
blank cell."""
import argparse
from pathlib import Path

import yaml

from bot.crd_parser import crd_columns, crd_fields, crd_meta, load_crd
from bot.descriptions import resolve_descriptions
from bot.emitter import HEADER, emit_data_file
from bot.report import write_report

CRD_GLOB = "config/crd/bases/*.yaml"
SECTION = "content/en/docs/krkn-operator/api-reference"
SOURCES = ("spec", "status", "columns")
# plural -> kind, short name, field count. The crd-ref shortcode resolves against
# this, so a renamed CRD fails the site build instead of leaving a 404 in prose.
INDEX_DATA = "data/krkn_operator_crds.yaml"
# Marks a column's description as taken from the field its jsonPath names.
BORROW = "crd-field"
_HEADINGS = {"spec": "Spec", "status": "Status", "columns": "kubectl columns"}


def _no_model(scenario, names):
    """Nothing should reach the model. Returning {} turns an undescribed field
    into a reported gap rather than a silent blank."""
    return {}


def _records(doc):
    spec, status = crd_fields(doc, "spec"), crd_fields(doc, "status")
    by_section = {"spec": {r.name: r for r in spec},
                  "status": {r.name: r for r in status}}
    return {"spec": spec, "status": status,
            "columns": crd_columns(doc, by_section)}


def _emit_one(website_root, scenario, source, records, source_ref):
    # No existing-file rung. The CRD is regenerated from the Go types every
    # build, so it is the only authority: keeping a description upstream just
    # deleted would publish text the code no longer has.
    descs, gaps = resolve_descriptions(scenario, records, {}, _no_model,
                                       borrow_source=BORROW)
    out = emit_data_file(website_root, scenario, source, records, descs, source_ref)
    return out, [(scenario, source) + g for g in gaps]


def _emit_index(website_root, index):
    path = Path(website_root) / INDEX_DATA
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(HEADER + yaml.dump(index, sort_keys=True, allow_unicode=True,
                                       default_flow_style=False), encoding="utf-8")
    return path


def emit(website_root, operator_root, source_ref="HEAD"):
    """Write data/params/<plural>/<section>.yaml plus the kind index.
    Returns (paths, gaps)."""
    website_root = Path(website_root)
    written, gaps, index = [], [], {}
    for path in sorted(Path(operator_root).glob(CRD_GLOB)):
        doc = load_crd(path)
        meta, records = crd_meta(doc), _records(doc)
        for source, recs in records.items():
            if not recs:
                continue
            out, g = _emit_one(website_root, meta["plural"], source, recs, source_ref)
            written.append(out)
            gaps += g
        index[meta["plural"]] = {
            "kind": meta["kind"],
            "short": meta["short"],
            "fields": len(records["spec"]) + len(records["status"]),
        }
    if index:
        written.append(_emit_index(website_root, index))
    return written, gaps


def _page(meta, sources):
    head = f'`{meta["group"]}/{meta["version"]}` &ensp; {meta["scope"]}'
    if meta["short"]:
        head += f' &ensp; short name `{meta["short"]}`'
    # No weight: Hugo falls back to title order, which is the order wanted here.
    # A weight would have to be recomputed as kinds arrive, and these pages are
    # written once so an old one could never be renumbered.
    body = [
        "---",
        f'title: {meta["kind"]}',
        f'description: Fields of the {meta["kind"]} custom resource',
        "---",
        "",
        head,
        "",
        "Generated from `config/crd/bases` in krkn-operator. Edit the Go doc"
        " comments there, not this page.",
        "",
    ]
    # The kind's own doc comment is not rendered: it is written for Go readers
    # and prose here belongs to whoever adds it.
    for source in sources:
        body += [f'## {_HEADINGS[source]}', "",
                 f'{{{{< param-table scenario="{meta["plural"]}" '
                 f'source="{source}" >}}}}', ""]
    return "\n".join(body)


_INDEX_HEAD = """---
title: API Reference
description: Fields of every krkn-operator custom resource
weight: 6
---

The operator is driven by custom resources. These pages are generated from the
CRDs in krkn-operator, so a field here always matches the cluster.

To fix a description, edit the Go doc comment in `api/v1alpha1` upstream. The
next sync carries it here.

<!-- This index is regenerated on every sync. Add prose to a kind's own page,
     which the bot writes once and never touches again. -->

"""


def _index(metas):
    rows = ["| Kind | Short name | Fields |", "| --- | --- | --- |"]
    for m in metas:
        short = f'`{m["short"]}`' if m["short"] else "-"
        rows.append(f'| [{m["kind"]}]({m["plural"]}/) | {short} | {m["fields"]} |')
    return _INDEX_HEAD + "\n".join(rows) + "\n"


def scaffold(website_root, operator_root):
    """Write a page per kind plus the section index.

    A kind's page is written only when absent, because it carries prose a human
    may add. The index is rewritten every run: it is a generated table with no
    prose slot, and left alone it would never list a kind added later."""
    website_root = Path(website_root)
    root = website_root / SECTION
    metas, written = [], []
    for path in sorted(Path(operator_root).glob(CRD_GLOB)):
        doc = load_crd(path)
        meta = crd_meta(doc)
        records = _records(doc)
        meta["fields"] = len(records["spec"]) + len(records["status"])
        meta["sources"] = [s for s in SOURCES if records[s]]
        metas.append(meta)
    metas.sort(key=lambda m: m["kind"])
    for meta in metas:
        if not meta["sources"]:
            continue
        page = root / f'{meta["plural"]}.md'
        if page.exists():
            continue
        page.parent.mkdir(parents=True, exist_ok=True)
        page.write_text(_page(meta, meta["sources"]), encoding="utf-8")
        written.append(page)
    if metas:
        index = root / "_index.md"
        index.parent.mkdir(parents=True, exist_ok=True)
        text = _index(metas)
        if not index.exists() or index.read_text(encoding="utf-8") != text:
            index.write_text(text, encoding="utf-8")
            written.append(index)
    return written + link_pages(website_root)


# ponytail: hardcoded, like globals._PAGES. Which page describes which kind is a
# human judgement that appears in no source file, so a new kind needs a row here.
_PAGE_LINKS = {
    "administration/user-management.md": ("krknusers", "krknusergroups"),
    "administration/cluster-management.md": ("krknoperatortargets", "krkntargetrequests"),
    "administration/provider-configuration.md": ("krknoperatortargetproviders",
                                                 "krknoperatortargetproviderconfigs"),
    "usage/run-scenarios.md": ("krknscenarioruns",),
    "usage/chaos-studio.md": ("krkngraphruns",),
    "usage/file-management.md": ("krknfiletypes",),
}


def link_pages(website_root):
    """Point each hand-written page at the reference for the kinds it describes.

    Injects the shortcode rather than a plain link, so the kind name and URL are
    resolved at build time and a renamed CRD fails the build instead of leaving a
    dead link. Idempotent, and a missing page is left for drift_scanner to report
    rather than crashed on."""
    root = Path(website_root) / "content/en/docs/krkn-operator"
    written = []
    for rel, crds in _PAGE_LINKS.items():
        page = root / rel
        if not page.exists() or "crd-ref" in (text := page.read_text(encoding="utf-8")):
            continue
        refs = " &ensp; ".join(f'{{{{< crd-ref crd="{c}" >}}}}' for c in crds)
        page.write_text(f"{text.rstrip()}\n\n---\n\n**API reference:** {refs}\n",
                        encoding="utf-8")
        written.append(page)
    return written


def main() -> None:
    ap = argparse.ArgumentParser(description="Generate the krkn-operator API reference")
    ap.add_argument("--operator", required=True, help="Path to the krkn-operator repo root")
    ap.add_argument("--website", default=".", help="Path to the website repo root")
    ap.add_argument("--source-ref", default="HEAD")
    ap.add_argument("--scaffold", action="store_true",
                    help="Also write any reference page that does not exist yet")
    args = ap.parse_args()
    crds = sorted(Path(args.operator).glob(CRD_GLOB))
    if not crds:
        raise FileNotFoundError(
            f"No CRDs under {Path(args.operator) / 'config/crd/bases'}. "
            "Point --operator at the krkn-operator repo root.")
    written, gaps = emit(args.website, args.operator, args.source_ref)
    for path in written:
        print(path)
    write_report(gaps)
    if args.scaffold:
        for path in scaffold(args.website, args.operator):
            print(path)


if __name__ == "__main__":
    main()
