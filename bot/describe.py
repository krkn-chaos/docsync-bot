"""Descriptions for params no source and no published page describes.
Python calls the model and writes the result, so nothing untrusted edits a file."""
import json
import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import asdict
from pathlib import Path

MAX_LEN = 160


def _timeout():
    """A bad value here must not crash the import: that would fail every
    target, including operator, which never calls the model."""
    try:
        # 30s was too tight: a free-tier endpoint answered the same prompt in
        # 20s, 27s and 83s within one hour, so this covers the slow end.
        return int(os.environ.get("DOC_SYNC_BOT_LLM_TIMEOUT", "120"))
    except ValueError:
        return 120


_TIMEOUT = _timeout()
# The endpoint the project runs. Only the key is a secret; the env overrides are
# for local experiments, so CI needs DOC_SYNC_BOT_LLM_API_KEY and nothing else.
_BASE_URL = "https://model.cclm-chaos.aws.rhperfscale.org/v1"
_MODEL = "qwen3.5:4b"
_NUMBER_OR_QUOTED = re.compile(r'"[^"]+"|\b\d+\b')
_PLACEHOLDER = re.compile(r'^(configures?|sets?|specifies|controls?) (the )?\w+\.?$', re.I)

_SYSTEM = (
    "Write one plain sentence describing each parameter, for a documentation "
    "table. Exactly one sentence, at most 25 words, no markdown. Describe only "
    "what the context states. Never state a default, range or unit that is not in that "
    "parameter's own record. Do not repeat the default value; the table shows it "
    "in its own column. If unsure, return an empty string for that parameter. "
    "Match the voice of the examples. Return JSON only: an object mapping each "
    "parameter name to its sentence."
)


def validate(text, record):
    """None if the text is usable, otherwise the reason it is not. The literal
    check is the important one: a confident wrong default is worse than a blank."""
    text = (text or "").strip()
    if not text:
        return "no description produced"
    if "\n" in text:
        return "rejected: contains a newline"
    if len(text) > MAX_LEN:
        return f"rejected: too long ({len(text)} > {MAX_LEN})"
    if _PLACEHOLDER.match(text):
        return "rejected: says nothing"
    # Substring, so "12" passes against a default of "120". Harmless: the point
    # is catching an invented value, not a narrower one.
    known = " ".join(str(v) for v in record.values() if v is not None)
    for lit in _NUMBER_OR_QUOTED.findall(text):
        if lit.strip('"') not in known:
            return f'rejected: contains a value not in the source ("{lit.strip(chr(34))}")'
    return None


def build_prompt(scenario, names, ctx):
    """The user message. Assembled the same way every run so the call is as
    reproducible as the model allows."""
    out = [f"Scenario: {scenario}", ""]
    if ctx.get("readme"):
        out += ["Overview:", ctx["readme"], ""]
    out.append("Parameters to describe:")
    for n in names:
        p = (ctx.get("params") or {}).get(n, {})
        out.append(f"- {n}")
        for label in ("type", "default", "allowed", "required"):
            if p.get(label):
                out.append(f"    {label}: {p[label]}")
    if ctx.get("examples"):
        out += ["", "Examples from the same scenario, for voice:"]
        out += [f"- {n}: {d}" for n, d in ctx["examples"]]
    return "\n".join(out)


def context(scn, names, records):
    """What the model gets. Curated in code rather than left to the model to go
    looking for, so the same run always sends the same thing."""
    scn = Path(scn)
    # Both: the README is usually a stub, but it is where a contributor writes up
    # a new parameter, and docs/<scenario>.md carries the scenario itself.
    sources = (scn / "README.md", scn.parent / "docs" / f"{scn.name}.md")
    wanted = set(names)
    return {
        "readme": "\n\n".join(
            p.read_text(encoding="utf-8-sig", errors="replace")[:2000]
            for p in sources if p.exists()),
        "params": {r.name: {"type": r.type or "",
                            "default": r.default if r.default is not None else "",
                            "allowed": ", ".join(r.allowed_values or []),
                            "required": "yes" if r.required else ""}
                   for r in records if r.name in wanted},
        # Real rows from the same source, so the sentence lands in house voice.
        "examples": [(r.name, r.description) for r in records if r.description][:5],
    }


def describe_fn(scn, records, reasons, memo=None):
    """llm_fn for resolve_descriptions. Anything the model writes is published;
    `reasons` carries what a reviewer should look at. memo is shared across a
    scenario's two sources, so a param on both tabs gets one description."""
    memo = {} if memo is None else memo
    by_name = {r.name: r for r in records}

    def fn(scenario, names):
        out = {n: memo[n] for n in names if n in memo}
        # A memo hit skipped validate, and this source's record may be stricter.
        for n, text in out.items():
            why = validate(text, asdict(by_name[n])) if n in by_name else None
            if why:
                reasons.setdefault(n, why)
        todo = [n for n in names if n not in memo]
        if not todo:
            return out
        errors = []
        got = describe(scenario, todo, context(scn, todo, records), errors=errors)
        for name, text in got.items():
            if not (text or "").strip():
                continue
            out[name] = memo[name] = text
            why = validate(text, asdict(by_name[name]))
            if why:
                reasons[name] = why
        # Never reached and reached-but-declined need opposite fixes, so the
        # report must not collapse them into one message.
        silent = [n for n in todo if n not in got]
        for n in todo:
            if n not in out:
                reasons.setdefault(n, f"model unavailable: {errors[0]}" if errors
                                   else "the model was asked and returned nothing")
        if silent and not errors:
            print(f"describe: model returned no text for {', '.join(silent)}",
                  file=sys.stderr)
        return out
    return fn


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """urllib keeps Authorization across a redirect and allows https -> http, so
    the endpoint itself could hand our key to any host in plaintext. Returning
    None raises the 3xx as an HTTPError, which describe() already reports."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


# Built once. build_opener drops the default redirect handler for this subclass.
_OPENER = urllib.request.build_opener(_NoRedirect)


def _post(url, key, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    with _OPENER.open(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read())


def _body(err, key=None):
    """The status alone names no cause: this endpoint answers 400 for an
    unsupported model and 400 for a malformed body. The body says which.

    Scrubbed before it is truncated, because this text ends up in a public commit
    message and Actions secret masking covers logs, not files. A 401 body is a
    common place for an endpoint to quote the credential back."""
    try:
        text = " ".join(err.read().decode("utf-8", "replace").split())
    except Exception:
        text = ""
    if key:
        text = text.replace(key, "***")
    return text[:200] or "no body"


def _unfence(text):
    """Strip a markdown fence. The prompt asks for bare JSON, but response_format
    is not portable across endpoints, so a fence cannot be ruled out."""
    text = text.strip()
    return text.partition("\n")[2].rsplit("```", 1)[0] if text.startswith("```") else text


def _fail(errors, msg):
    """Fail soft but say so. A silent {} is indistinguishable from "nothing
    described it", which makes a broken endpoint impossible to diagnose."""
    print(f"describe: {msg}", file=sys.stderr)
    if errors is not None:
        errors.append(msg)
    return {}


def describe(scenario, names, ctx, transport=None, errors=None):
    """{name: sentence} for the names that produced text.
    Returns {} on any failure (non-200, bad JSON, timeout, no credentials): a
    blank cell is already legal and reported, so a failed call never fails the
    run."""
    if not names:
        return {}
    key = os.environ.get("DOC_SYNC_BOT_LLM_API_KEY")
    if transport is None:
        if not key:
            return _fail(errors, "no DOC_SYNC_BOT_LLM_API_KEY set")
        base = os.environ.get("DOC_SYNC_BOT_LLM_BASE_URL", _BASE_URL).rstrip("/")
        # The key rides this connection as a bearer header, so a plaintext base
        # would put it on the wire. Refuse rather than send it.
        if not base.startswith("https://"):
            return _fail(errors, f"DOC_SYNC_BOT_LLM_BASE_URL must be https, got {base[:40]!r}")
        transport = lambda body: _post(base + "/chat/completions", key, body)  # noqa: E731
    # A small model told "return JSON only" still answers with something else.
    # Not every endpoint takes the field, so a 400 retries once without it.
    body = {"model": os.environ.get("DOC_SYNC_BOT_LLM_MODEL", _MODEL),
            "response_format": {"type": "json_object"},
            "temperature": 0,
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user",
                          "content": build_prompt(scenario, names, ctx)}]}
    try:
        payload = transport(body)
    except urllib.error.HTTPError as e:
        if e.code != 400 or "response_format" not in body:
            return _fail(errors, f"endpoint returned HTTP {e.code}: {_body(e, key)}")
        body.pop("response_format")
        print("describe: endpoint rejected response_format, retrying without it",
              file=sys.stderr)
        try:
            payload = transport(body)
        except urllib.error.HTTPError as e2:
            return _fail(errors, f"endpoint returned HTTP {e2.code}: {_body(e2, key)}")
        except Exception as e2:
            return _fail(errors, f"endpoint unreachable ({type(e2).__name__})")
    except Exception as e:
        return _fail(errors, f"endpoint unreachable ({type(e).__name__})")
    try:
        raw = json.loads(_unfence(payload["choices"][0]["message"]["content"]))
    except Exception as e:
        return _fail(errors, f"unexpected response shape ({type(e).__name__})")
    if not isinstance(raw, dict):
        return _fail(errors, "response JSON was not an object")
    # A model that wraps the mapping in one key, {"parameters": {...}}, is
    # answering correctly in the wrong shape. Unwrap rather than drop it.
    if not any(n in raw for n in names) and len(raw) == 1:
        inner = next(iter(raw.values()))
        if isinstance(inner, dict):
            raw = inner
    out = {n: raw[n].strip() for n in names
            if isinstance(raw.get(n), str) and raw[n].strip()}
    if not out:
        # Tells "declined" apart from "answered in a shape we do not read".
        # Content only, no headers, so the key cannot ride along.
        body_text = " ".join(str(payload["choices"][0]["message"]["content"]).split())
        print(f"describe: no requested name in the reply: {body_text[:200]!r}",
              file=sys.stderr)
    return out
