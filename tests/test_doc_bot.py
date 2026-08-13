import yaml
import bot.doc_bot as doc_bot


def _site(tmp_path):
    website = tmp_path / "site"
    (website / "content/en/docs/scenarios").mkdir(parents=True)
    (website / "content/en/docs/scenarios/all-scenario-env.md").write_text("", encoding="utf-8")
    return website


def _params(website, scenario, source="krkn-hub"):
    data = yaml.safe_load((website / f"data/params/{scenario}/{source}.yaml").read_text(encoding="utf-8"))
    return {p["name"]: p for p in data["params"]}


def _page(website, scenario, source, table, page_dir=None):
    d = website / "content/en/docs/scenarios" / (page_dir or scenario)
    d.mkdir(parents=True, exist_ok=True)
    (d / "_index.md").write_text(f'<krkn-hub-scenario id="{scenario}">\n', encoding="utf-8")
    (d / f"_tab-{source}.md").write_text(table, encoding="utf-8")


def _scn(tmp_path, name, env=None, krknctl=None):
    scn = tmp_path / "hub" / name
    scn.mkdir(parents=True)
    if env:
        (scn / "env.sh").write_text(env, encoding="utf-8")
    if krknctl:
        (scn / "krknctl-input.json").write_text(krknctl, encoding="utf-8")
    return tmp_path / "hub"


def test_a_published_description_is_carried_when_no_source_has_one(tmp_path):
    """VERIFY_SESSION and 3 others: the page has wording and no source does."""
    hub = _scn(tmp_path, "node-scenarios", env='export VERIFY_SESSION="${VERIFY_SESSION:-false}"\n')
    website = _site(tmp_path)
    _page(website, "node-scenarios", "krkn-hub",
          "Parameter | Description | Type\n"
          "--------- | ----------- | ----\n"
          "VERIFY_SESSION | Verify the SSH session | string\n")
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    row = _params(website, "node-scenarios")["VERIFY_SESSION"]
    assert row["description"] == "Verify the SSH session"
    assert row["type"] == "string"
    assert row["description_source"] == "published-table"


def test_the_page_is_found_when_its_directory_name_diverges(tmp_path):
    """hog-scenarios/cpu-hog-scenario is the page for node-cpu-hog. Only 12 of
    the 31 scenarios match a page directory by name."""
    hub = _scn(tmp_path, "node-cpu-hog", env='export NEW_ONE="${NEW_ONE:-x}"\n')
    website = _site(tmp_path)
    _page(website, "node-cpu-hog", "krkn-hub",
          "Parameter | Description\n--------- | -----------\nNEW_ONE | From the page\n",
          page_dir="hog-scenarios/cpu-hog-scenario")
    doc_bot.run(scenario="node-cpu-hog", krkn_hub_root=hub, website_root=website)
    assert _params(website, "node-cpu-hog")["NEW_ONE"]["description"] == "From the page"


def test_the_krknctl_page_is_keyed_by_flag_not_env_var(tmp_path):
    """The page lists --action; the data file keys name on ACTION."""
    hub = _scn(tmp_path, "node-scenarios",
               krknctl='[{"name": "action", "variable": "ACTION"}]')
    website = _site(tmp_path)
    _page(website, "node-scenarios", "krknctl",
          "Parameter | Description\n--------- | -----------\n`--action` | From the page\n")
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    row = _params(website, "node-scenarios", "krknctl")["ACTION"]
    assert row["description"] == "From the page"


def test_a_carried_description_and_type_survive_the_next_run(tmp_path):
    """The shortcode replaces the table in the run that reads it, so run 2 has
    no page left to fall back to."""
    hub = _scn(tmp_path, "node-scenarios", env='export VERIFY_SESSION="${VERIFY_SESSION:-false}"\n')
    website = _site(tmp_path)
    _page(website, "node-scenarios", "krkn-hub",
          "Parameter | Description | Type\n"
          "--------- | ----------- | ----\n"
          "VERIFY_SESSION | Verify the SSH session | string\n")
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    tab = website / "content/en/docs/scenarios/node-scenarios/_tab-krkn-hub.md"
    tab.write_text('{{< param-table scenario="node-scenarios" source="krkn-hub" >}}\n',
                   encoding="utf-8")
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    row = _params(website, "node-scenarios")["VERIFY_SESSION"]
    assert row["description"] == "Verify the SSH session"
    assert row["type"] == "string"
    assert row["description_source"] == "published-table"


def test_a_generated_description_is_cached_not_regenerated(tmp_path, monkeypatch):
    """temperature 0 is not fully reproducible across calls, so run 2 has to take
    the value from the file or every sync churns the diff."""
    calls = []

    def fake(scenario, names, ctx, transport=None, errors=None):
        # No digits: validate() rejects a literal the source record does not have.
        calls.append(list(names))
        return {n: "Written by the model." for n in names}

    monkeypatch.setattr("bot.describe.describe", fake)
    hub = _scn(tmp_path, "node-scenarios", env='export NEW_ONE="${NEW_ONE:-x}"\n')
    website = _site(tmp_path)
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    row = _params(website, "node-scenarios")["NEW_ONE"]
    assert row["description"] == "Written by the model."
    assert row["description_source"] == "llm"
    assert len(calls) == 1


def test_env_description_filled_from_krknctl_json(tmp_path):
    hub = tmp_path / "hub"
    scn = hub / "node-scenarios"
    scn.mkdir(parents=True)
    (scn / "env.sh").write_text('export FOO="${FOO:-x}"\n', encoding="utf-8")
    (scn / "krknctl-input.json").write_text(
        '[{"variable": "FOO", "description": "controls the foo behaviour", "default": "x"}]',
        encoding="utf-8")
    website = _site(tmp_path)

    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)

    assert _params(website, "node-scenarios")["FOO"]["description"] == "controls the foo behaviour"


def test_env_params_borrow_type_from_krknctl(tmp_path):
    """env.sh has no types. RUNS has a type and no description, which the
    description-only filter would have dropped."""
    hub = tmp_path / "hub"
    scn = hub / "node-scenarios"
    scn.mkdir(parents=True)
    (scn / "env.sh").write_text(
        'export TIMEOUT="${TIMEOUT:-180}"\nexport RUNS="${RUNS:-1}"\n', encoding="utf-8")
    (scn / "krknctl-input.json").write_text(
        '[{"variable": "TIMEOUT", "type": "number", "description": "How long to wait"},'
        ' {"variable": "RUNS", "type": "number"}]', encoding="utf-8")
    website = _site(tmp_path)
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    rows = _params(website, "node-scenarios")
    assert rows["TIMEOUT"]["type"] == "number"
    assert rows["TIMEOUT"]["description"] == "How long to wait"
    assert rows["RUNS"]["type"] == "number"


def test_env_only_param_is_left_blank_not_papered_over(tmp_path):
    hub = tmp_path / "hub"
    scn = hub / "node-scenarios"
    scn.mkdir(parents=True)
    (scn / "env.sh").write_text('export BAR="${BAR:-y}"\n', encoding="utf-8")
    (scn / "krknctl-input.json").write_text('[{"variable": "OTHER", "description": "x"}]', encoding="utf-8")
    website = _site(tmp_path)
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    # Was "Configures bar.", which reads as finished while saying nothing.
    assert _params(website, "node-scenarios")["BAR"]["description"] == ""


def test_source_wins_over_the_committed_file(tmp_path):
    hub = tmp_path / "hub"
    scn = hub / "node-scenarios"
    scn.mkdir(parents=True)
    (scn / "env.sh").write_text('export FOO="${FOO:-x}"\n', encoding="utf-8")
    (scn / "krknctl-input.json").write_text('[{"variable": "FOO", "description": "from json"}]', encoding="utf-8")
    website = _site(tmp_path)
    out = website / "data/params/node-scenarios"
    out.mkdir(parents=True)
    (out / "krkn-hub.yaml").write_text(
        "# Generated by krkn-docs-bot. Do not edit by hand.\n"
        "source_repo: krkn-hub\nsource_ref: HEAD\n"
        "params:\n- name: FOO\n  description: hand written desc\n  default: x\n",
        encoding="utf-8")
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    # krknctl is the other tab's source, so it ranks below the committed file.
    # A borrow it did write is marked and dropped, so it never freezes.
    assert _params(website, "node-scenarios")["FOO"]["description"] == "hand written desc"


def test_a_borrowed_description_does_not_freeze(tmp_path):
    """Marked as a borrow, so the next run re-derives it and a better krknctl
    line reaches the docs instead of the file pinning the first one."""
    hub = tmp_path / "hub"
    scn = hub / "node-scenarios"
    scn.mkdir(parents=True)
    (scn / "env.sh").write_text('export FOO="${FOO:-x}"\n', encoding="utf-8")
    ctl = scn / "krknctl-input.json"
    ctl.write_text('[{"variable": "FOO", "description": "first"}]', encoding="utf-8")
    website = _site(tmp_path)
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    assert _params(website, "node-scenarios")["FOO"]["description_source"] == "krknctl"
    ctl.write_text('[{"variable": "FOO", "description": "second"}]', encoding="utf-8")
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    assert _params(website, "node-scenarios")["FOO"]["description"] == "second"


def _write_env(scn_dir):
    scn_dir.mkdir(parents=True, exist_ok=True)
    (scn_dir / "env.sh").write_text(
        'export ACTION="${ACTION:-node_stop}"\n'
        'export NEW_ONE="${NEW_ONE:-x}"\n', encoding="utf-8")


def test_emit_then_reemit_is_byte_identical(tmp_path):
    hub = tmp_path / "hub"
    _write_env(hub / "node-scenarios")
    website = tmp_path / "site"
    (website / "content/en/docs/scenarios").mkdir(parents=True)
    (website / "content/en/docs/scenarios/all-scenario-env.md").write_text("", encoding="utf-8")

    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    out = website / "data/params/node-scenarios/krkn-hub.yaml"
    first = out.read_text(encoding="utf-8")

    # A blank description is falsy, so an undescribed param goes to the resolver
    # on every run. The resolver is a no-op here, so the bytes still match.
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    assert out.read_text(encoding="utf-8") == first


def test_an_env_comment_reaches_the_krknctl_tab_too(tmp_path):
    """Otherwise a maintainer follows the report's advice, adds the comment, and
    the next report still calls the param blank on the other tab."""
    hub = tmp_path / "hub"
    scn = hub / "node-scenarios"
    scn.mkdir(parents=True)
    (scn / "env.sh").write_text(
        'export FOO=${FOO:=1}   # Seconds to wait before giving up\n', encoding="utf-8")
    (scn / "krknctl-input.json").write_text(
        '[{"name": "foo", "variable": "FOO", "type": "number"}]', encoding="utf-8")
    website = _site(tmp_path)
    doc_bot.run(scenario="node-scenarios", krkn_hub_root=hub, website_root=website)
    for source in ("krkn-hub", "krknctl"):
        rows = _params(website, "node-scenarios", source)
        assert rows["FOO"]["description"] == "Seconds to wait before giving up", source
