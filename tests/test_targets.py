import yaml

from bot.operator import SECTION
from bot.targets import operator_groups, resolve

# The plurals a real index holds. Kept short; only membership matters here.
CRDS = ("krknfiletypes", "krknusers", "krknscenarioruns")


def test_a_scenario_path_resolves_to_that_scenario():
    assert resolve(["data/params/node-scenarios/krkn-hub.yaml"], CRDS) == ["node-scenarios"]


def test_globals_needs_no_special_case():
    """`globals` is the group name the emitter already writes under, so the same
    rule that finds a scenario finds it."""
    assert resolve(["data/params/globals/krknctl.yaml"], CRDS) == ["globals"]


def test_an_operator_group_resolves_to_the_operator_target():
    """The bug this module exists for: a CRD plural routed to bot.doc_bot."""
    changed = ["data/params/krknfiletypes/spec.yaml",
               "data/params/krknusers/columns.yaml"]
    assert resolve(changed, CRDS) == ["operator"]


def test_the_crd_index_and_a_reference_page_both_mean_operator():
    assert resolve(["data/krkn_operator_crds.yaml"], CRDS) == ["operator"]
    assert resolve([f"{SECTION}/krknusers.md"],
                   CRDS) == ["operator"]


def test_a_page_the_bot_links_resolves_to_the_operator():
    """link_pages appends a crd-ref to six prose pages, none under the generated section.
    A pull request whose only change is one of those links resolved to nothing,
    so /resync exited `no target given`."""
    assert resolve(["content/en/docs/krkn-operator/usage/chaos-studio.md"],
                   CRDS) == ["operator"]
    assert resolve(["content/en/docs/krkn-operator/administration/user-management.md"],
                   CRDS) == ["operator"]


def test_a_mixed_pull_request_resolves_every_target_once():
    """The real upstream case: one run touched several sources."""
    changed = ["data/params/globals/krkn-hub.yaml",
               "data/params/krknscenarioruns/spec.yaml",
               "data/params/krknscenarioruns/status.yaml",
               "data/krkn_operator_crds.yaml",
               "data/params/node-scenarios/krknctl.yaml"]
    assert resolve(changed, CRDS) == ["globals", "node-scenarios", "operator"]


def test_without_an_index_a_plural_is_treated_as_a_scenario():
    """No index means we cannot know a group is a CRD, so pass it through for the
    existing guard rather than guess."""
    assert resolve(["data/params/krknusers/spec.yaml"]) == ["krknusers"]


def test_paths_outside_the_generated_tree_are_ignored():
    changed = ["README.md",
               "content/en/docs/krkn-operator/usage/jobs.md",
               "data/params",
               ""]
    assert resolve(changed, CRDS) == []


def test_operator_groups_reads_the_generated_index(tmp_path):
    (tmp_path / "data").mkdir()
    (tmp_path / "data/krkn_operator_crds.yaml").write_text(
        yaml.dump({"krknusers": {"kind": "KrknUser"},
                   "krknfiletypes": {"kind": "KrknFileType"}}), encoding="utf-8")
    assert operator_groups(tmp_path) == {"krknusers", "krknfiletypes"}


def test_operator_groups_is_empty_when_the_index_is_absent(tmp_path):
    assert operator_groups(tmp_path) == set()
