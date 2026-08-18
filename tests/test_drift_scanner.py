from bot import drift_scanner as ds


def _mk(tmp_path, env=None, krknctl=None, table=None, scenario="demo"):
    """Build a mini krkn-hub + website. Returns (krkn_hub_root, website_root)."""
    hub = tmp_path / "hub" / scenario
    hub.mkdir(parents=True)
    if env is not None:
        (hub / "env.sh").write_text(env, encoding="utf-8")
    if krknctl is not None:
        (hub / "krknctl-input.json").write_text(krknctl, encoding="utf-8")
    web = tmp_path / "web"
    (web / "content/en/docs/scenarios").mkdir(parents=True)
    if table is not None:
        d = web / "data/params" / scenario
        d.mkdir(parents=True)
        (d / "krkn-hub.yaml").write_text(table, encoding="utf-8")
    return tmp_path / "hub", web


def _hub(tmp_path, **kw):
    hub, web = _mk(tmp_path, **kw)
    return [f for f in ds.scenario_findings("demo", hub, web) if f.source == "krkn-hub"]


def test_missing_table(tmp_path):
    fs = _hub(tmp_path, env='export FOO=${FOO:="bar"}\n')
    assert [f.kind for f in fs] == ["missing-table"]
    assert "FOO" in fs[0].new


def test_stale_default(tmp_path):
    fs = _hub(tmp_path, env='export FOO=${FOO:="new"}\n',
              table="params:\n  - name: FOO\n    default: old\n")
    assert any(f.kind == "stale" and f.param == "FOO"
               and f.old == "old" and f.new == "new" for f in fs)


def test_missing_param(tmp_path):
    fs = _hub(tmp_path,
              env='export FOO=${FOO:="bar"}\nexport BAZ=${BAZ:="1"}\n',
              table="params:\n  - name: FOO\n    default: bar\n")
    assert any(f.kind == "missing" and f.param == "BAZ" and f.new == "1" for f in fs)


def test_extra_param(tmp_path):
    fs = _hub(tmp_path, env='export FOO=${FOO:="bar"}\n',
              table="params:\n  - name: FOO\n    default: bar\n  - name: OLD\n    default: x\n")
    assert any(f.kind == "extra" and f.param == "OLD" for f in fs)


def test_no_drift_when_table_matches(tmp_path):
    fs = _hub(tmp_path, env='export FOO=${FOO:="bar"}\n',
              table="params:\n  - name: FOO\n    default: bar\n")
    assert fs == []


def test_skips_global_params(tmp_path):
    """A param the root env.sh declares with the same default is global, so a
    per-scenario table must not repeat it."""
    hub, web = _mk(tmp_path,
                   env='export WAIT_DURATION=${WAIT_DURATION:="60"}\nexport LOCAL=${LOCAL:="1"}\n',
                   table="params:\n  - name: LOCAL\n    default: '1'\n")
    (hub / "env.sh").write_text('export WAIT_DURATION=${WAIT_DURATION:="60"}\n', encoding="utf-8")
    fs = ds.scenario_findings("demo", hub, web, krkn_root=tmp_path / "no-krkn")
    assert all(f.param != "WAIT_DURATION" for f in fs), "global leaked into a scenario table"
    assert [f.kind for f in fs if f.source == "krkn-hub"] == [], "LOCAL should be in sync"


def test_a_global_the_scenario_overrides_is_not_skipped(tmp_path):
    """network-chaos sets WAIT_DURATION=300 against a global 60. Skipping on the
    name alone hid it, and the globals page then stated the wrong default."""
    hub, web = _mk(tmp_path,
                   env='export WAIT_DURATION=${WAIT_DURATION:="300"}\n',
                   table="params: []\n")
    (hub / "env.sh").write_text('export WAIT_DURATION=${WAIT_DURATION:="60"}\n', encoding="utf-8")
    fs = ds.scenario_findings("demo", hub, web, krkn_root=tmp_path / "no-krkn")
    assert [f.param for f in fs if f.source == "krkn-hub"] == ["WAIT_DURATION"]


def test_format_report_structure_and_no_emdash(tmp_path):
    body = ds.format_report(_hub(tmp_path, env='export FOO=${FOO:="bar"}\n'))
    assert "—" not in body and "–" not in body and "→" not in body
    assert "#### demo" in body
    assert "- [ ]" in body
    assert "/fix demo" in body
    assert "source:" in body


def _box(body, scenario):
    import re
    m = re.search(rf"drift:{scenario} -->\n#### {scenario}\n(- \[.\])", body)
    return m.group(1)


def test_tick_preserved_per_scenario_not_by_shared_text():
    # two scenarios with identical summary text (both missing a krkn-hub table)
    a = ds.Finding("alpha", "krkn-hub", "missing-table", new="X", source_file="u", table_file="t")
    b = ds.Finding("beta", "krkn-hub", "missing-table", new="X", source_file="u", table_file="t")
    first = ds.format_report([a, b])
    assert first.count("- [ ]") == 2
    # tick only alpha
    prev = first.replace("#### alpha\n- [ ]", "#### alpha\n- [x]", 1)
    second = ds.format_report([a, b], prev_body=prev)
    assert _box(second, "alpha") == "- [x]"
    assert _box(second, "beta") == "- [ ]"   # shared text must NOT tick beta


def test_a_tick_clears_when_new_drift_appears():
    """A tick says the drift it was next to has been handled. Later findings must
    not hide behind it."""
    a = ds.Finding("alpha", "krkn-hub", "stale", "X", old="1", new="2",
                   source_file="u", table_file="t")
    prev = ds.format_report([a]).replace("- [ ]", "- [x]", 1)
    assert _box(ds.format_report([a], prev_body=prev), "alpha") == "- [x]"

    b = ds.Finding("alpha", "krknctl", "stale", "Y", old="1", new="2",
                   source_file="u", table_file="t")
    assert _box(ds.format_report([a, b], prev_body=prev), "alpha") == "- [ ]"


def test_empty_findings_all_clear():
    assert ds.format_report([]) == "### Docs drift report\n\nNo drift found.\n"


def test_find_scenarios_from_markers(tmp_path):
    d = tmp_path / "content/en/docs/scenarios/node"
    d.mkdir(parents=True)
    (d / "_index.md").write_text('<krkn-hub-scenario id="node-scenarios" />\n', encoding="utf-8")
    assert ds.find_scenarios(tmp_path) == ["node-scenarios"]


# --- global parameter drift ------------------------------------------------

def _globals_sources(tmp_path):
    """A mini krkn-hub root env.sh + krkn containers/krknctl-input.json."""
    hub = tmp_path / "hub"
    hub.mkdir(parents=True, exist_ok=True)
    (hub / "env.sh").write_text('export CERBERUS_ENABLED=${CERBERUS_ENABLED:=False}\n',
                                encoding="utf-8")
    c = tmp_path / "krkn" / "containers"
    c.mkdir(parents=True)
    (c / "krknctl-input.json").write_text(
        '[{"name": "cerberus-enabled", "variable": "CERBERUS_ENABLED",'
        ' "group": "cerberus", "default": "False"}]', encoding="utf-8")
    return hub, tmp_path / "krkn"


def test_global_missing_table_is_reported(tmp_path):
    hub, krkn = _globals_sources(tmp_path)
    web = tmp_path / "web"
    fs = ds.global_findings(hub, krkn, web)
    assert {f.kind for f in fs} == {"missing-table"}
    assert all(f.scenario == "globals" for f in fs)
    assert {f.source for f in fs} == {"krknctl-cerberus", "krkn-hub-cerberus"}


def test_global_stale_default_is_reported(tmp_path):
    hub, krkn = _globals_sources(tmp_path)
    web = tmp_path / "web"
    d = web / "data/params/globals"
    d.mkdir(parents=True)
    (d / "krknctl.yaml").write_text(
        "params:\n  - name: cerberus-enabled\n    group: cerberus\n    default: True\n",
        encoding="utf-8")
    (d / "krkn-hub.yaml").write_text(
        "params:\n  - name: CERBERUS_ENABLED\n    group: cerberus\n    default: False\n",
        encoding="utf-8")
    fs = ds.global_findings(hub, krkn, web)
    assert any(f.kind == "stale" and f.param == "cerberus-enabled"
               and f.old == "True" and f.new == "False" for f in fs)


def test_globals_get_their_own_checkbox(tmp_path):
    hub, krkn = _globals_sources(tmp_path)
    body = ds.format_report(ds.global_findings(hub, krkn, tmp_path / "web"))
    assert "#### globals" in body
    assert "/fix globals" in body


# --- readability and confidence -------------------------------------------

def _mkf(kind, source="krknctl-telemetry", param=None, new=None, old=None):
    return ds.Finding("globals", source, kind, param, old, new, "u", "t")


def test_only_derived_kinds_are_marked_safe():
    fs = [_mkf("missing-table", new="a, b"), _mkf("stale", param="x", old="1", new="2")]
    assert "Safe to regenerate" in ds._scenario_summary(fs)


def test_a_removed_param_is_marked_as_needing_a_look():
    """extra is the only kind where /fix deletes a documented row."""
    fs = [_mkf("stale", param="x", old="1", new="2"), _mkf("extra", param="GONE", old="9")]
    s = ds._scenario_summary(fs)
    assert "Review first" in s and "1 param" in s
    assert "Safe to regenerate" not in s
    # /fix does remove the row, so this asks for a look, not for a maintainer.
    assert "Maintainer needed" not in s


def test_long_group_lists_are_collapsed_not_inlined():
    fs = [_mkf("missing-table", source=f"krknctl-g{i}", new="a, b, c") for i in range(9)]
    body = ds.format_report(fs)
    assert "<details>" in body, "long lists must collapse"
    assert body.count("krknctl-g0") >= 1


def test_global_findings_honour_the_fork_urls(tmp_path):
    hub, krkn = _globals_sources(tmp_path)
    fs = ds.global_findings(hub, krkn, tmp_path / "web",
                            hub_url="https://github.com/fork/krkn-hub/blob/main",
                            krkn_url="https://github.com/fork/krkn/blob/main")
    assert all("fork/" in f.source_file for f in fs), "must not hardcode krkn-chaos"


def test_a_group_missing_from_a_shared_file_is_still_missing_table(tmp_path):
    """One file per source: a group with no rows in it must read as missing-table,
    not as an empty in-sync table."""
    hub, krkn = _globals_sources(tmp_path)
    web = tmp_path / "web"
    d = web / "data/params/globals"
    d.mkdir(parents=True)
    # file exists but holds only an unrelated group
    (d / "krknctl.yaml").write_text(
        "params:\n  - name: other-thing\n    group: telemetry\n    default: x\n",
        encoding="utf-8")
    (d / "krkn-hub.yaml").write_text("params: []\n", encoding="utf-8")
    fs = ds.global_findings(hub, krkn, web)
    ctl = [f for f in fs if f.source == "krknctl-cerberus"]
    assert [f.kind for f in ctl] == ["missing"], "cerberus rows absent -> reported"


def _f(scenario, source="krkn-hub", kind="missing", target=None, param="P"):
    f = ds.Finding(scenario, source, kind, param, source_file="s", table_file="t")
    f.target = target
    return f


def test_each_source_gets_its_own_collapsed_section():
    """Every source drifting at once is hundreds of lines, so the reader opens the
    one they care about instead of scrolling past the rest."""
    md = ds.format_report([_f("node-scenarios"),
                           _f("globals"),
                           _f("krknusers", source="spec", target="operator")])
    assert "<summary><b>krkn-hub scenarios</b> (1)</summary>" in md
    assert "<summary><b>Global parameters</b> (1)</summary>" in md
    assert "<summary><b>krkn-operator CRDs</b> (1)</summary>" in md
    # Fixed order, so the body only changes when the findings do.
    assert (md.index("krkn-hub scenarios</b>") < md.index("Global parameters</b>")
            < md.index("krkn-operator CRDs</b>"))


def test_a_source_with_no_drift_gets_no_section():
    md = ds.format_report([_f("node-scenarios")])
    assert md.count("<details><summary>") == 1
    assert "krkn-operator CRDs" not in md


def test_a_tick_survives_the_move_into_a_collapsed_section():
    """The marker, not the layout, is what a tick is keyed on, so regrouping must
    not silently untick everything a maintainer already handled."""
    first = ds.format_report([_f("node-scenarios")])
    ticked = first.replace("- [ ]", "- [x]", 1)
    again = ds.format_report([_f("node-scenarios")], prev_body=ticked)
    assert "- [x]" in again


def test_a_tick_from_the_old_flat_layout_still_counts():
    """The rolling issue predates the collapsed sections, so the first run after
    this change reads a body that has no <details> in it at all."""
    fs = [_f("node-scenarios")]
    label = ds.format_report(fs).split("- [ ] ", 1)[1].splitlines()[0]
    flat = ("### Docs drift report\n\n"
            "<!-- drift:node-scenarios -->\n"
            "#### node-scenarios\n"
            f"- [x] {label}\n")
    assert "- [x]" in ds.format_report(fs, prev_body=flat)


def _unlinked(scenario, why="no hand-written page is mapped to it"):
    f = ds.Finding(scenario, "page", "unlinked", None, None, why, "s", "t")
    f.target = "operator"
    return f


def test_the_group_header_counts_what_needs_a_maintainer():
    """A red marker inside a collapsed group is invisible, which would defeat the
    collapse. Only unlinked counts: /fix handles everything else."""
    md = ds.format_report([_unlinked("krknusers"), _unlinked("krknwebhooks"),
                           _f("krkngraphruns", kind="missing-link", target="operator")])
    assert "<b>krkn-operator CRDs</b> (3) · 🔴 2 need a maintainer" in md


def test_one_maintainer_item_reads_as_singular():
    md = ds.format_report([_unlinked("krknusers")])
    assert "🔴 1 needs a maintainer" in md


def test_a_clean_group_header_stays_a_bare_count():
    """No suffix when nothing is blocked, so the body only changes with findings."""
    md = ds.format_report([_f("node-scenarios"), _f("pod-scenarios")])
    assert "<b>krkn-hub scenarios</b> (2)</summary>" in md
    assert "🔴" not in md


def test_a_tick_set_before_the_marker_existed_comes_back_unticked():
    """Labels changed, so every box resets once. It has to reset rather than
    carry over: the old label made a claim about /fix that was wrong."""
    fs = [_unlinked("krknusers")]
    old = ("### Docs drift report\n\n<!-- drift:krknusers -->\n#### krknusers\n"
           "- [x] reference page exists but nothing links to it. **Needs a human**\n")
    assert "- [ ]" in ds.format_report(fs, prev_body=old)
