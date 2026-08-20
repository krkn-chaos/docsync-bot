from bot.parser import ParamRecord
from bot.descriptions import resolve_descriptions


def fake_llm(scenario, names):
    return {n: f"LLM desc for {n}." for n in names}


def test_source_wins_over_the_committed_file():
    """The regression this file exists for. Under the old order a better
    description upstream changed nothing, because the generated file won."""
    recs = [ParamRecord(name="P", description="improved upstream wording")]
    existing = {"P": "whatever was generated last time"}
    out, _ = resolve_descriptions("scn", recs, existing, fake_llm)
    assert out["P"] == "improved upstream wording"


def test_existing_is_the_fallback_when_the_source_says_nothing():
    """Some params are described nowhere. What is already in the file beats
    nothing, so it still fills the gap."""
    recs = [ParamRecord(name="PORT")]
    out, called = resolve_descriptions("scn", recs, {"PORT": "kept"}, fake_llm)
    assert out["PORT"] == "kept"
    assert called == []


def test_llm_only_for_params_nothing_describes():
    recs = [ParamRecord(name="SRC", description="from src"),
            ParamRecord(name="NEW")]
    out, gaps = resolve_descriptions("scn", recs, {}, fake_llm)
    assert out["SRC"] == "from src"
    assert out["NEW"] == "LLM desc for NEW."
    assert gaps == [("NEW", "llm", "LLM desc for NEW.")]
    assert recs[1].description_source == "llm"


def test_no_llm_call_when_all_resolved():
    recs = [ParamRecord(name="A", description="d")]
    out, gaps = resolve_descriptions("scn", recs, {}, fake_llm)
    assert gaps == []


def test_an_undescribed_param_is_left_blank_not_papered_over():
    """The old fallback wrote "Configures port.", which reads as finished and
    says nothing. An empty cell shows a human there is work to do."""
    recs = [ParamRecord(name="PORT")]
    out, gaps = resolve_descriptions("scn", recs, {}, lambda s, n: {})
    assert out["PORT"] == ""
    assert gaps == [("PORT", "", "no description in any source and no published row")]


def test_a_published_description_is_carried_when_no_source_has_one():
    """node-scenarios/VERIFY_SESSION: the page has wording, no source does."""
    recs = [ParamRecord(name="VERIFY_SESSION")]
    out, gaps = resolve_descriptions("scn", recs, {}, lambda s, n: {},
                                     published={"VERIFY_SESSION": "Verify the SSH session"})
    assert out["VERIFY_SESSION"] == "Verify the SSH session"
    assert recs[0].description_source == "published-table"
    assert gaps == [("VERIFY_SESSION", "published-table", "Verify the SSH session")]


def test_a_source_description_still_wins_over_the_published_one():
    """CLOUD_TYPE's published list omits azure and gcp. The source is right."""
    recs = [ParamRecord(name="CLOUD_TYPE", description="aws, azure, gcp")]
    out, gaps = resolve_descriptions("scn", recs, {}, fake_llm,
                                     published={"CLOUD_TYPE": "aws, vmware"})
    assert out["CLOUD_TYPE"] == "aws, azure, gcp"
    assert gaps == []


def test_the_published_page_wins_over_the_existing_file():
    """Both only coexist while a page is still being migrated. The page is the
    human-written one, and the file would otherwise shadow it forever."""
    recs = [ParamRecord(name="X")]
    out, _ = resolve_descriptions("scn", recs, {"X": "from yaml"}, fake_llm,
                                  published={"X": "from page"})
    assert out["X"] == "from page"


def test_the_existing_file_wins_over_the_other_source():
    """Once the page is converted its prose survives only in the file, so a
    borrow must not overwrite it on the next run."""
    recs = [ParamRecord(name="X", borrowed_description="from krknctl")]
    out, _ = resolve_descriptions("scn", recs, {"X": "from yaml"}, fake_llm)
    assert out["X"] == "from yaml"


def test_the_published_table_is_tried_before_the_llm():
    recs = [ParamRecord(name="X")]
    out, gaps = resolve_descriptions("scn", recs, {}, fake_llm,
                                     published={"X": "from page"})
    assert out["X"] == "from page"


def test_scenario_doc_fills_a_param_env_sh_leaves_bare():
    """krkn-hub documents most params in docs/<scenario>.md, not beside the
    export. Without this rung they reach the model, which correctly declines."""
    recs = [ParamRecord(name="HTTP2")]
    out, gaps = resolve_descriptions(
        "http-load", recs, {}, lambda s, n: {},
        doc={"HTTP2": "Enable HTTP/2 protocol support"})
    assert out["HTTP2"] == "Enable HTTP/2 protocol support"
    assert recs[0].description_source == "hub-doc"
    # Reported, so the commit message says where the wording came from. It is
    # not the row's own source file, so a reviewer has to be able to see it.
    assert gaps == [("HTTP2", "hub-doc", "Enable HTTP/2 protocol support")]


def test_a_curated_published_row_outranks_the_scenario_doc():
    """The published table is the one rung a human wrote for this site, so the
    doc must not overwrite it on adoption."""
    recs = [ParamRecord(name="TIMEOUT")]
    out, _ = resolve_descriptions(
        "http-load", recs, {}, lambda s, n: {},
        published={"TIMEOUT": "Curated wording from the page"},
        doc={"TIMEOUT": "Per-request timeout (e.g. 10s, 30s)"})
    assert out["TIMEOUT"] == "Curated wording from the page"


def test_the_doc_never_costs_a_model_call():
    recs = [ParamRecord(name="RUNS")]

    def boom(scenario, names):
        raise AssertionError(f"model called for {names}")

    out, _ = resolve_descriptions("http-load", recs, {}, boom,
                                  doc={"RUNS": "Number of times it runs"})
    assert out["RUNS"] == "Number of times it runs"
