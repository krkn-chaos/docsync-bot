import shutil
from pathlib import Path

import pytest
import yaml

from bot import operator

CRDS = Path(__file__).parent / "fixtures" / "crd"


@pytest.fixture
def repo(tmp_path):
    """A krkn-operator checkout, as the bot sees it: only the CRDs matter."""
    bases = tmp_path / "operator" / "config" / "crd" / "bases"
    bases.mkdir(parents=True)
    for f in CRDS.glob("*.yaml"):
        shutil.copy(f, bases)
    (tmp_path / "website").mkdir()
    return tmp_path


def run(repo, scaffold=True):
    written, gaps = operator.emit(repo / "website", repo / "operator")
    pages = operator.scaffold(repo / "website", repo / "operator") if scaffold else []
    return written, gaps, pages


def sections(written):
    """The per-section files only. `written` also carries the kind index, which
    holds no params."""
    return [f for f in written if Path(f).parent.parent.name == "params"]


def test_a_full_run_writes_a_file_per_section_per_kind(repo):
    written, _, _ = run(repo)
    # 25 section files plus the one kind index.
    assert len(written) == 26
    data = repo / "website" / "data" / "params"
    assert (data / "krknusers" / "spec.yaml").exists()
    assert (data / "krknusers" / "columns.yaml").exists()


def test_the_kind_index_carries_what_a_link_needs(repo):
    """crd-ref reads the kind and short name from here rather than having them
    typed into prose, so the link text cannot drift from the CRD."""
    run(repo)
    index = yaml.safe_load(
        (repo / "website" / operator.INDEX_DATA).read_text(encoding="utf-8"))
    assert index["krknusers"] == {"kind": "KrknUser", "short": "ku", "fields": 9}
    assert set(index) == {
        "krknfiletypes", "krkngraphruns", "krknoperatortargetproviderconfigs",
        "krknoperatortargetproviders", "krknoperatortargets", "krknscenarioruns",
        "krkntargetrequests", "krknusergroups", "krknusers"}


def test_a_removed_kind_leaves_the_index(repo):
    """The index is rewritten whole, so a kind deleted upstream stops resolving
    and crd-ref fails the build rather than linking at a page that is gone."""
    run(repo)
    (repo / "operator" / "config" / "crd" / "bases" /
     "krkn.krkn-chaos.dev_krknusers.yaml").unlink()
    run(repo)
    index = yaml.safe_load(
        (repo / "website" / operator.INDEX_DATA).read_text(encoding="utf-8"))
    assert "krknusers" not in index


def test_a_kind_with_no_status_gets_no_status_file(repo):
    run(repo)
    data = repo / "website" / "data" / "params" / "krknusergroups"
    assert not (data / "status.yaml").exists()
    assert (data / "spec.yaml").exists()


def test_every_row_is_described_without_the_model(repo):
    """The claim the whole source rests on: the CRDs describe themselves, so a
    full run never calls out."""
    calls = []
    original = operator._no_model
    operator._no_model = lambda s, n: calls.append(n) or {}
    try:
        written, gaps, _ = run(repo)
    finally:
        operator._no_model = original
    rows = [p for f in sections(written)
            for p in yaml.safe_load(Path(f).read_text(encoding="utf-8"))["params"]]
    assert len(rows) == 167
    assert [r["name"] for r in rows if not r["description"]] == []
    assert calls == []
    assert gaps == []


def test_only_the_borrowed_column_rows_carry_provenance(repo):
    written, _, _ = run(repo)
    marked = [(Path(f).name, p["name"]) for f in sections(written)
              for p in yaml.safe_load(Path(f).read_text(encoding="utf-8"))["params"]
              if p.get("description_source")]
    # A field describes itself, so only a column can be a borrow.
    assert len(marked) == 26
    assert {f for f, _ in marked} == {"columns.yaml"}


def test_a_second_run_changes_nothing(repo):
    written, _, _ = run(repo)
    before = {f: Path(f).read_bytes() for f in written}
    pages_before = {p: Path(p).read_bytes()
                    for p in (repo / "website").rglob("api-reference/*.md")}
    run(repo)
    assert {f: Path(f).read_bytes() for f in written} == before
    assert {p: Path(p).read_bytes()
            for p in (repo / "website").rglob("api-reference/*.md")} == pages_before


def test_a_page_edited_by_hand_survives_the_next_run(repo):
    """The guarantee: the bot owns the data files, humans own the markdown."""
    run(repo)
    page = repo / "website" / operator.SECTION / "krknusers.md"
    edited = page.read_text(encoding="utf-8") + "\n## Notes\n\nAdded by a human.\n"
    page.write_text(edited, encoding="utf-8")
    run(repo)
    assert page.read_text(encoding="utf-8") == edited


def test_a_changed_description_moves_exactly_one_row(repo):
    run(repo)
    spec = repo / "website" / "data" / "params" / "krknusers" / "spec.yaml"
    before = spec.read_text(encoding="utf-8").splitlines()
    crd = repo / "operator" / "config" / "crd" / "bases" / \
        "krkn.krkn-chaos.dev_krknusers.yaml"
    crd.write_text(crd.read_text(encoding="utf-8").replace(
        "Surname is the last name of the user", "Family name of the user"),
        encoding="utf-8")
    run(repo)
    after = spec.read_text(encoding="utf-8").splitlines()
    differing = [(a, b) for a, b in zip(before, after) if a != b]
    assert len(differing) == 1
    assert "Family name of the user" in differing[0][1]


def test_pages_are_written_once_per_kind_plus_an_index(repo):
    _, _, pages = run(repo)
    assert len(pages) == 10
    names = sorted(Path(p).name for p in pages)
    assert "_index.md" in names
    assert "krknusers.md" in names


def test_a_page_calls_only_the_sources_that_have_data(repo):
    """krknusergroups has no status, so its page must not call a table that
    would fail the Hugo build."""
    run(repo)
    page = (repo / "website" / operator.SECTION / "krknusergroups.md").read_text(
        encoding="utf-8")
    assert 'source="spec"' in page
    assert 'source="columns"' in page
    assert 'source="status"' not in page


def test_the_page_heading_names_the_api_and_short_name(repo):
    run(repo)
    page = (repo / "website" / operator.SECTION / "krknusers.md").read_text(
        encoding="utf-8")
    assert "`krkn.krkn-chaos.dev/v1alpha1`" in page
    assert "short name `ku`" in page
    assert "title: KrknUser" in page


def test_the_go_doc_comment_is_not_rendered_into_the_page(repo):
    """Assert the text itself is absent, not just one hazardous substring: a
    spot-check would still pass for the eight kinds that lack it."""
    run(repo)
    page = (repo / "website" / operator.SECTION / "krknusers.md").read_text(
        encoding="utf-8")
    assert "It represents an authentication entity" not in page
    assert "<user|admin>" not in page


def test_a_kind_added_later_reaches_the_index(repo):
    """The likeliest real event for this source. The index is a generated table
    with no prose slot, so unlike a kind's page it is rewritten every run."""
    late = repo / "operator" / "config" / "crd" / "bases" / \
        "krkn.krkn-chaos.dev_krknusers.yaml"
    held = late.read_text(encoding="utf-8")
    late.unlink()
    run(repo)
    index = repo / "website" / operator.SECTION / "_index.md"
    assert "KrknUser]" not in index.read_text(encoding="utf-8")

    late.write_text(held, encoding="utf-8")
    run(repo)
    text = index.read_text(encoding="utf-8")
    assert "[KrknUser](krknusers/)" in text
    assert (repo / "website" / operator.SECTION / "krknusers.md").exists()


def test_no_two_pages_claim_the_same_sidebar_position(repo):
    """Pages are written once, so a weight assigned by alphabetical position
    would collide the moment a kind was inserted above an existing one."""
    run(repo)
    pages = list((repo / "website" / operator.SECTION).glob("*.md"))
    weights = [line for p in pages if p.name != "_index.md"
               for line in p.read_text(encoding="utf-8").splitlines()
               if line.startswith("weight:")]
    assert weights == []


def test_an_upstream_description_removal_is_reported_not_papered_over(repo):
    """The CRD is regenerated from the Go types, so it is the only authority.
    Keeping the previous run's text would publish what the code no longer says."""
    run(repo)
    crd = repo / "operator" / "config" / "crd" / "bases" / \
        "krkn.krkn-chaos.dev_krknusers.yaml"
    crd.write_text(crd.read_text(encoding="utf-8").replace(
        "description: Surname is the last name of the user\n", ""), encoding="utf-8")
    written, gaps, _ = run(repo)
    spec = yaml.safe_load(
        (repo / "website" / "data" / "params" / "krknusers" / "spec.yaml")
        .read_text(encoding="utf-8"))
    surname = next(p for p in spec["params"] if p["name"] == "surname")
    assert surname["description"] == ""
    assert any(g[2] == "surname" and g[3] == "" for g in gaps)


def _ui_page(repo, rel, body="# Users\n\nClick Next.\n"):
    p = repo / "website" / "content/en/docs/krkn-operator" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_the_bot_points_a_ui_page_at_the_reference(repo):
    """The shortcode is injected, not a plain link: the kind name and URL are
    resolved at build time, so a rename fails the build instead of 404ing."""
    page = _ui_page(repo, "administration/user-management.md")
    run(repo)
    text = page.read_text(encoding="utf-8")
    assert '{{< crd-ref crd="krknusers" >}}' in text
    assert '{{< crd-ref crd="krknusergroups" >}}' in text
    assert text.startswith("# Users\n\nClick Next.")


def test_linking_is_idempotent(repo):
    page = _ui_page(repo, "usage/run-scenarios.md")
    run(repo)
    once = page.read_text(encoding="utf-8")
    run(repo)
    assert page.read_text(encoding="utf-8") == once


def test_a_page_the_map_names_but_the_site_lacks_is_skipped(repo):
    """A renamed page must not crash the run. drift_scanner reports it instead."""
    _ui_page(repo, "usage/chaos-studio.md")
    written = run(repo)[2]
    assert not any("run-scenarios" in str(p) for p in written)
    assert any("chaos-studio" in str(p) for p in written)


def test_drift_reports_a_reference_nothing_links_to(repo):
    """The safety net that replaces the bot writing links itself: it reports,
    a human links."""
    from bot.drift_scanner import operator_findings
    run(repo)
    unlinked = [f.scenario for f in operator_findings(repo / "operator", repo / "website")
                if f.kind == "unlinked"]
    assert "krknusers" in unlinked

    page = repo / "website" / "content/en/docs/krkn-operator/administration"
    page.mkdir(parents=True, exist_ok=True)
    (page / "user-management.md").write_text(
        '# Users\n\n{{< crd-ref crd="krknusers" >}}\n', encoding="utf-8")
    unlinked = [f.scenario for f in operator_findings(repo / "operator", repo / "website")
                if f.kind == "unlinked"]
    assert "krknusers" not in unlinked
    assert "krknusergroups" in unlinked


def test_drift_ignores_a_reference_page_linking_to_itself(repo):
    """The generated pages are the target, so their own calls must not count."""
    from bot.drift_scanner import _linked_crds
    run(repo)
    assert _linked_crds(repo / "website") == set()


def test_drift_sees_a_field_the_tables_have_not_caught_up_with(repo):
    from bot.drift_scanner import operator_findings
    run(repo)
    crd = repo / "operator" / "config" / "crd" / "bases" / \
        "krkn.krkn-chaos.dev_krknusers.yaml"
    crd.write_text(crd.read_text(encoding="utf-8").replace(
        "              surname:\n",
        "              nickname:\n                type: string\n"
        "                description: What to call them\n              surname:\n"),
        encoding="utf-8")
    missing = [(f.scenario, f.param) for f in
               operator_findings(repo / "operator", repo / "website")
               if f.kind == "missing"]
    assert ("krknusers", "nickname") in missing


def test_an_operator_path_with_no_crds_is_an_error(tmp_path, monkeypatch):
    """Pointing --operator at the wrong directory would otherwise write nothing
    and report success."""
    (tmp_path / "website").mkdir()
    monkeypatch.setattr("sys.argv", ["operator", "--operator", str(tmp_path),
                                     "--website", str(tmp_path / "website")])
    with pytest.raises(FileNotFoundError, match="No CRDs"):
        operator.main()


def _report(findings):
    from bot.drift_scanner import format_report
    return format_report(findings)


def _finding(**kw):
    from bot.drift_scanner import Finding
    base = dict(scenario="krknusers", source="spec", kind="missing",
                param="nickname", source_file="src", table_file="tbl")
    return Finding(**{**base, **kw})


def test_an_operator_finding_offers_the_operator_target():
    """The CRD plural groups the report, but `/fix krknusers` routes to doc_bot."""
    md = _report([_finding(target="operator")])
    assert "`/fix operator`" in md
    assert "/fix krknusers" not in md


def test_a_krkn_hub_finding_still_offers_its_own_scenario():
    md = _report([_finding(scenario="node-scenarios", source="krkn-hub", target=None)])
    assert "`/fix node-scenarios`" in md


def test_an_unlinked_only_group_offers_no_command_and_names_the_real_fix():
    """No `/fix` links a page, so offering one would send a reader to a command
    that silently does nothing."""
    md = _report([_finding(kind="unlinked", source="page", param=None,
                           target="operator", table_file="ref/krknusers.md")])
    # The preamble and the guidance both say the word, so pin the offer itself.
    assert "Fix with `/fix" not in md
    assert "_PAGE_LINKS" in md and 'crd-ref crd="krknusers"' in md
    assert "Needs a human" in md


def test_a_mixed_group_keeps_the_command_and_flags_the_part_it_cannot_do():
    md = _report([_finding(target="operator"),
                  _finding(kind="unlinked", source="page", param=None,
                           target="operator")])
    assert "`/fix operator`" in md
    assert "plus a link no `/fix` can add" in md
    # The command covers the rest, so it must not claim to cover everything.
    assert "The rest is safe to regenerate" in md
