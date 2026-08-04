from pathlib import Path

import pytest

from bot.parser import (
    build_skip_list,
    extract_env_params,
    extract_krknctl_params,
    require_sources,
)

FIXTURES = Path(__file__).parent / "fixtures"


def _records(tmp_path, text):
    f = tmp_path / "env.sh"
    f.write_text(text)
    return {r.name: r for r in extract_env_params(f)}


def _sources(tmp_path, env=None, krknctl=None):
    """A krkn-hub root and a krkn root, each holding a global source or not."""
    hub, krkn = tmp_path / "krkn-hub", tmp_path / "krkn"
    hub.mkdir()
    (krkn / "containers").mkdir(parents=True)
    if env is not None:
        (hub / "env.sh").write_text(env)
    if krknctl is not None:
        (krkn / "containers/krknctl-input.json").write_text(krknctl)
    return hub, krkn


def test_skip_list_covers_both_sources(tmp_path):
    hub, krkn = _sources(
        tmp_path,
        env='export WAIT_DURATION="${WAIT_DURATION:-60}"\n',
        krknctl='[{"variable": "TELEMETRY_ENABLED", "name": "telemetry-enabled"}]')
    skip = build_skip_list(hub, krkn)
    assert "WAIT_DURATION" in skip
    assert "TELEMETRY_ENABLED" in skip
    # Set by run.sh, so neither source declares them.
    assert {"SCENARIO_TYPE", "SCENARIO_FILE", "IMAGE"} <= skip


def test_skip_list_tolerates_a_missing_source(tmp_path):
    hub, krkn = _sources(tmp_path, env='export WAIT_DURATION="${WAIT_DURATION:-60}"\n')
    assert build_skip_list(hub, krkn) == {
        "WAIT_DURATION", "SCENARIO_TYPE", "SCENARIO_FILE", "IMAGE"}


def test_require_sources_names_the_file_and_how_to_point_at_it(tmp_path):
    hub, krkn = _sources(tmp_path, env="")
    with pytest.raises(FileNotFoundError, match="KRKN_PATH"):
        require_sources(hub, krkn)


def test_extract_bare_var_is_required_no_default(tmp_path):
    """pvc-scenario pattern: export PVC_NAME=${PVC_NAME}"""
    recs = _records(tmp_path, "export PVC_NAME=${PVC_NAME}\n")
    assert recs["PVC_NAME"].required is True
    assert recs["PVC_NAME"].default is None


def test_extract_malformed_colon_empty_default(tmp_path):
    """application-outages pattern: ${EXCLUDE_LABEL:""} -- intended default."""
    recs = _records(tmp_path, 'export EXCLUDE_LABEL=${EXCLUDE_LABEL:""}\n')
    assert recs["EXCLUDE_LABEL"].default == ""
    assert recs["EXCLUDE_LABEL"].required is False


def test_extract_malformed_colon_value_default(tmp_path):
    """global env.sh pattern: ${KUBE_VIRT_EXIT_ON_FAIL:False}"""
    recs = _records(tmp_path, "export KUBE_VIRT_EXIT_ON_FAIL=${KUBE_VIRT_EXIT_ON_FAIL:False}\n")
    assert recs["KUBE_VIRT_EXIT_ON_FAIL"].default == "False"


def test_extract_inline_comment_becomes_description(tmp_path):
    recs = _records(
        tmp_path,
        'export KUBE_VIRT_NODE_NAME=${KUBE_VIRT_NODE_NAME:""}   '
        "# Filter only VMI's running a specific node name\n",
    )
    rec = recs["KUBE_VIRT_NODE_NAME"]
    assert rec.description == "Filter only VMI's running a specific node name"
    assert rec.description_source == "env-comment"


def test_extract_no_comment_means_no_description(tmp_path):
    recs = _records(tmp_path, 'export DURATION=${DURATION:=600}\n')
    assert recs["DURATION"].description is None
    assert recs["DURATION"].description_source is None


def test_extract_skips_command_substitution(tmp_path):
    recs = _records(
        tmp_path,
        'export MODE=$([ "$X" = "true" ] && echo "a" || echo "b")\n'
        "export TESTS=`yq -e '.chaos_tests.MEM[]' config.yaml`\n",
    )
    assert recs == {}


def test_extract_skips_plain_string_assignment(tmp_path):
    """node-scenarios-bm pattern: export SCENARIO_TYPE="node_scenarios" """
    recs = _records(tmp_path, 'export SCENARIO_TYPE="node_scenarios"\nexport SIMPLE=value\n')
    assert recs == {}


def test_extract_quoted_wrapper(tmp_path):
    recs = _records(tmp_path, 'export KRKN_DEBUG="${KRKN_DEBUG:-False}"\n')
    assert recs["KRKN_DEBUG"].default == "False"


def test_extract_braces_inside_default(tmp_path):
    """network-chaos pattern: default itself contains balanced braces."""
    recs = _records(tmp_path, 'export EGRESS=${EGRESS:="{bandwidth: 100mbit}"}\n')
    assert recs["EGRESS"].default == "{bandwidth: 100mbit}"


def test_extract_quote_protected_unbalanced_brace(tmp_path):
    """A '}' inside a quoted default must not close the expansion early."""
    recs = _records(tmp_path, 'export ODD=${ODD:="a}b"}\n')
    assert recs["ODD"].default == "a}b"


def test_extract_regex_default_with_repetition_braces(tmp_path):
    """global env.sh TELEMETRY_FILTER_PATTERN: quoted default with {1,2} etc."""
    recs = _records(tmp_path, "export P=${P:='[\"(\\\\d{1,2}:\\\\d{2})\"]'}\n")
    assert recs["P"].default == '["(\\\\d{1,2}:\\\\d{2})"]'


def test_extract_first_declaration_wins(tmp_path):
    """global env.sh: KUBECONFIG=${KRKN_KUBE_CONFIG} re-export must not
    demote the earlier default to required."""
    recs = _records(
        tmp_path,
        "export KRKN_KUBE_CONFIG=${KRKN_KUBE_CONFIG:=/home/krkn/.kube/config}\n"
        "export KUBECONFIG=${KRKN_KUBE_CONFIG}\n",
    )
    rec = recs["KRKN_KUBE_CONFIG"]
    assert rec.default == "/home/krkn/.kube/config"
    assert rec.required is False
    assert "KUBECONFIG" not in recs


def test_extract_variable_reference_alone_is_not_a_default(tmp_path):
    # Was: the literal "$ALERTS_PATH" is kept. It reached the rendered table,
    # where it tells a reader nothing. With no sibling to resolve against,
    # reporting no default is better.
    recs = _records(tmp_path, "export RESILIENCY_FILE=${RESILIENCY_FILE:=$ALERTS_PATH}\n")
    assert recs["RESILIENCY_FILE"].default is None


def test_extract_unquoted_default_with_spaces(tmp_path):
    """application-outages pattern: ${BLOCK_TRAFFIC_TYPE:=- Ingress}"""
    recs = _records(tmp_path, "export BLOCK_TRAFFIC_TYPE=${BLOCK_TRAFFIC_TYPE:=- Ingress}\n")
    assert recs["BLOCK_TRAFFIC_TYPE"].default == "- Ingress"


def test_extract_skips_other_expansions(tmp_path):
    recs = _records(tmp_path, "export SHORT=${LONG%.txt}\nexport SUB=${SRC/abc/xyz}\n")
    assert recs == {}



def test_golden_pvc_scenario_env():
    recs = {r.name: r for r in extract_env_params(FIXTURES / "pvc-scenario_env.sh")}
    for name in ("PVC_NAME", "POD_NAME", "NAMESPACE"):
        assert recs[name].required is True, f"{name} must be required (v1 dropped it)"
        assert recs[name].default is None
    assert recs["FILL_PERCENTAGE"].default == "50"
    assert recs["DURATION"].default == "60"
    assert recs["BLOCK_SIZE"].default == "102400"
    assert recs["SCENARIO_TYPE"].default == "pvc_scenarios"


def test_golden_application_outages_env():
    recs = {r.name: r for r in extract_env_params(FIXTURES / "application-outages_env.sh")}
    assert recs["EXCLUDE_LABEL"].default == ""        # v1 dropped (malformed colon)
    assert recs["EXCLUDE_LABEL"].required is False
    assert recs["DURATION"].default == "600"
    assert recs["NAMESPACE"].default == "<namespace>"
    assert recs["POD_SELECTOR"].default == "{}"       # v1 truncated to '{'
    assert recs["BLOCK_TRAFFIC_TYPE"].default == "- Ingress"


def test_golden_global_env():
    recs = {r.name: r for r in extract_env_params(FIXTURES / "global_env.sh")}
    assert recs["ES_PASSWORD"].required is True
    assert recs["TELEMETRY_PASSWORD"].required is True
    assert recs["KUBE_VIRT_SSH_NODE"].default == ""
    assert recs["KUBE_VIRT_NODE_NAME"].description is not None
    assert "node name" in recs["KUBE_VIRT_NODE_NAME"].description
    assert recs["KUBE_VIRT_EXIT_ON_FAIL"].default == "False"
    assert "{1,2}" in recs["TELEMETRY_FILTER_PATTERN"].default
    # $( ) re-exports skipped; first declaration wins
    assert recs["RESILIENCY_RUN_MODE"].default == "standalone"
    assert recs["KRKN_KUBE_CONFIG"].default == "/home/krkn/.kube/config"
    assert recs["KRKN_KUBE_CONFIG"].required is False



def test_krknctl_full_schema_application_outages():
    recs = {r.name: r for r in extract_krknctl_params(FIXTURES / "application-outages_krknctl-input.json")}
    dur = recs["DURATION"]
    assert dur.default == "600"
    assert dur.type == "number"
    assert dur.required is False
    assert dur.description_source == "krknctl"
    assert "chaos duration" in dur.description.lower()
    ns = recs["NAMESPACE"]
    assert ns.required is True
    assert ns.default is None         # required-without-default, not ""


def test_krknctl_golden_node_scenarios():
    recs = {r.name: r for r in extract_krknctl_params(FIXTURES / "node-scenarios_krknctl-input.json")}
    action = recs["ACTION"]
    assert action.required is True
    assert action.type == "enum"
    assert "node_reboot_scenario" in action.allowed_values
    assert len(action.allowed_values) == 12
    assert recs["VSPHERE_PASSWORD"].default == ""     # explicit "" kept, not None
    creds = recs["GOOGLE_APPLICATION_CREDENTIALS"]
    assert creds.type == "file"
    assert creds.default is None


def test_krknctl_malformed_inputs(tmp_path):
    not_a_list = tmp_path / "a.json"
    not_a_list.write_text('{"variable": "X"}')
    assert extract_krknctl_params(not_a_list) == []
    missing_variable = tmp_path / "b.json"
    missing_variable.write_text('[{"name": "x"}, {"variable": "OK", "default": "1"}]')
    recs = extract_krknctl_params(missing_variable)
    assert [r.name for r in recs] == ["OK"]
    assert recs[0].default == "1"



def test_adv_nested_expansion_kept_literal(tmp_path):
    recs = _records(tmp_path, "export A=${A:=${B:-x}}\n")
    assert recs["A"].default == "${B:-x}"


def test_adv_escaped_quotes_inside_default(tmp_path):
    recs = _records(tmp_path, 'export A=${A:="he said \\"hi\\""}\n')
    assert recs["A"].default == 'he said \\"hi\\"'


def test_adv_hash_inside_unquoted_default_not_a_comment(tmp_path):
    recs = _records(tmp_path, "export A=${A:=a#b}\n")
    assert recs["A"].default == "a#b"
    assert recs["A"].description is None


def test_adv_double_hash_comment(tmp_path):
    recs = _records(tmp_path, "export A=${A:=x}  ## double hash comment\n")
    assert recs["A"].description == "double hash comment"


def test_adv_crlf_line_endings(tmp_path):
    f = tmp_path / "env.sh"
    f.write_bytes(b"export A=${A:=1}\r\nexport B=${B}\r\n")
    recs = {r.name: r for r in extract_env_params(f)}
    assert recs["A"].default == "1"
    assert recs["B"].required is True


def test_adv_utf8_bom(tmp_path):
    f = tmp_path / "env.sh"
    f.write_bytes(b"\xef\xbb\xbfexport A=${A:=1}\n")
    recs = {r.name: r for r in extract_env_params(f)}
    assert recs["A"].default == "1"


def test_adv_lowercase_and_mixed_names(tmp_path):
    recs = _records(tmp_path, "export myvar=${myvar:-x}\nexport MixedCase=${MixedCase:=y}\n")
    assert recs["myvar"].default == "x"
    assert recs["MixedCase"].default == "y"


def test_adv_degenerate_lines_yield_nothing(tmp_path):
    recs = _records(
        tmp_path,
        "export A=${}\n"            # empty expansion
        "export B=${B:=x\n"         # unclosed brace
        "export C=${C,,}\n"         # case-modification expansion
        "export D=${D%.txt}\n"      # suffix-strip expansion
        "export\n"                  # bare export
        "export =${X:=1}\n",        # missing name
    )
    assert recs == {}


def test_adv_concatenation_is_not_a_declaration(tmp_path):
    """export PATH=${PATH}:/extra must not register PATH as a required param."""
    recs = _records(tmp_path, "export PATH=${PATH}:/usr/local/bin\nexport A=${A:=1} && echo done\n")
    assert recs == {}


def test_adv_quoted_wrapper_with_comment(tmp_path):
    recs = _records(tmp_path, 'export A="${A:-x}" # docs here\n')
    assert recs["A"].default == "x"
    assert recs["A"].description == "docs here"


def test_adv_quoted_default_with_spaces(tmp_path):
    recs = _records(tmp_path, 'export A=${A:-"x y z"}\n')
    assert recs["A"].default == "x y z"


def test_adv_unicode_comment_and_default(tmp_path):
    f = tmp_path / "env.sh"
    f.write_text("export A=${A:=café}  # durée en secondes\n", encoding="utf-8")
    recs = {r.name: r for r in extract_env_params(f)}
    assert recs["A"].default == "café"
    assert recs["A"].description == "durée en secondes"


def test_adv_empty_and_comment_only_files(tmp_path):
    f = tmp_path / "env.sh"
    f.write_text("")
    assert extract_env_params(f) == []
    f.write_text("#!/bin/bash\n# only comments\n\n")
    assert extract_env_params(f) == []


# group and flag, the two krknctl-only fields

def test_krknctl_params_carry_their_group(tmp_path):
    f = tmp_path / "krknctl-input.json"
    f.write_text('[{"name": "cerberus-enabled", "variable": "CERBERUS_ENABLED", '
                 '"group": "cerberus", "default": "False"}]', encoding="utf-8")
    rec = extract_krknctl_params(f)[0]
    assert rec.name == "CERBERUS_ENABLED"
    assert rec.group == "cerberus"


def test_krknctl_params_carry_both_identifiers(tmp_path):
    """The env var joins against env.sh, the flag is what the krknctl page shows.
    Both ride on the record so nothing has to parse the file twice."""
    f = tmp_path / "krknctl-input.json"
    f.write_text('[{"name": "cerberus-enabled", "variable": "CERBERUS_ENABLED", '
                 '"group": "cerberus"}]', encoding="utf-8")
    rec = extract_krknctl_params(f)[0]
    assert rec.name == "CERBERUS_ENABLED"
    assert rec.flag == "cerberus-enabled"


def test_krknctl_group_descriptors_are_not_params(tmp_path):
    """A "type": "Group" entry names a group and configures nothing."""
    f = tmp_path / "krknctl-input.json"
    f.write_text(
        '[{"name": "cerberus", "description": "Group containing ...", "type": "Group"},'
        ' {"name": "cerberus-enabled", "variable": "CERBERUS_ENABLED", "group": "cerberus"}]',
        encoding="utf-8")
    assert [r.name for r in extract_krknctl_params(f)] == ["CERBERUS_ENABLED"]


def test_a_group_descriptor_is_skipped_even_if_it_gains_a_variable(tmp_path):
    """Today they carry no variable, so the variable check alone would do it.
    This pins the intent so a data change upstream cannot leak a phantom param
    into a published table."""
    f = tmp_path / "krknctl-input.json"
    f.write_text('[{"name": "cerberus", "variable": "CERBERUS", "type": "Group"}]',
                 encoding="utf-8")
    assert extract_krknctl_params(f) == []


def test_a_param_without_a_group_gets_none(tmp_path):
    """Per-scenario krknctl-input.json files carry no group."""
    f = tmp_path / "krknctl-input.json"
    f.write_text('[{"variable": "X"}]', encoding="utf-8")
    rec = extract_krknctl_params(f)[0]
    assert rec.group is None
    assert rec.flag is None


def test_adv_indented_and_multi_space_export(tmp_path):
    recs = _records(tmp_path, "   export A=${A:=1}\n\texport B=${B:=2}\nexport   C=${C:=3}\n")
    assert recs["A"].default == "1"
    assert recs["B"].default == "2"
    assert recs["C"].default == "3"


def test_adv_krknctl_null_default_means_no_default(tmp_path):
    f = tmp_path / "a.json"
    f.write_text('[{"variable": "X", "default": null}, {"variable": "Y", "default": ""}]')
    recs = {r.name: r for r in extract_krknctl_params(f)}
    assert recs["X"].default is None
    assert recs["Y"].default == ""


def test_adv_krknctl_boolean_and_numeric_json_types(tmp_path):
    f = tmp_path / "a.json"
    f.write_text('[{"variable": "X", "default": 600, "required": true}]')
    recs = extract_krknctl_params(f)
    assert recs[0].default == "600"
    assert recs[0].required is True


# alias exports and reference defaults

def test_alias_export_is_not_a_param(tmp_path):
    """Root env.sh: export KUBECONFIG=${KRKN_KUBE_CONFIG} re-exports a different
    variable. Nobody sets KUBECONFIG here, so it is not a param."""
    assert _records(tmp_path, "export KUBECONFIG=${KRKN_KUBE_CONFIG}\n") == {}


def test_self_reference_stays_a_required_param(tmp_path):
    """pvc-scenario: export PVC_NAME=${PVC_NAME} is a real required input."""
    rec = _records(tmp_path, "export FOO=${FOO}\n")["FOO"]
    assert rec.required is True and rec.default is None


def test_a_default_referencing_another_var_is_resolved(tmp_path):
    recs = _records(tmp_path,
                    "export ALERTS_PATH=${ALERTS_PATH:=config/alerts.yaml}\n"
                    "export RESILIENCY_FILE=${RESILIENCY_FILE:=$ALERTS_PATH}\n")
    assert recs["RESILIENCY_FILE"].default == "config/alerts.yaml"


def test_an_unresolvable_reference_becomes_no_default(tmp_path):
    recs = _records(tmp_path, "export FOO=${FOO:=$NOT_DECLARED_HERE}\n")
    assert recs["FOO"].default is None


def test_a_chain_of_references_resolves_all_the_way(tmp_path):
    """A single pass left A holding "$C", since B was still a reference when A
    read it. Which one broke depended on declaration order."""
    recs = _records(tmp_path,
                    "export A=${A:=$B}\n"
                    "export B=${B:=$C}\n"
                    "export C=${C:=value}\n")
    assert [recs[n].default for n in "ABC"] == ["value", "value", "value"]


def test_a_chain_resolves_regardless_of_declaration_order(tmp_path):
    recs = _records(tmp_path,
                    "export C=${C:=value}\n"
                    "export B=${B:=$C}\n"
                    "export A=${A:=$B}\n")
    assert [recs[n].default for n in "ABC"] == ["value", "value", "value"]


def test_a_reference_cycle_does_not_hang(tmp_path):
    """Nothing in krkn-hub does this, but a parser must not recurse forever."""
    recs = _records(tmp_path, "export A=${A:=$B}\nexport B=${B:=$A}\n")
    assert recs["A"].default is None and recs["B"].default is None


def test_an_unbalanced_brace_is_a_literal_not_a_reference(tmp_path):
    """${FOO and $FOO} are not references. Matching them would silently drop a
    default that happens to look like one."""
    recs = _records(tmp_path, 'export X=${X:="${FOO"}\nexport Y=${Y:="$FOO}"}\n')
    assert recs["X"].default == "${FOO"
    assert recs["Y"].default == "$FOO}"
