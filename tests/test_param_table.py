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
    assert cells(site.html(rel)) == ["FLAG", "A flag.", "false"]


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
    assert cells(site.html(rel), row=1) == ["B", "Has neither.", "", ""]


# krknctl possible_values and required columns

def test_possible_values_comma_joined(site):
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
    assert headers(site.html(rel)) == [
        "Parameter", "Description", "Type", "Possible Values", "Default", "Required",
    ]
    assert cells(site.html(rel)) == [
        "CLOUD_TYPE", "Cloud platform.", "enum", "aws, gcp, azure", "aws", "true",
    ]


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
    assert cells(site.html(rel), row=2)[2] == '"x"'


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
