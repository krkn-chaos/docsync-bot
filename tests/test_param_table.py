from pathlib import Path

from bs4 import BeautifulSoup

EXAMPLES = Path(__file__).resolve().parents[1] / "website-template" / "examples" / "data" / "params"


def headers(html):
    soup = BeautifulSoup(html, "html.parser")
    table = soup.select_one("table.krkn-param-table")
    assert table is not None, "no krkn-param-table rendered"
    return [th.get_text(strip=True) for th in table.select("thead th")]


def cells(html, row=0):
    soup = BeautifulSoup(html, "html.parser")
    tr = soup.select("table.krkn-param-table tbody tr")[row]
    return [td.get_text(strip=True) for td in tr.select("td")]


def no_table(html):
    return BeautifulSoup(html, "html.parser").select_one("table.krkn-param-table") is None


def test_param_and_description_always_render(site):
    site.data("svc", "krkn-hub", """\
params:
  - name: SCENARIO_BASE64
    description: Base64 encoded scenario file.
""")
    rel = site.page("svc", "svc", "krkn-hub")
    proc = site.build()
    assert proc.returncode == 0, proc.stderr
    assert headers(site.html(rel)) == ["Parameter", "Description"]


FOUR_COL = """\
params:
  - name: ACTION
    description: Action to run.
    type: enum
    default: node_stop_start_scenario
  - name: TIMEOUT
    description: Seconds to wait.
    type: number
    default: 180
"""


def test_four_column(site):
    site.data("node", "krkn-hub", FOUR_COL)
    rel = site.page("node", "node", "krkn-hub")
    proc = site.build()
    assert proc.returncode == 0, proc.stderr
    assert headers(site.html(rel)) == ["Parameter", "Description", "Type", "Default"]


def test_default_only_three_column(site):
    site.data("c", "krkn-hub", """\
params:
  - name: FOO
    description: A foo.
    default: bar
""")
    rel = site.page("c", "c", "krkn-hub")
    assert site.build().returncode == 0
    assert headers(site.html(rel)) == ["Parameter", "Description", "Default"]


def test_type_only_three_column(site):
    site.data("t", "krkn-hub", """\
params:
  - name: FOO
    description: A foo.
    type: string
""")
    rel = site.page("t", "t", "krkn-hub")
    assert site.build().returncode == 0
    assert headers(site.html(rel)) == ["Parameter", "Description", "Type"]


# numeric-zero default and required-false must not be dropped by falsy guards

def test_numeric_zero_default_renders(site):
    site.data("z", "krkn-hub", """\
params:
  - name: RETRIES
    description: How many retries.
    type: number
    default: 0
""")
    rel = site.page("z", "z", "krkn-hub")
    assert site.build().returncode == 0
    assert cells(site.html(rel)) == ["RETRIES", "How many retries.", "number", "0"]


def test_required_false_shows_and_renders(site):
    site.data("r", "krknctl", """\
params:
  - name: FLAG
    description: A flag.
    required: false
""")
    rel = site.page("r", "r", "krknctl")
    assert site.build().returncode == 0
    assert headers(site.html(rel)) == ["Parameter", "Description", "Required"]
    # Yes/No, not true/false: a docs table is read by people, not parsed.
    assert cells(site.html(rel)) == ["FLAG", "A flag.", "No"]


def test_mixed_rows_empty_cells(site):
    site.data("m", "krkn-hub", """\
params:
  - name: A
    description: Has type and default.
    type: string
    default: x
  - name: B
    description: Has neither.
""")
    rel = site.page("m", "m", "krkn-hub")
    assert site.build().returncode == 0
    assert headers(site.html(rel)) == ["Parameter", "Description", "Type", "Default"]
    # A dash, not a blank: an empty cell reads as an oversight in the table.
    assert cells(site.html(rel), row=1) == ["B", "Has neither.", "-", "-"]


# krknctl possible_values and required columns

def test_possible_values_slash_joined(site):
    site.data("k", "krknctl", """\
params:
  - name: CLOUD_TYPE
    description: Cloud platform.
    type: enum
    possible_values: [aws, gcp, azure]
    default: aws
    required: true
""")
    rel = site.page("k", "k", "krknctl")
    assert site.build().returncode == 0
    # Possible Values sits last: it is the sparsest column, so leading with it
    # pushed Default and Required off to the right on the widest tables.
    assert headers(site.html(rel)) == [
        "Parameter", "Description", "Type", "Default", "Required", "Possible Values",
    ]
    # Slash-joined: a comma reads as part of the value when a value contains one.
    assert cells(site.html(rel)) == [
        "CLOUD_TYPE", "Cloud platform.", "enum", "aws", "Yes", "aws/gcp/azure",
    ]


def test_a_flag_is_shown_instead_of_the_name(site):
    """The krknctl page lists CLI flags, but name stays the env var in the data
    so drift_scanner and the skip list keep matching on it."""
    site.data("f", "krknctl", """\
params:
  - name: CERBERUS_ENABLED
    flag: cerberus-enabled
    description: Enable cerberus.
""")
    rel = site.page("f", "f", "krknctl", prefix="--")
    assert site.build().returncode == 0
    assert cells(site.html(rel)) == ["--cerberus-enabled", "Enable cerberus."]


def test_a_row_with_no_flag_still_shows_its_name(site):
    """env.sh rows carry no flag, and must not render an empty first cell."""
    site.data("n", "krkn-hub", """\
params:
  - name: TIMEOUT
    description: Seconds to wait.
""")
    rel = site.page("n", "n", "krkn-hub")
    assert site.build().returncode == 0
    assert cells(site.html(rel)) == ["TIMEOUT", "Seconds to wait."]


def test_a_secret_is_marked_in_the_type_column(site):
    """The marker rides in Type rather than a column of its own: one row in
    thirty is secret, so a dedicated column would be empty on the rest."""
    site.data("s", "krknctl", """\
params:
  - name: AWS_SECRET_ACCESS_KEY
    description: AWS secret key.
    type: string
    secret: true
""")
    rel = site.page("s", "s", "krknctl")
    assert site.build().returncode == 0
    assert headers(site.html(rel)) == ["Parameter", "Description", "Type"]
    assert cells(site.html(rel)) == ["AWS_SECRET_ACCESS_KEY", "AWS secret key.",
                                     "string (secret)"]


# a missing data file or empty params list fails the build (the errorf gate)

def test_missing_data_file_fails_build(site):
    site.page("ghost", "ghost", "krkn-hub")  # no data() call
    proc = site.build()
    assert proc.returncode != 0
    assert 'param-table: no data for scenario="ghost"' in proc.stderr


def test_empty_params_fails_build(site):
    site.data("empty", "krkn-hub", "params: []\n")
    site.page("empty", "empty", "krkn-hub")
    proc = site.build()
    assert proc.returncode != 0
    assert 'param-table: no data for scenario="empty"' in proc.stderr


# markdown descriptions and awkward default values

def test_markdown_description_renders_links_and_code(site):
    site.data("md", "krkn-hub", """\
params:
  - name: ACTION
    description: "See the [docs](/x) and `node_stop`."
""")
    rel = site.page("md", "md", "krkn-hub")
    assert site.build().returncode == 0
    soup = BeautifulSoup(site.html(rel), "html.parser")
    desc = soup.select("table.krkn-param-table tbody td")[1]
    assert desc.select_one("a[href='/x']") is not None
    assert desc.select_one("code") is not None


def test_default_with_slash_quote_and_empty(site):
    site.data("d", "krkn-hub", """\
params:
  - name: LABEL
    description: A label.
    default: node-role.kubernetes.io/worker
  - name: EMPTY
    description: Empty default.
    default: ""
  - name: QUOTED
    description: Quoted default.
    default: '"x"'
""")
    rel = site.page("d", "d", "krkn-hub")
    assert site.build().returncode == 0
    assert cells(site.html(rel), row=0)[2] == "node-role.kubernetes.io/worker"
    # An explicit empty default is not the same as no default, which renders "-".
    # UUID=${UUID:=""} is a real param that defaults to empty.
    assert cells(site.html(rel), row=1)[2] == '""'
    assert cells(site.html(rel), row=2)[2] == '"x"'


# the group filter and the flag prefix, used by the two global pages

GROUPED = """\
params:
  - name: cerberus-enabled
    description: Enables it.
    group: cerberus
    type: enum
    possible_values: [True, False]
  - name: uuid
    description: Run id.
    group: general
"""


def test_group_selects_only_its_own_rows(site):
    site.data("globals", "krknctl", GROUPED)
    rel = site.page("g", "globals", "krknctl", group="cerberus")
    assert site.build().returncode == 0
    soup = BeautifulSoup(site.html(rel), "html.parser")
    assert len(soup.select("table.krkn-param-table tbody tr")) == 1
    assert cells(site.html(rel))[0] == "cerberus-enabled"


def test_a_group_does_not_inherit_a_sibling_group_column(site):
    """general has no possible_values, so filtering must happen before the
    columns are worked out or it gains an empty Possible Values column."""
    site.data("globals", "krknctl", GROUPED)
    rel = site.page("g2", "globals", "krknctl", group="general")
    assert site.build().returncode == 0
    assert headers(site.html(rel)) == ["Parameter", "Description"]


def test_prefix_is_prepended_to_the_name(site):
    site.data("globals", "krknctl", GROUPED)
    rel = site.page("g3", "globals", "krknctl", group="general", prefix="--")
    assert site.build().returncode == 0
    assert cells(site.html(rel))[0] == "--uuid"


def test_a_group_with_no_rows_fails_the_build(site):
    site.data("globals", "krknctl", GROUPED)
    site.page("g4", "globals", "krknctl", group="nosuchgroup")
    proc = site.build()
    assert proc.returncode != 0
    assert 'group "nosuchgroup" has no params' in proc.stderr


# the shipped example data files must render cleanly

def test_example_node_scenarios_renders_four_columns(site):
    yaml_text = (EXAMPLES / "node-scenarios" / "krkn-hub.yaml").read_text(encoding="utf-8")
    site.data("node-scenarios", "krkn-hub", yaml_text)
    rel = site.page("node-scenarios", "node-scenarios", "krkn-hub")
    proc = site.build()
    assert proc.returncode == 0, proc.stderr
    assert headers(site.html(rel)) == ["Parameter", "Description", "Type", "Default"]
    soup = BeautifulSoup(site.html(rel), "html.parser")
    rows = soup.select("table.krkn-param-table tbody tr")
    assert len(rows) == 18
    # The quoted boolean-ish defaults survive as text, not Python booleans.
    assert cells(site.html(rel), row=9)[3] == "True"   # KUBE_CHECK


def test_example_service_hijacking_renders_two_columns(site):
    yaml_text = (EXAMPLES / "service-hijacking-scenario" / "krkn-hub.yaml").read_text(encoding="utf-8")
    site.data("service-hijacking-scenario", "krkn-hub", yaml_text)
    rel = site.page("svc-hijack", "service-hijacking-scenario", "krkn-hub")
    proc = site.build()
    assert proc.returncode == 0, proc.stderr
    assert headers(site.html(rel)) == ["Parameter", "Description"]


def _crd_ref_page(site, crd):
    """A page carrying one crd-ref call, plus the index it resolves against."""
    (site.root / "data" / "krkn_operator_crds.yaml").write_text(
        f"{crd}:\n  kind: KrknUser\n  short: ku\n  fields: 9\n", encoding="utf-8")
    (site.root / "content" / "users.md").write_text(
        f'---\ntitle: users\n---\n\n{{{{< crd-ref crd="{crd}" >}}}}\n', encoding="utf-8")
    return "users/index.html"


def href(html):
    return BeautifulSoup(html, "html.parser").select_one("a.krkn-crd-ref")["href"]


def test_crd_ref_links_to_the_generated_reference(site):
    rel = _crd_ref_page(site, "krknusers")
    proc = site.build()
    assert proc.returncode == 0, proc.stderr
    assert href(site.html(rel)) == "/docs/krkn-operator/api-reference/krknusers/"


def test_crd_ref_keeps_the_site_base_path(tmp_path):
    """A root-absolute href drops the base path, so every link 404s on a site
    served under a sub-path. relURL is what puts it back."""
    from tests.conftest import Site
    site = Site(tmp_path, base_url="http://example.org/chaos/")
    rel = _crd_ref_page(site, "krknusers")
    proc = site.build()
    assert proc.returncode == 0, proc.stderr
    assert href(site.html(rel)) == "/chaos/docs/krkn-operator/api-reference/krknusers/"
