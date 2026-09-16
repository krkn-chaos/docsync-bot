from bot.scaffold import (_first_cell, _is_param_table, _row_cells, inject_shortcode, published_cell,
                          published_table, scaffold_scenario)


def _data(website, scenario, source="krkn-hub"):
    d = website / "data/params" / scenario
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{source}.yaml").write_text("params: []\n", encoding="utf-8")


def _make_page(website, relpath, source_id=None, tab_source="krkn-hub"):
    d = website / "content/en/docs/scenarios" / relpath
    d.mkdir(parents=True, exist_ok=True)
    idx = "---\ntitle: X\n---\n"
    if source_id is not None:
        idx += f'<krkn-hub-scenario id="{source_id}">\n</krkn-hub-scenario>\n'
    (d / "_index.md").write_text(idx, encoding="utf-8")
    tab = d / f"_tab-{tab_source}.md"
    tab.write_text(
        "#### Supported parameters\n\n"
        "| Parameter | Description | Default |\n"
        "| --------- | ----------- | ------- |\n"
        "| ACTION | Action to run. | x |\n\n"
        "keep this prose.\n",
        encoding="utf-8",
    )
    return tab


def test_scaffold_finds_page_by_krkn_hub_id_when_dir_name_differs(tmp_path):
    website = tmp_path / "site"
    tab = _make_page(website, "hog-scenarios/cpu-hog-scenario", source_id="node-cpu-hog")
    _data(website, "node-cpu-hog", "krkn-hub")
    scaffold_scenario("node-cpu-hog", website)
    out = tab.read_text(encoding="utf-8")
    assert '{{< param-table scenario="node-cpu-hog" source="krkn-hub" >}}' in out
    assert "| ACTION |" not in out
    assert "keep this prose." in out


def test_scaffold_falls_back_to_dir_name_when_id_disagrees(tmp_path):
    website = tmp_path / "site"
    tab = _make_page(website, "pvc-scenario", source_id="pvc-scenarios")
    _data(website, "pvc-scenario", "krkn-hub")
    scaffold_scenario("pvc-scenario", website)
    assert '{{< param-table scenario="pvc-scenario" source="krkn-hub" >}}' in tab.read_text(encoding="utf-8")


def test_scaffold_does_not_match_dir_name_by_substring(tmp_path):
    website = tmp_path / "site"
    tab = _make_page(website, "node-scenarios", source_id="node-scenarios")
    scaffold_scenario("node", website)
    assert "param-table" not in tab.read_text(encoding="utf-8")


def test_scaffold_creates_page_when_none_exists(tmp_path):
    website = tmp_path / "site"
    (website / "content/en/docs/scenarios").mkdir(parents=True)
    _data(website, "brand-new-scenario", "krkn-hub")
    _data(website, "brand-new-scenario", "krknctl")
    scaffold_scenario("brand-new-scenario", website)
    page = website / "content/en/docs/scenarios/brand-new-scenario"
    idx = (page / "_index.md").read_text(encoding="utf-8")
    assert '<krkn-hub-scenario id="brand-new-scenario">' in idx
    assert 'readfile file="_tab-krkn-hub.md"' in idx
    krkn_hub_tab = (page / "_tab-krkn-hub.md").read_text(encoding="utf-8")
    assert '{{< param-table scenario="brand-new-scenario" source="krkn-hub" >}}' in krkn_hub_tab
    krknctl_tab = (page / "_tab-krknctl.md").read_text(encoding="utf-8")
    assert '{{< param-table scenario="brand-new-scenario" source="krknctl" prefix="--" >}}' in krknctl_tab


def test_scaffold_only_creates_tabs_for_sources_with_data(tmp_path):
    website = tmp_path / "site"
    (website / "content/en/docs/scenarios").mkdir(parents=True)
    _data(website, "rollback", "krknctl")   # only krknctl has data, no env params
    scaffold_scenario("rollback", website)
    page = website / "content/en/docs/scenarios/rollback"
    assert (page / "_tab-krknctl.md").exists()
    assert not (page / "_tab-krkn-hub.md").exists()
    idx = (page / "_index.md").read_text(encoding="utf-8")
    assert 'readfile file="_tab-krknctl.md"' in idx
    assert 'readfile file="_tab-krkn-hub.md"' not in idx

TAB = """\
#### Supported parameters

| Parameter | Description | Type | Default |
| --------- | ----------- | ---- | ------- |
| ACTION | Action to run. | enum | node_stop |

**NOTE** keep this prose.
"""


def test_replaces_table_with_shortcode_and_keeps_prose():
    out = inject_shortcode(TAB, scenario="node-scenarios", source="krkn-hub")
    assert '{{< param-table scenario="node-scenarios" source="krkn-hub" >}}' in out
    assert "| ACTION |" not in out
    assert "#### Supported parameters" in out
    assert "**NOTE** keep this prose." in out


def test_the_krknctl_tab_call_carries_the_flag_prefix():
    """The data stores a bare flag but a reader types --telemetry-enabled."""
    out = inject_shortcode(TAB, scenario="node-scenarios", source="krknctl")
    assert 'prefix="--"' in out


def test_the_krkn_hub_tab_call_does_not():
    """env.sh params are env vars and take no prefix."""
    out = inject_shortcode(TAB, scenario="node-scenarios", source="krkn-hub")
    assert "prefix" not in out


PUBLISHED = """\
Parameter | Description | Type | Default
--------- | ----------- | ---- | -------
ACTION    | Do a thing  | enum | stop
TIMEOUT   |             | number | 180
"""

SECOND_GROUP = """\
Parameter | Description | Default
--------- | ----------- | -------
SIGNAL_STATE | Waits for the RUN signal | RUN
"""


def test_published_table_keys_rows_on_the_parameter():
    """Headers travel per row: two tables on one page need not match."""
    rows = published_table(PUBLISHED)
    assert set(rows) == {"ACTION", "TIMEOUT"}
    headers, cells = rows["ACTION"]
    assert headers == ["parameter", "description", "type", "default"]
    assert cells[1] == "Do a thing"


def test_published_table_reads_every_table_on_the_page():
    """The global pages carry one table per group, not one per page."""
    rows = published_table(PUBLISHED + "\n" + SECOND_GROUP)
    assert set(rows) == {"ACTION", "TIMEOUT", "SIGNAL_STATE"}
    assert published_cell(rows, "SIGNAL_STATE", "description") == "Waits for the RUN signal"


def test_published_cell_on_a_column_the_table_does_not_have():
    """The global pages have no Type column at all."""
    rows = published_table(SECOND_GROUP)
    assert published_cell(rows, "SIGNAL_STATE", "type") == ""


def test_published_table_strips_the_flag_prefix():
    """The krknctl page lists --action; the data file keys name on ACTION."""
    rows = published_table("Parameter | Description\n--- | ---\n`--action` | Do it\n")
    assert set(rows) == {"action"}


def test_published_table_on_a_page_with_no_table():
    assert published_table("just prose\n") == {}


def test_idempotent_when_already_migrated():
    once = inject_shortcode(TAB, "node-scenarios", "krkn-hub")
    twice = inject_shortcode(once, "node-scenarios", "krkn-hub")
    assert once == twice


BARE_TAB = """\
#### Supported parameters

See list of variables [here](all-scenario-env.md)

Parameter               | Description                   | Type   | Default
----------------------- | ----------------------------- | ------ | -------
ACTION                  | Action to run.                | enum   | node_stop_start_scenario
LABEL_SELECTOR          | Node label to target          | string | node-role.kubernetes.io/worker

{{% alert title="Note" %}} some note {{% /alert %}}
"""


def test_bare_table_replaced():
    out = inject_shortcode(BARE_TAB, "node-scenarios", "krkn-hub")
    assert '{{< param-table scenario="node-scenarios" source="krkn-hub" >}}' in out
    assert "ACTION" not in out
    assert "#### Supported parameters" in out
    assert "{{% alert" in out


def test_bare_table_idempotent():
    once = inject_shortcode(BARE_TAB, "node-scenarios", "krkn-hub")
    twice = inject_shortcode(once, "node-scenarios", "krkn-hub")
    assert once == twice


def test_frontmatter_is_not_mistaken_for_a_table():
    """--- passes the separator shape test, and a pipe in a metadata value
    satisfied the guard, so the closing fence and a title line were deleted."""
    page = ("---\ntitle: Node Scenarios\ndescription: Chaos | node\n---\n\n"
            "| Parameter | Description |\n| --- | --- |\n| DUR | how long |\n")
    out = inject_shortcode(page, "node-scenarios", "krkn-hub")
    assert out.startswith("---\ntitle: Node Scenarios\ndescription: Chaos | node\n---\n")
    assert "param-table" in out


def test_a_table_that_is_not_parameters_is_left_alone():
    """A tab's first table can be prerequisites. Replacing it deleted that table
    and left the real one behind as a stale duplicate, permanently."""
    page = ("## Prerequisites\n\n| Requirement | Notes |\n| --- | --- |\n"
            "| kubectl | in PATH |\n\n## Parameters\n\n"
            "| Parameter | Description |\n| --- | --- |\n| DUR | how long |\n")
    out = inject_shortcode(page, "x", "krkn-hub")
    assert "| kubectl | in PATH |" in out
    assert "| DUR | how long |" not in out


TWO_TABLES = """\
##### Egress Scenarios

| Parameter | Description |
| --- | --- |
| EGRESS | shape it |

##### Ingress Scenarios

| Parameter | Description |
| --- | --- |
| WAIT_DURATION | how long |
"""


def test_a_page_with_two_parameter_tables_is_left_alone():
    """Replacing one strands the other, and no later run comes back for it: the
    idempotency guard sees the call that got written. See docsync-bot#36."""
    out = inject_shortcode(TWO_TABLES, "network-chaos", "krkn-hub")
    assert out == TWO_TABLES


def _two_table_page(tmp_path, params):
    website = tmp_path / "site"
    d = website / "content/en/docs/scenarios/network-chaos"
    d.mkdir(parents=True)
    (d / "_index.md").write_text("---\ntitle: X\n---\n", encoding="utf-8")
    (d / "_tab-krkn-hub.md").write_text(TWO_TABLES, encoding="utf-8")
    data = website / "data/params/network-chaos"
    data.mkdir(parents=True)
    (data / "krkn-hub.yaml").write_text(params, encoding="utf-8")
    return website, d / "_tab-krkn-hub.md"


def test_two_tables_are_split_by_the_groups_the_source_declares(tmp_path):
    """Which table is which comes from the source, so the bot can finish the job
    instead of handing it back. See docsync-bot#36."""
    website, tab = _two_table_page(tmp_path, """params:
  - name: EGRESS
    description: shape it
    group: egress
  - name: WAIT_DURATION
    description: how long
    group: ingress
""")
    report = scaffold_scenario("network-chaos", website)
    out = tab.read_text(encoding="utf-8")
    assert '{{< param-table scenario="network-chaos" source="krkn-hub" group="egress" >}}' in out
    assert '{{< param-table scenario="network-chaos" source="krkn-hub" group="ingress" >}}' in out
    assert "| EGRESS |" not in out and "| WAIT_DURATION |" not in out
    assert report == ["network-chaos/_tab-krkn-hub.md: egress: replaced 1 rows",
                      "network-chaos/_tab-krkn-hub.md: ingress: replaced 1 rows"]


def test_a_page_is_split_all_or_nothing(tmp_path):
    """One table resolving and the other not would leave a call beside a table,
    which is the half-converted page this whole change is about."""
    website, tab = _two_table_page(tmp_path, """params:
  - name: EGRESS
    description: shape it
    group: egress
  - name: WAIT_DURATION
    description: how long
""")
    report = scaffold_scenario("network-chaos", website)
    assert tab.read_text(encoding="utf-8") == TWO_TABLES
    assert report == ["network-chaos/_tab-krkn-hub.md: 2 parameter tables, left "
                      "alone. Give each param a group in the source, then split "
                      "the page by group"]


def test_a_scenario_page_gains_no_appended_section(tmp_path):
    """The global pages append a section for a group no table claims. A scenario
    tab is read into a tabpane, so a new ## heading there is out of place."""
    website, tab = _two_table_page(tmp_path, """params:
  - name: EGRESS
    description: shape it
    group: egress
  - name: WAIT_DURATION
    description: how long
    group: ingress
  - name: BMC_USER
    description: bmc
    group: baremetal
""")
    scaffold_scenario("network-chaos", website)
    out = tab.read_text(encoding="utf-8")
    assert "## Baremetal" not in out
    assert 'group="baremetal"' not in out


def test_two_tables_stay_put_when_the_source_declares_no_groups(tmp_path):
    """Nothing says which table is which, so guessing would strand rows."""
    website, tab = _two_table_page(tmp_path, """params:
  - name: EGRESS
    description: shape it
  - name: WAIT_DURATION
    description: how long
""")
    report = scaffold_scenario("network-chaos", website)
    assert tab.read_text(encoding="utf-8") == TWO_TABLES
    assert report == ["network-chaos/_tab-krkn-hub.md: 2 parameter tables, left "
                      "alone. Give each param a group in the source, then split "
                      "the page by group"]


def test_scaffold_reports_nothing_for_a_single_table_page(tmp_path):
    website = tmp_path / "site"
    tab = _make_page(website, "pvc-scenario", source_id="pvc-scenario")
    _data(website, "pvc-scenario", "krkn-hub")
    assert scaffold_scenario("pvc-scenario", website) == []
    assert "param-table" in tab.read_text(encoding="utf-8")


def test_an_argument_header_is_a_parameter_table():
    """7 of the 52 published tabs head the column Argument, not Parameter."""
    page = "| Argument | Description |\n| --- | --- |\n| DUR | how long |\n"
    assert "param-table" in inject_shortcode(page, "x", "krkn-hub")


def test_an_escaped_pipe_stays_in_its_cell():
    r"""A \| inside a description split the row, shifting every column right so
    Type read the tail of the description and then froze in the data file."""
    assert _row_cells(r"| MODE | one of a \| b | string |") == \
        ["MODE", "one of a | b", "string"]


def test_a_description_keeps_its_trailing_code_span():
    """Stripping the row's outer backticks truncated the span and unbalanced the
    rest of the cell. The real case: website#616 flagged RESILIENCY_FILE."""
    row = ("| `RESILIENCY_FILE` | Path to a YAML file containing SLO definitions; "
           "defaults to the alerts profile or `config/alerts.yaml` | config/alerts.yaml |")
    cells = _row_cells(row)
    assert cells[1].endswith("`config/alerts.yaml`")
    assert cells[1].count("`") % 2 == 0


def test_a_name_cell_is_still_bare():
    cells = _row_cells("| `RESILIENCY_FILE` | prose | x |")
    assert cells[0] == "`RESILIENCY_FILE`", "the raw cell keeps its formatting"
    assert _first_cell("| `RESILIENCY_FILE` | prose | x |") == "RESILIENCY_FILE"
    assert _first_cell("| `--telemetry-enabled` | prose | x |") == "telemetry-enabled"


def test_a_backticked_header_still_marks_a_param_table():
    assert _is_param_table("| `Parameter` | Description | Default |")
    assert _is_param_table("| Parameter | Description | Default |")
    assert not _is_param_table("| Step | Notes |")


HALF_CONVERTED = """##### Egress Scenarios

{{< param-table scenario="network-chaos" source="krkn-hub" >}}

##### Ingress Scenarios

| Parameter | Description |
| --- | --- |
| WAIT_DURATION | how long |
"""


def test_scaffold_reports_a_half_converted_page(tmp_path):
    """One call and one table left is the state the old bug produced. The
    idempotency guard skips the page, so nothing else would ever mention it."""
    website = tmp_path / "site"
    d = website / "content/en/docs/scenarios/network-chaos"
    d.mkdir(parents=True)
    (d / "_index.md").write_text("---\ntitle: X\n---\n", encoding="utf-8")
    (d / "_tab-krkn-hub.md").write_text(HALF_CONVERTED, encoding="utf-8")
    _data(website, "network-chaos", "krkn-hub")
    report = scaffold_scenario("network-chaos", website)
    assert (d / "_tab-krkn-hub.md").read_text(encoding="utf-8") == HALF_CONVERTED
    assert report == ["network-chaos/_tab-krkn-hub.md: a param-table call and 1 "
                      "hand-written table(s), left alone. Give each param a group "
                      "in the source, then split the page by group"]


def test_a_fully_converted_page_is_not_reported(tmp_path):
    website = tmp_path / "site"
    d = website / "content/en/docs/scenarios/pvc-scenario"
    d.mkdir(parents=True)
    (d / "_index.md").write_text("---\ntitle: X\n---\n", encoding="utf-8")
    (d / "_tab-krkn-hub.md").write_text(
        '{{< param-table scenario="pvc-scenario" source="krkn-hub" >}}\n', encoding="utf-8")
    _data(website, "pvc-scenario", "krkn-hub")
    assert scaffold_scenario("pvc-scenario", website) == []
