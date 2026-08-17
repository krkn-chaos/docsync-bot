from bot.report import main, render, write_report


def _row(md, prefix):
    return [l for l in md.splitlines() if l.startswith(prefix)][0]


def test_a_pipe_in_the_text_cannot_add_a_column():
    """An escaped \\| still contains a pipe, so count the unescaped ones."""
    md = render([("s", "krkn-hub", "P", "llm", "takes a|b|c")])
    row = _row(md, "| s ")
    assert row.count("|") - row.count(r"\|") == 5
    assert r"\|" in row


def test_a_newline_in_the_text_cannot_break_the_row():
    md = render([("s", "krkn-hub", "P", "llm", "first line\nsecond line")])
    assert "first line second line" in md


def test_carried_and_generated_share_the_first_section():
    md = render([("s", "krkn-hub", "A", "published-table", "from the page"),
                 ("s", "krkn-hub", "B", "llm", "written")])
    assert "### Descriptions not taken from source (2)" in md
    assert "published-table" in md and "llm" in md


def test_blank_params_get_their_own_section_with_a_reason():
    md = render([("s", "krkn-hub", "RETRY_WAIT", "", "no description in any source")])
    assert "### Still blank (1)" in md
    assert "no description in any source" in md
    assert "trailing comment in env.sh" in md


def test_a_param_on_both_tabs_is_reported_once():
    """The same param appears on the krkn-hub and krknctl tabs; one row is enough."""
    md = render([("s", "krkn-hub", "X", "llm", "same text"),
                 ("s", "krknctl", "X", "llm", "same text")])
    assert md.count("| s | X |") == 1
    assert "### Descriptions not taken from source (1)" in md


def test_an_orphan_keeps_its_source():
    """Which tab lost the row is the useful part there."""
    md = render([("s", "krkn-hub", "X", "orphan", ""),
                 ("s", "krknctl", "X", "orphan", "")])
    assert "| s | krkn-hub | X |" in md
    assert "| s | krknctl | X |" in md


def test_an_orphan_row_is_reported_separately():
    """A published row no source produces is a whole row dropped, not a cell."""
    md = render([("node-scenarios", "krknctl", "disks", "orphan", "")])
    assert "### Dropped, not in any source (1)" in md
    assert "| node-scenarios | krknctl | disks |" in md


def test_output_is_sorted_so_reruns_are_byte_identical():
    a = render([("b", "krkn-hub", "Z", "llm", "z"), ("a", "krkn-hub", "Y", "llm", "y")])
    b = render([("a", "krkn-hub", "Y", "llm", "y"), ("b", "krkn-hub", "Z", "llm", "z")])
    assert a == b


def test_a_clean_run_renders_nothing():
    """No sections at all, so a normal commit message stays normal."""
    assert render([]) == ""


def test_rows_from_several_targets_merge_into_one_section(tmp_path, monkeypatch):
    """The workflow runs the bot once per target; rendering per target would
    repeat every heading."""
    monkeypatch.setenv("GH_AW_REPORT_DIR", str(tmp_path))
    write_report([("a", "krkn-hub", "X", "llm", "one")])
    write_report([("b", "krkn-hub", "Y", "llm", "two")])
    main()
    md = (tmp_path / "gaps.md").read_text(encoding="utf-8")
    assert md.count("### Descriptions not taken from source") == 1
    assert "### Descriptions not taken from source (2)" in md


def test_writing_without_a_report_dir_is_a_no_op(monkeypatch):
    monkeypatch.delenv("GH_AW_REPORT_DIR", raising=False)
    write_report([("a", "krkn-hub", "X", "llm", "one")])
