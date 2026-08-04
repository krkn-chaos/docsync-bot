import json

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


def test_env_export_borrows_its_group_from_the_join(tmp_path):
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    _, env = g.build_groups(hub, krkn)
    assert env[0].group == "cerberus"


def test_env_export_borrows_a_description_when_it_has_no_comment(tmp_path):
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    _, env = g.build_groups(hub, krkn)
    assert env[0].description == "Enables Cerberus Support"


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


def test_regenerating_twice_is_byte_identical(tmp_path):
    hub, krkn = _sources(tmp_path, CERBERUS, CTL)
    web = tmp_path / "web"
    g.emit(web, hub, krkn)
    first = (web / "data/params/globals/krkn-hub.yaml").read_text(encoding="utf-8")
    g.emit(web, hub, krkn)
    assert (web / "data/params/globals/krkn-hub.yaml").read_text(encoding="utf-8") == first
