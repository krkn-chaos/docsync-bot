import json
import re

import pytest
import yaml

from bot import globals as g


def _sources(tmp_path, env, ctl):
    """A mini krkn-hub and krkn. Returns (krkn_hub_root, krkn_root)."""
    hub = tmp_path / "hub"
    hub.mkdir()
    (hub / "env.sh").write_text(env, encoding="utf-8")
    containers = tmp_path / "krkn" / "containers"
    containers.mkdir(parents=True)
    (containers / "krknctl-input.json").write_text(json.dumps(ctl), encoding="utf-8")
    return hub, tmp_path / "krkn"


CTL = [{"name": "cerberus-enabled", "variable": "CERBERUS_ENABLED", "group": "cerberus",
        "default": "False", "description": "Enables Cerberus Support"}]

CERBERUS = 'export CERBERUS_ENABLED=${CERBERUS_ENABLED:=False}\n'


def _rows(website, source):
    text = (website / f"data/params/globals/{source}.yaml").read_text(encoding="utf-8")
    return yaml.safe_load(text)["params"]


def _global_page(website, body):
    page = website / "content/en/docs/scenarios"
    page.mkdir(parents=True, exist_ok=True)
    (page / "all-scenario-env.md").write_text(body, encoding="utf-8")


def test_a_global_description_is_carried_from_the_published_page(tmp_path):
    """6 of the 75 krkn-hub globals have no description in any source, and
    SIGNAL_STATE is one that carries a long one on the page."""
    hub, krkn = _sources(tmp_path, CERBERUS + 'export SIGNAL_STATE=${SIGNAL_STATE:=RUN}\n', CTL)
    website = tmp_path / "site"
    _global_page(website,
                 "Parameter | Description | Default\n"
                 "--------- | ----------- | -------\n"
                 "`SIGNAL_STATE` | Waits for the RUN signal | RUN\n")
    g.emit(website, hub, krkn)
    rows = {r["name"]: r for r in _rows(website, "krkn-hub")}
    assert rows["SIGNAL_STATE"]["description"] == "Waits for the RUN signal"
    assert rows["SIGNAL_STATE"]["description_source"] == "published-table"


def test_every_group_table_on_the_global_page_is_read(tmp_path):
    """The real page carries nine tables, one per group. A first-table-only
    reader would blank the other eight."""
    hub, krkn = _sources(
        tmp_path,
        CERBERUS + 'export SIGNAL_STATE=${SIGNAL_STATE:=RUN}\nexport PORT=${PORT:=8081}\n',
        CTL)
    website = tmp_path / "site"
    _global_page(website,
                 "Parameter | Description\n--------- | -----------\n"
                 "`SIGNAL_STATE` | From table one\n"
                 "\n"
                 "Parameter | Description\n--------- | -----------\n"
                 "`PORT` | From table two\n")
    g.emit(website, hub, krkn)
    rows = {r["name"]: r for r in _rows(website, "krkn-hub")}
    assert rows["SIGNAL_STATE"]["description"] == "From table one"
    assert rows["PORT"]["description"] == "From table two"


def test_the_published_page_outranks_the_other_source(tmp_path):
    """The page is the only human-written rung. krknctl says "Enables Cerberus
    Support"; the page says when to set it, and elsewhere carries links."""
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    website = tmp_path / "site"
    _global_page(website,
                 "Parameter | Description\n--------- | -----------\n"
                 "`CERBERUS_ENABLED` | Set this to true if cerberus monitors the cluster\n")
    g.emit(website, hub, krkn)
    rows = {r["name"]: r for r in _rows(website, "krkn-hub")}
    assert rows["CERBERUS_ENABLED"]["description"] == \
        "Set this to true if cerberus monitors the cluster"
    assert rows["CERBERUS_ENABLED"]["description_source"] == "published-table"


def test_the_other_source_fills_a_param_the_page_never_listed(tmp_path):
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    website = tmp_path / "site"
    _global_page(website, "No table here.\n")
    g.emit(website, hub, krkn)
    rows = {r["name"]: r for r in _rows(website, "krkn-hub")}
    assert rows["CERBERUS_ENABLED"]["description"] == "Enables Cerberus Support"
    assert rows["CERBERUS_ENABLED"]["description_source"] == "krknctl"


def test_env_export_borrows_its_group_from_the_join(tmp_path):
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    _, env = g.build_groups(hub, krkn)
    assert env[0].group == "cerberus"


def test_env_export_borrows_a_description_when_it_has_no_comment(tmp_path):
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    _, env = g.build_groups(hub, krkn)
    assert env[0].borrowed_description == "Enables Cerberus Support"


def test_own_comment_beats_the_joined_description(tmp_path):
    hub, krkn = _sources(tmp_path, CERBERUS.rstrip("\n") + "  # Local wording\n", CTL)
    _, env = g.build_groups(hub, krkn)
    assert env[0].description == "Local wording"


def test_unjoined_export_lands_in_other(tmp_path):
    """RETRY_WAIT is krkn-hub only, krknctl does not expose it."""
    hub, krkn = _sources(tmp_path, 'export RETRY_WAIT=${RETRY_WAIT:=120}\n', CTL)
    _, env = g.build_groups(hub, krkn)
    assert env[0].group == "other"


def test_the_krknctl_side_is_named_by_its_cli_flag(tmp_path):
    """Its page renders --cerberus-enabled, not CERBERUS_ENABLED."""
    hub, krkn = _sources(tmp_path, "", CTL)
    ctl, _ = g.build_groups(hub, krkn)
    assert ctl[0].name == "cerberus-enabled"
    assert ctl[0].group == "cerberus"


def test_an_entry_without_a_flag_keeps_its_variable_name(tmp_path):
    hub, krkn = _sources(tmp_path, "", [{"variable": "ONLY_A_VAR", "group": "cerberus"}])
    ctl, _ = g.build_groups(hub, krkn)
    assert [r.name for r in ctl] == ["ONLY_A_VAR"]


def test_an_entry_without_a_group_lands_in_other(tmp_path):
    """A row emitted with no group matches no group-filtered call, so it would
    drop off the page rather than surface somewhere wrong."""
    hub, krkn = _sources(tmp_path, "", [{"name": "no-group", "variable": "NO_GROUP"}])
    web = tmp_path / "web"
    g.emit(web, hub, krkn)
    assert _rows(web, "krknctl")[0]["group"] == "other"


def test_a_missing_env_sh_is_refused_at_the_cli(tmp_path, monkeypatch):
    """emit() on its own would write an empty krkn-hub.yaml over the committed one."""
    hub, krkn = _sources(tmp_path, "", CTL)
    (hub / "env.sh").unlink()
    monkeypatch.setattr("sys.argv", ["globals", "--krkn-hub", str(hub), "--krkn", str(krkn),
                                     "--website", str(tmp_path / "web")])
    with pytest.raises(FileNotFoundError, match="KRKN_HUB_PATH"):
        g.main()


def test_emits_one_file_per_source_not_per_group(tmp_path):
    """Grouping is data, not filenames: a new upstream group must not add a file."""
    hub, krkn = _sources(tmp_path, 'export RETRY_WAIT=${RETRY_WAIT:=120}\n', CTL)
    web = tmp_path / "web"
    g.emit(web, hub, krkn)
    d = web / "data/params/globals"
    assert sorted(p.name for p in d.iterdir()) == ["krkn-hub.yaml", "krknctl.yaml"]


def test_every_param_carries_its_group(tmp_path):
    hub, krkn = _sources(tmp_path, 'export RETRY_WAIT=${RETRY_WAIT:=120}\n', CTL)
    web = tmp_path / "web"
    g.emit(web, hub, krkn)
    assert {r["name"]: r["group"] for r in _rows(web, "krkn-hub")} == {"RETRY_WAIT": "other"}
    assert _rows(web, "krknctl")[0]["group"] == "cerberus"


def test_globals_leave_out_the_required_column(tmp_path):
    """No global is required, so the column would be one value repeated."""
    hub, krkn = _sources(tmp_path, "", CTL)
    web = tmp_path / "web"
    g.emit(web, hub, krkn)
    assert "required" not in _rows(web, "krknctl")[0]


def test_a_source_description_change_reaches_the_data_file(tmp_path):
    hub, krkn = _sources(tmp_path, "", CTL)
    web = tmp_path / "web"
    out = web / "data/params/globals/krknctl.yaml"
    out.parent.mkdir(parents=True)
    out.write_text("params:\n  - name: cerberus-enabled\n    description: stale wording\n",
                   encoding="utf-8")
    g.emit(web, hub, krkn)
    assert _rows(web, "krknctl")[0]["description"] == "Enables Cerberus Support"


PAGE = """## Cerberus

Blurb.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--cerberus-enabled` | Enables it | False |
"""


def test_scaffold_injects_into_the_global_pages(tmp_path):
    hub, krkn = _sources(tmp_path, "", CTL)
    web = tmp_path / "web"
    d = web / "content/en/docs/scenarios"
    d.mkdir(parents=True)
    (d / "all-scenario-env-krknctl.md").write_text(PAGE, encoding="utf-8")
    report = g.scaffold(web, hub, krkn)
    out = (d / "all-scenario-env-krknctl.md").read_text(encoding="utf-8")
    assert 'group="cerberus"' in out
    assert "Blurb." in out, "prose must survive"
    assert any("cerberus" in r for r in report), report


def test_scaffold_tolerates_a_missing_page(tmp_path):
    hub, krkn = _sources(tmp_path, "", CTL)
    web = tmp_path / "web"
    (web / "content/en/docs/scenarios").mkdir(parents=True)
    assert g.scaffold(web, hub, krkn) == []


def test_regenerating_twice_is_byte_identical(tmp_path):
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    web = tmp_path / "web"
    g.emit(web, hub, krkn)
    first = (web / "data/params/globals/krkn-hub.yaml").read_text(encoding="utf-8")
    g.emit(web, hub, krkn)
    assert (web / "data/params/globals/krkn-hub.yaml").read_text(encoding="utf-8") == first


def test_the_page_section_outranks_the_krknctl_group(tmp_path):
    """krknctl's groups describe the krknctl page. Applying them to the krkn-hub
    page put params in sections that page does not have."""
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    website = tmp_path / "site"
    _global_page(website, "## Kraken\n\nParameter | Description | Default\n"
                          "--------- | ----------- | -------\n"
                          "`CERBERUS_ENABLED` | Enables it | False\n")
    _, env = g.build_groups(hub, krkn, website)
    assert env[0].group == "kraken"


def test_a_param_new_to_the_page_still_takes_the_krknctl_group(tmp_path):
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    website = tmp_path / "site"
    _global_page(website, "## Kraken\n\nNo table here.\n")
    _, env = g.build_groups(hub, krkn, website)
    assert env[0].group == "cerberus"


def test_a_param_in_neither_lands_in_other(tmp_path):
    hub, krkn = _sources(tmp_path, 'export BRAND_NEW=${BRAND_NEW:=1}\n', CTL)
    website = tmp_path / "site"
    _global_page(website, "## Kraken\n\nNo table here.\n")
    _, env = g.build_groups(hub, krkn, website)
    assert env[0].group == "other"


def test_a_dropped_global_is_reported(tmp_path):
    """ES_RUN_TAG was removed from env.sh but stayed on the page, and nothing
    said so: the orphan check existed only on the per-scenario path."""
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    website = tmp_path / "site"
    _global_page(website, "Parameter | Description | Default\n"
                          "--------- | ----------- | -------\n"
                          "`ES_RUN_TAG` | Tag to identify the run | blank\n")
    _, gaps = g.emit(website, hub, krkn)
    assert ("globals", "krkn-hub", "ES_RUN_TAG", "orphan", "") in gaps


def test_the_data_file_and_the_injected_call_agree_on_the_group(tmp_path):
    """Two build_groups calls with different website_root would emit a section
    filtering on a group no row carries, rendering an empty table."""
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    website = tmp_path / "site"
    _global_page(website, "## Kraken\n\nParameter | Description | Default\n"
                          "--------- | ----------- | -------\n"
                          "`CERBERUS_ENABLED` | Enables it | False\n")
    g.emit(website, hub, krkn)
    g.scaffold(website, hub, krkn)
    page = (website / "content/en/docs/scenarios/all-scenario-env.md").read_text(encoding="utf-8")
    assert 'group="kraken"' in page
    assert {r["group"] for r in _rows(website, "krkn-hub")} == {"kraken"}


def _run(website, hub, krkn):
    g.emit(website, hub, krkn)
    g.scaffold(website, hub, krkn)
    page = website / "content/en/docs/scenarios/all-scenario-env.md"
    return page.read_text(encoding="utf-8"), _rows(website, "krkn-hub")


def test_a_second_run_changes_nothing(tmp_path):
    """Run two reads a converted page, so every group would collapse into "other"
    and every call already on the page would filter on a group nothing carries."""
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    website = tmp_path / "site"
    _global_page(website, "## Kraken\n\nParameter | Description | Default\n"
                          "--------- | ----------- | -------\n"
                          "`CERBERUS_ENABLED` | Enables it | False\n")
    first = _run(website, hub, krkn)
    assert _run(website, hub, krkn) == first


def test_every_emitted_param_is_rendered_by_some_call(tmp_path):
    """A param in the data file that no group call selects renders nowhere, which
    is worse than a blank cell because nothing on the page shows it is missing."""
    hub, krkn = _sources(
        tmp_path, CERBERUS + 'export GLOBAL_PROBE_TIMEOUT=${GLOBAL_PROBE_TIMEOUT:=90}\n', CTL)
    website = tmp_path / "site"
    _global_page(website, "## Kraken\n\nParameter | Description | Default\n"
                          "--------- | ----------- | -------\n"
                          "`CERBERUS_ENABLED` | Enables it | False\n")
    page, rows = _run(website, hub, krkn)
    rendered = set(re.findall(r'group="([^"]+)"', page))
    assert {r["group"] for r in rows} <= rendered
    assert "GLOBAL_PROBE_TIMEOUT" in {r["name"] for r in rows}


def test_provenance_survives_a_second_run(tmp_path):
    """The published table is read once, by the run that replaces it."""
    hub, krkn = _sources(tmp_path, CERBERUS + 'export SIGNAL_STATE=${SIGNAL_STATE:=RUN}\n', CTL)
    website = tmp_path / "site"
    _global_page(website, "Parameter | Description | Default\n"
                          "--------- | ----------- | -------\n"
                          "`SIGNAL_STATE` | Waits for the RUN signal | RUN\n")
    _run(website, hub, krkn)
    _, rows = _run(website, hub, krkn)
    row = next(r for r in rows if r["name"] == "SIGNAL_STATE")
    assert row["description"] == "Waits for the RUN signal"
    assert row["description_source"] == "published-table"
