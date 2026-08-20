from pathlib import Path

import pytest

from bot.crd_parser import crd_columns, crd_fields, crd_meta, load_crd

CRDS = Path(__file__).parent / "fixtures" / "crd"


def crd(kind):
    return load_crd(CRDS / f"krkn.krkn-chaos.dev_{kind}.yaml")


def by_name(records):
    return {r.name: r for r in records}


def sections(doc):
    spec, status = crd_fields(doc, "spec"), crd_fields(doc, "status")
    return {"spec": by_name(spec), "status": by_name(status)}


# The headline number, guarded. Every field described at source is what lets the
# operator skip the model entirely.
def test_every_field_across_every_crd_is_described():
    fields = [r for f in sorted(CRDS.glob("*.yaml"))
              for s in ("spec", "status") for r in crd_fields(load_crd(f), s)]
    assert len(fields) == 141
    undescribed = [r.name for r in fields if not r.description]
    assert undescribed == []


def test_every_column_borrows_a_description():
    total, borrowed = 0, 0
    for f in sorted(CRDS.glob("*.yaml")):
        doc = load_crd(f)
        for c in crd_columns(doc, sections(doc)):
            total += 1
            borrowed += bool(c.borrowed_description)
    assert (total, borrowed) == (26, 26)


def test_the_age_column_is_skipped():
    """Every kind carries .metadata.creationTimestamp as Age, which documents
    Kubernetes rather than krkn."""
    doc = crd("krknusers")
    names = [c.name for c in crd_columns(doc, sections(doc))]
    assert "Age" not in names
    assert names == ["UserID", "Name", "Surname", "Role", "Active"]


def test_a_column_borrows_from_the_field_its_jsonpath_names():
    doc = crd("krknusers")
    active = next(c for c in crd_columns(doc, sections(doc)) if c.name == "Active")
    assert active.borrowed_description == \
        "Active indicates whether the user account is active"


def test_a_column_pointing_nowhere_borrows_nothing():
    """A jsonPath the walk cannot reach leaves the record blank. That it then
    becomes a reported gap is test_operator's job, not this one's."""
    doc = crd("krknusers")
    doc["spec"]["versions"][0]["additionalPrinterColumns"] = [
        {"jsonPath": ".spec.doesNotExist", "name": "Ghost", "type": "string"}]
    ghost = crd_columns(doc, sections(doc))[0]
    assert ghost.name == "Ghost"
    assert ghost.borrowed_description is None
    assert ghost.description is None


def test_a_column_carries_no_requiredness():
    """Requiredness is meaningless for a display column, and None is what stops
    the emitter adding a column of "No"."""
    doc = crd("krknusers")
    assert all(c.required is None for c in crd_columns(doc, sections(doc)))


def test_a_hard_wrapped_description_comes_back_as_one_line():
    """controller-gen wraps at 80 columns. Raw, it breaks out of a table cell."""
    spec = by_name(crd_fields(crd("krknusers"), "spec"))
    assert spec["passwordSecretRef"].description == (
        "PasswordSecretRef references the Secret containing the hashed password "
        "The Secret must contain a 'passwordHash' key with the bcrypt hash")


def test_an_enum_and_a_default_both_survive():
    role = by_name(crd_fields(crd("krknusers"), "spec"))["role"]
    assert role.allowed_values == ["user", "admin"]
    assert role.default == "user"


def test_an_array_takes_its_enum_from_items():
    """actions is an array of enum strings, so the values sit on items, not on
    the property itself."""
    spec = by_name(crd_fields(crd("krknusergroups"), "spec"))
    assert spec["clusterPermissions.<key>.actions"].allowed_values == \
        ["view", "run", "cancel"]


def test_a_boolean_default_is_not_rendered_as_python():
    """YAML gives a real bool, and a reader copies this into a manifest."""
    status = by_name(crd_fields(crd("krknusers"), "status"))
    assert status["active"].default == "true"


def test_required_is_read_from_the_parent_not_the_top():
    spec = by_name(crd_fields(crd("krknusers"), "spec"))
    assert spec["name"].required is True
    assert spec["organization"].required is False


def test_required_is_read_at_each_nested_level():
    spec = by_name(crd_fields(crd("krknusergroups"), "spec"))
    assert spec["clusterPermissions.<key>.actions"].required is True


def test_a_map_of_objects_is_flattened_with_a_key_marker():
    spec = by_name(crd_fields(crd("krknusergroups"), "spec"))
    assert "clusterPermissions" in spec
    assert "clusterPermissions.<key>.actions" in spec


def test_a_map_of_arrays_of_objects_is_reached():
    """targetData is map -> array -> object. The three containers compose, so a
    walk that checks each once at a single level loses both leaves."""
    status = by_name(crd_fields(crd("krkntargetrequests"), "status"))
    assert "targetData.<key>[].cluster-name" in status
    assert "targetData.<key>[].cluster-api-url" in status


def test_a_field_that_only_names_a_secret_is_not_marked_as_one():
    """passwordSecretRef holds a Secret's name and secretType holds an enum.
    Marking either would contradict the row's own description and values."""
    users = by_name(crd_fields(crd("krknusers"), "spec"))
    targets = by_name(crd_fields(crd("krknoperatortargets"), "spec"))
    assert users["passwordSecretRef"].secret is False
    assert users["name"].secret is False
    assert targets["secretType"].secret is False
    assert targets["secretUUID"].secret is False


def test_a_field_that_holds_a_secret_is_marked():
    spec = by_name(crd_fields(crd("krknscenarioruns"), "spec"))
    assert spec["password"].secret is True
    assert spec["token"].secret is True


def test_the_storage_version_is_the_one_documented():
    """versions are emitted name-sorted, so a later v1beta1 would leave
    versions[0] documenting v1alpha1 forever."""
    doc = crd("krknusers")
    versions = doc["spec"]["versions"]
    older = {**versions[0], "name": "v1alpha0", "storage": False}
    doc["spec"]["versions"] = [older, {**versions[0], "storage": True}]
    assert crd_meta(doc)["version"] == "v1alpha1"


def test_a_column_with_its_own_description_does_not_borrow():
    """printcolumn description= is written for the column, so it wins."""
    doc = crd("krknusers")
    doc["spec"]["versions"][0]["additionalPrinterColumns"] = [
        {"jsonPath": ".spec.role", "name": "Role", "type": "string",
         "description": "The permission level granted to this user"}]
    role = crd_columns(doc, sections(doc))[0]
    assert role.description == "The permission level granted to this user"
    assert role.borrowed_description is None


def test_kubernetes_boilerplate_is_not_a_parameter():
    """apiVersion, kind and metadata sit beside spec and status on every kind."""
    spec = by_name(crd_fields(crd("krknusers"), "spec"))
    assert not {"apiVersion", "kind", "metadata"} & set(spec)


def test_a_kind_with_no_status_yields_no_status_records():
    assert crd_fields(crd("krknusergroups"), "status") == []


def test_meta_carries_what_the_page_heading_needs():
    m = crd_meta(crd("krknusers"))
    assert m["kind"] == "KrknUser"
    assert m["plural"] == "krknusers"
    assert m["short"] == "ku"
    assert m["group"] == "krkn.krkn-chaos.dev"
    assert m["version"] == "v1alpha1"
    assert m["scope"] == "Namespaced"
    # The kind's own doc comment is deliberately not carried: nothing renders it.
    assert "description" not in m


@pytest.mark.parametrize("kind,plural", [
    ("krknusers", "krknusers"), ("krkngraphruns", "krkngraphruns"),
    ("krknscenarioruns", "krknscenarioruns"),
])
def test_the_plural_is_already_lowercase_so_it_can_be_a_scenario_key(kind, plural):
    assert crd_meta(crd(kind))["plural"] == plural


def test_a_key_field_is_marked_secret_but_a_reference_to_one_is_not():
    """apiKey is about as common as CRD field names get, and an unmarked
    credential is the expensive direction to be wrong in."""
    from bot.crd_parser import _is_secret
    for leaf in ("apiKey", "privateKey", "spec.accessKey", "secretKey"):
        assert _is_secret(leaf) is True, leaf
    # _NOT_SECRET still wins, which is what keeps "key" safe to add.
    for leaf in ("apiKeyRef", "keyName", "spec.signingKeyPath", "keyType"):
        assert _is_secret(leaf) is False, leaf


def test_a_crd_whose_plural_would_escape_the_data_directory_is_refused(tmp_path):
    """plural becomes a directory under data/params/. Unchecked, a crafted CRD
    writes anywhere in the website checkout and git add -A commits it."""
    from bot.crd_parser import load_crd
    bad = tmp_path / "evil.yaml"
    bad.write_text('spec:\n  group: g\n  scope: Namespaced\n  names:\n'
                   '    kind: Evil\n    plural: ../../../.github/workflows\n'
                   '  versions: []\n', encoding="utf-8")
    with pytest.raises(ValueError) as e:
        load_crd(bad)
    assert "evil.yaml" in str(e.value) and "bad names" in str(e.value)


def test_a_file_that_is_not_a_crd_names_itself(tmp_path):
    """A stray kustomization.yaml in config/crd/bases used to abort the run with
    a bare KeyError naming no file."""
    from bot.crd_parser import load_crd
    stray = tmp_path / "kustomization.yaml"
    stray.write_text("resources:\n  - a.yaml\n", encoding="utf-8")
    with pytest.raises(ValueError) as e:
        load_crd(stray)
    assert "kustomization.yaml" in str(e.value) and "not a CRD" in str(e.value)
