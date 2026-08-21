import io
import urllib.error
import pytest

from bot.describe import (MAX_LEN, build_prompt, context, describe, describe_fn,
                          validate)
from bot.parser import ParamRecord

CTX = {"params": {"BLOCK_SIZE": {"type": "number", "default": "512"}}}


def reply(content):
    return lambda body: {"choices": [{"message": {"content": content}}]}


def boom(exc):
    def t(body):
        raise exc
    return t


def test_a_good_response_is_returned():
    t = reply('{"BLOCK_SIZE": "Size in bytes of each block written to the volume"}')
    assert describe("pvc-scenario", ["BLOCK_SIZE"], CTX, transport=t) == {
        "BLOCK_SIZE": "Size in bytes of each block written to the volume"}


def test_an_unreachable_endpoint_returns_nothing():
    """A blank cell is already legal and already reported, so one flaky endpoint
    must not fail the whole sync."""
    assert describe("s", ["X"], CTX, transport=boom(OSError("refused"))) == {}


def test_a_timeout_returns_nothing():
    assert describe("s", ["X"], CTX, transport=boom(TimeoutError())) == {}


def test_malformed_json_returns_nothing():
    assert describe("s", ["X"], CTX, transport=reply("here you go: not json")) == {}


def test_a_response_missing_the_choices_key_returns_nothing():
    assert describe("s", ["X"], CTX, transport=lambda b: {"error": "nope"}) == {}


def test_a_json_array_instead_of_an_object_returns_nothing():
    assert describe("s", ["X"], CTX, transport=reply('["not", "an object"]')) == {}


def test_a_name_that_was_not_asked_for_is_dropped():
    t = reply('{"X": "fine", "MADE_UP": "not asked for"}')
    assert set(describe("s", ["X"], CTX, transport=t)) == {"X"}


def test_an_empty_string_is_dropped_rather_than_stored():
    assert describe("s", ["X"], CTX, transport=reply('{"X": "   "}')) == {}


def test_no_names_makes_no_call():
    assert describe("s", [], CTX, transport=boom(AssertionError("called"))) == {}


def test_no_credentials_makes_no_call():
    assert describe("s", ["X"], CTX) == {}


def test_the_prompt_carries_the_record_and_voice_examples():
    ctx = dict(CTX, examples=[("PORT", "Port to publish kraken status to")],
               readme="Fills a PVC.")
    p = build_prompt("pvc-scenario", ["BLOCK_SIZE"], ctx)
    assert "type: number" in p and "default: 512" in p
    assert "Port to publish kraken status to" in p
    assert "Fills a PVC." in p


def test_context_takes_examples_only_from_described_params(tmp_path):
    """Voice examples come from real rows; an undescribed param has nothing to
    teach and must not appear as an empty example."""
    (tmp_path / "README.md").write_text("Fills a PVC.", encoding="utf-8")
    recs = [ParamRecord(name="BLOCK_SIZE", type="number", default="512"),
            ParamRecord(name="PORT", description="Port to publish to")]
    ctx = context(tmp_path, ["BLOCK_SIZE"], recs)
    assert ctx["readme"] == "Fills a PVC."
    assert ctx["params"] == {"BLOCK_SIZE": {"type": "number", "default": "512",
                                            "allowed": "", "required": ""}}
    assert ctx["examples"] == [("PORT", "Port to publish to")]


def test_context_without_a_readme_is_still_usable(tmp_path):
    ctx = context(tmp_path, ["X"], [ParamRecord(name="X")])
    assert ctx["readme"] == ""


def test_the_overview_is_the_readme_and_the_scenario_doc(tmp_path):
    """The README is normally a stub, but it is where a contributor writes up a
    new parameter, so dropping either one loses the context the model needs."""
    scn = tmp_path / "http-load"
    scn.mkdir()
    (scn / "README.md").write_text(
        "See [doc](../docs/http-load.md)\n\n"
        "## Redirect handling\n"
        "`FOLLOW_REDIRECTS` decides what a pod does when a target redirects.",
        encoding="utf-8")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "http-load.md").write_text(
        "This scenario generates distributed HTTP load with Vegeta pods.",
        encoding="utf-8")
    ctx = context(scn, ["FOLLOW_REDIRECTS"], [ParamRecord(name="FOLLOW_REDIRECTS")])
    assert "Redirect handling" in ctx["readme"]
    assert "distributed HTTP load" in ctx["readme"]


def test_the_readme_is_enough_when_there_is_no_scenario_doc(tmp_path):
    scn = tmp_path / "solo"
    scn.mkdir()
    (scn / "README.md").write_text("Everything worth knowing.", encoding="utf-8")
    ctx = context(scn, ["X"], [ParamRecord(name="X")])
    assert ctx["readme"] == "Everything worth knowing."


def test_the_memo_stops_a_second_call_for_the_same_param(tmp_path, monkeypatch):
    """A param on both tabs must get one description. Two calls return two
    different sentences, so the tabs would disagree about the same parameter."""
    calls = []

    def fake(scenario, names, ctx, transport=None, errors=None):
        calls.append(list(names))
        return {n: "Written once." for n in names}

    monkeypatch.setattr("bot.describe.describe", fake)
    recs, memo = [ParamRecord(name="X")], {}
    hub = describe_fn(tmp_path, recs, {}, memo)
    ctl = describe_fn(tmp_path, recs, {}, memo)
    assert hub("s", ["X"]) == {"X": "Written once."}
    assert ctl("s", ["X"]) == {"X": "Written once."}
    assert calls == [["X"]]


def test_a_memo_hit_is_validated_against_its_own_source(tmp_path, monkeypatch):
    """The second tab reuses the text but has its own record. Skipping validate
    there loses the flag whenever that record is the stricter of the two."""
    def fake(scenario, names, ctx, transport=None, errors=None):
        return {n: "Waits 30 seconds between retries." for n in names}

    monkeypatch.setattr("bot.describe.describe", fake)
    memo = {}
    # 30 is in this record, so the first source has nothing to flag.
    lenient = {}
    describe_fn(tmp_path, [ParamRecord(name="W", default="30")], lenient, memo)("s", ["W"])
    assert lenient == {}
    # The second source's record does not carry it, so the row must be flagged.
    strict = {}
    describe_fn(tmp_path, [ParamRecord(name="W")], strict, memo)("s", ["W"])
    assert "30" in strict["W"]


def test_a_failed_call_is_reported_as_unavailable_not_as_undescribed(tmp_path, monkeypatch):
    """"The endpoint is broken" and "nothing describes it" need opposite fixes."""
    def broken(scenario, names, ctx, transport=None, errors=None):
        errors.append("endpoint returned HTTP 401")
        return {}

    monkeypatch.setattr("bot.describe.describe", broken)
    reasons = {}
    assert describe_fn(tmp_path, [ParamRecord(name="X")], reasons)("s", ["X"]) == {}
    assert reasons["X"] == "model unavailable: endpoint returned HTTP 401"


def test_an_http_error_names_the_status_and_the_body():
    """The status alone is not actionable: this endpoint answers 400 for an
    unsupported model and 400 for a malformed body."""
    import io
    import urllib.error

    def boom(_):
        raise urllib.error.HTTPError(
            "u", 400, "Bad Request", {},
            io.BytesIO(b'{"error":{"message":"The requested model\n is not supported."}}'))

    errors = []
    assert describe("s", ["X"], CTX, transport=boom, errors=errors) == {}
    assert errors == ['endpoint returned HTTP 400: {"error":{"message":"The requested '
                      'model is not supported."}}']


def test_an_unreadable_error_body_still_names_the_status():
    import urllib.error

    def boom(_):
        raise urllib.error.HTTPError("u", 401, "Unauthorized", {}, None)

    errors = []
    assert describe("s", ["X"], CTX, transport=boom, errors=errors) == {}
    assert errors == ["endpoint returned HTTP 401: no body"]


def test_a_missing_key_is_named():
    """The key is the only setting CI supplies, so it is the only one to report."""
    errors = []
    assert describe("s", ["X"], CTX, errors=errors) == {}
    assert errors == ["no DOC_SYNC_BOT_LLM_API_KEY set"]


def test_a_plaintext_base_url_is_refused_before_the_key_is_sent(monkeypatch):
    """DOC_SYNC_BOT_LLM_BASE_URL is deployment-supplied and the key rides it as a bearer
    header, so http would put the credential on the wire."""
    monkeypatch.setenv("DOC_SYNC_BOT_LLM_API_KEY", "sekrit")
    monkeypatch.setenv("DOC_SYNC_BOT_LLM_BASE_URL", "http://model.example/v1")
    errors = []
    assert describe("s", ["X"], CTX, errors=errors) == {}
    assert errors and "must be https" in errors[0]
    assert "sekrit" not in errors[0]


def test_the_timeout_is_configurable(monkeypatch):
    """30s cut off the slow end of a real endpoint: 20.6s, 27.4s and 83.3s within
    one hour on a free tier."""
    import importlib
    import bot.describe as d
    monkeypatch.setenv("DOC_SYNC_BOT_LLM_TIMEOUT", "45")
    assert importlib.reload(d)._TIMEOUT == 45
    monkeypatch.delenv("DOC_SYNC_BOT_LLM_TIMEOUT")
    assert importlib.reload(d)._TIMEOUT == 120


def test_a_bad_timeout_value_does_not_crash_the_import(monkeypatch):
    """A bad value here would otherwise fail every target, including operator,
    which never calls the model."""
    import importlib
    import bot.describe as d
    monkeypatch.setenv("DOC_SYNC_BOT_LLM_TIMEOUT", "45s")
    assert importlib.reload(d)._TIMEOUT == 120
    monkeypatch.delenv("DOC_SYNC_BOT_LLM_TIMEOUT")
    importlib.reload(d)


def test_the_key_alone_produces_the_full_request(monkeypatch):
    """The URL is built by concatenation, so a stray slash or a doubled /v1
    would 404 at runtime with nothing in the suite to catch it."""
    seen = {}

    def fake_post(url, key, body):
        seen.update(url=url, key=key, model=body["model"])
        return {"choices": [{"message": {"content": '{"X": "Plain."}'}}]}

    monkeypatch.setattr("bot.describe._post", fake_post)
    monkeypatch.setenv("DOC_SYNC_BOT_LLM_API_KEY", "k")
    assert describe("s", ["X"], CTX) == {"X": "Plain."}
    assert seen == {
        "url": "https://model.cclm-chaos.aws.rhperfscale.org/v1/chat/completions",
        "key": "k",
        "model": "qwen3.5:4b",
    }


def test_a_flagged_description_is_still_published(tmp_path, monkeypatch):
    """The bot no longer decides. Placeholder text reaches the table and the
    validator's reason rides along for the reviewer."""
    monkeypatch.setattr(
        "bot.describe.describe",
        lambda s, n, c, transport=None, errors=None: {x: "Configures port." for x in n})
    reasons, memo = {}, {}
    fn = describe_fn(tmp_path, [ParamRecord(name="X")], reasons, memo)
    assert fn("s", ["X"]) == {"X": "Configures port."}
    assert memo == {"X": "Configures port."}
    assert reasons["X"] == "rejected: says nothing"


@pytest.mark.parametrize("text,reason", [
    ("", "no description produced"),
    ("one\ntwo", "rejected: contains a newline"),
    ("x" * 161, "rejected: too long (161 > 160)"),
    ("Configures port.", "rejected: says nothing"),
])
def test_validator_reasons(text, reason):
    assert validate(text, {"name": "PORT"}) == reason


def test_text_that_invents_a_value_is_flagged():
    """A model that writes 1024 when the source says 512 reads as authoritative
    and is wrong. It still publishes, but the reviewer is told."""
    assert validate("Block size, default 1024", {"name": "B", "default": "512"}) == \
        'rejected: contains a value not in the source ("1024")'


def test_a_value_that_is_in_the_source_is_accepted():
    assert validate("Block size in bytes, defaults to 512",
                    {"name": "B", "default": "512"}) is None


def test_the_real_model_output_for_retry_wait_passes():
    """What gpt-4o-mini actually returned for globals/RETRY_WAIT."""
    assert validate("Time to wait before retrying an operation.",
                    {"name": "RETRY_WAIT", "default": "120"}) is None


@pytest.mark.parametrize("content", [
    '{"X": "Plain."}',
    '```json\n{"X": "Plain."}\n```',
    '```\n{"X": "Plain."}\n```',
])
def test_a_fenced_reply_parses(content):
    """Without response_format the model may wrap the object in a code fence."""
    assert describe("s", ["X"], CTX, transport=reply(content)) == {"X": "Plain."}


def test_a_redirect_is_refused_rather_than_followed():
    """urllib keeps Authorization across a hop and permits https -> http, so a
    redirect the endpoint chooses would put the key on the wire in plaintext.
    The https check on the base URL cannot see this, it only sees hop one."""
    import http.server
    import threading
    import urllib.error

    from bot.describe import _post

    seen = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            # Drained before replying, or Windows aborts the half-written request.
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            seen.append(self.headers.get("Authorization"))
            self.send_response(302)
            self.send_header("Location", "http://127.0.0.1:9/leaked")
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        with pytest.raises(urllib.error.HTTPError) as e:
            _post(f"http://127.0.0.1:{srv.server_port}/v1/chat/completions",
                  "sekrit", {"model": "m"})
        assert e.value.code == 302
    finally:
        srv.shutdown()
    # Hop one carries the key by design. The whole point is that there is no two.
    assert seen == ["Bearer sekrit"]


def test_an_error_body_does_not_carry_the_key_into_the_report(monkeypatch):
    """The gap table is appended to a commit message on a public PR, and Actions
    secret masking covers log output, not file contents."""
    import io
    import urllib.error

    monkeypatch.setenv("DOC_SYNC_BOT_LLM_API_KEY", "nvapi-SEKRIT-0123456789")

    def boom(body):
        raise urllib.error.HTTPError(
            "https://model.example/v1", 401, "Unauthorized", {},
            io.BytesIO(b'{"error":{"message":"Incorrect API key provided: '
                       b'nvapi-SEKRIT-0123456789. Check your key."}}'))

    errors = []
    assert describe("s", ["X"], CTX, transport=boom, errors=errors) == {}
    assert errors and "HTTP 401" in errors[0]
    assert "nvapi-SEKRIT-0123456789" not in errors[0]
    assert "***" in errors[0]


def test_a_parameter_the_model_declined_is_not_reported_as_having_no_source():
    """Three states need three fixes: the key is wrong, nothing describes it, or
    the model was asked and gave nothing. The third used to read as the second."""
    import bot.describe as d
    from bot.descriptions import resolve_descriptions
    from bot.describe import describe_fn

    real = d.describe
    d.describe = lambda *a, **k: {}
    try:
        recs = [ParamRecord(name="HTTP2")]
        reasons = {}
        resolve_descriptions("http-load", [ParamRecord(name="HTTP2")], {},
                             describe_fn("http-load", recs, reasons))
    finally:
        d.describe = real
    assert reasons["HTTP2"] == "the model was asked and returned nothing"


def test_response_format_is_requested():
    sent = {}

    def transport(body):
        sent.update(body)
        return {"choices": [{"message": {"content": '{"A": "text"}'}}]}

    describe("s", ["A"], {}, transport=transport)
    assert sent["response_format"] == {"type": "json_object"}


def test_an_endpoint_that_rejects_response_format_still_works(capsys):
    """Not every endpoint accepts the field. A 400 must retry without it rather
    than lose the run, which is exactly the old behaviour."""
    calls = []

    def transport(body):
        calls.append(dict(body))
        if "response_format" in body:
            raise urllib.error.HTTPError("u", 400, "bad", {}, io.BytesIO(b"no such field"))
        return {"choices": [{"message": {"content": '{"A": "text"}'}}]}

    got = describe("s", ["A"], {}, transport=transport)
    assert got == {"A": "text"}
    assert len(calls) == 2 and "response_format" not in calls[1]


def test_a_non_400_is_not_retried():
    calls = []

    def transport(body):
        calls.append(1)
        raise urllib.error.HTTPError("u", 401, "no", {}, io.BytesIO(b"bad key"))

    errors = []
    assert describe("s", ["A"], {}, transport=transport, errors=errors) == {}
    assert len(calls) == 1 and "401" in errors[0]


def test_a_mapping_wrapped_in_one_key_is_unwrapped():
    def transport(body):
        return {"choices": [{"message":
                {"content": '{"parameters": {"A": "text"}}'}}]}

    assert describe("s", ["A"], {}, transport=transport) == {"A": "text"}


def test_a_reply_with_no_requested_name_is_printed(capsys):
    def transport(body):
        return {"choices": [{"message": {"content": '{"other": "text"}'}}]}

    assert describe("s", ["A"], {}, transport=transport) == {}
    assert "no requested name in the reply" in capsys.readouterr().err


def test_an_over_long_reply_is_published_verbatim():
    """No constraint on what the model writes. Over-length is a review note,
    not a reason to throw the description away."""
    long = ("Decides whether the generator follows redirect chains and measures "
            "the final response. When disabled it records the redirect itself "
            "and moves on to the next request instead of chasing it further.")
    assert len(long) > MAX_LEN

    recs = [ParamRecord(name="FOLLOW_REDIRECTS")]
    reasons = {}
    import bot.describe as d
    real = d.describe
    d.describe = lambda *a, **k: {"FOLLOW_REDIRECTS": long}
    try:
        got = describe_fn("http-load", recs, reasons)("http-load", ["FOLLOW_REDIRECTS"])
    finally:
        d.describe = real
    assert got["FOLLOW_REDIRECTS"] == long
    assert reasons["FOLLOW_REDIRECTS"].startswith("rejected: too long")


