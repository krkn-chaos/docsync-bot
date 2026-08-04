from bot.scaffold import inject_global_shortcodes

# name -> group, as build_groups() produces
CTL = {"krkn-kubeconfig": "general", "uuid": "general",
       "cerberus-enabled": "cerberus", "cerberus-url": "cerberus",
       "telemetry-enabled": "telemetry"}
HUB = {"CERBERUS_ENABLED": "cerberus", "CERBERUS_URL": "cerberus"}

KRKNCTL_PAGE = """## Cerberus

Blurb with a [link](../krkn/config.md#cerberus).

<div class="wide-params-table">

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--cerberus-enabled` | Enables it | False |
| `--cerberus-url` | The url | http://0.0.0.0:8080 |

</div>

## Telemetry

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--telemetry-enabled` | On or off | False |
"""

HUB_PAGE = """## Cerberus

Blurb.

Parameter | Description | Default
--- | --- | ---
`CERBERUS_ENABLED` | Set this to true | False
`CERBERUS_URL` | URL to poll | http://0.0.0.0:8080
"""


def test_replaces_a_table_with_a_group_filtered_call():
    out, _ = inject_global_shortcodes(KRKNCTL_PAGE, "krknctl", CTL)
    assert '{{< param-table scenario="globals" source="krknctl" group="cerberus" prefix="--" >}}' in out
    assert '{{< param-table scenario="globals" source="krknctl" group="telemetry" prefix="--" >}}' in out
    assert "`--cerberus-enabled`" not in out, "table body must be gone"


def test_prose_and_wrappers_survive():
    out, _ = inject_global_shortcodes(KRKNCTL_PAGE, "krknctl", CTL)
    assert "## Cerberus" in out
    assert "[link](../krkn/config.md#cerberus)" in out
    assert '<div class="wide-params-table">' in out and "</div>" in out


def test_handles_tables_without_leading_pipes():
    out, _ = inject_global_shortcodes(HUB_PAGE, "krkn-hub", HUB)
    assert '{{< param-table scenario="globals" source="krkn-hub" group="cerberus" >}}' in out
    assert "`CERBERUS_ENABLED`" not in out


def test_a_group_split_across_sections_injects_neither():
    """Kraken and Tunings both draw from general. Injecting the first would pull
    Tunings' params into Kraken while Tunings still lists them, showing them
    twice, so refusing only the second table is not enough."""
    page = """## Kraken

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--krkn-kubeconfig` | path | x |

## Tunings

| Parameter | Description | Default |
|-----------|-------------|---------|
| `--uuid` | id | y |
"""
    out, report = inject_global_shortcodes(page, "krknctl", CTL)
    assert "param-table" not in out
    assert "`--krkn-kubeconfig`" in out and "`--uuid`" in out
    assert sum("split across" in r for r in report) == 2, report


def test_a_mixed_table_is_left_alone():
    page = KRKNCTL_PAGE.replace("`--cerberus-url`", "`--telemetry-enabled`")
    out, report = inject_global_shortcodes(page, "krknctl", CTL)
    assert "`--telemetry-enabled` | The url" in out
    assert any("mixed" in r for r in report), report


def test_unknown_params_leave_the_table_alone():
    page = KRKNCTL_PAGE.replace("`--cerberus-enabled`", "`--not-a-real-flag`")
    out, report = inject_global_shortcodes(page, "krknctl", CTL)
    assert "`--not-a-real-flag`" in out
    assert any("unknown" in r for r in report), report


def test_is_idempotent():
    once, _ = inject_global_shortcodes(KRKNCTL_PAGE, "krknctl", CTL)
    twice, _ = inject_global_shortcodes(once, "krknctl", CTL)
    assert twice == once


def test_krkn_hub_calls_carry_no_prefix():
    """krkn-hub params are env vars, set as CERBERUS_ENABLED=... not --cerberus."""
    out, _ = inject_global_shortcodes(HUB_PAGE, "krkn-hub", HUB)
    assert "prefix=" not in out
