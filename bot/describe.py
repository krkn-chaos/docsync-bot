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

MAX_LEN = 120
_TIMEOUT = 30
# The endpoint the project runs. Only the key is a secret; the env overrides are
# for local experiments, so CI needs LLM_API_KEY and nothing else.
_BASE_URL = "https://model.cclm-chaos.aws.rhperfscale.org/v1"
_MODEL = "qwen3.5:4b"
_NUMBER_OR_QUOTED = re.compile(r'"[^"]+"|\b\d+\b')
_PLACEHOLDER = re.compile(r'^(configures?|sets?|specifies|controls?) (the )?\w+\.?$', re.I)

_SYSTEM = (
    "Write one plain sentence describing each parameter, for a documentation "
    "table. One sentence, at most 120 characters, no markdown. Describe only what "
    "the context states. Never state a default, range or unit that is not in that "
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
    readme = Path(scn) / "README.md"
    wanted = set(names)
    return {
        "readme": readme.read_text(encoding="utf-8")[:2000] if readme.exists() else "",
        "params": {r.name: {"type": r.type or "",
                            "default": r.default if r.default is not None else "",
                            "allowed": ", ".join(r.allowed_values or []),
                            "required": "yes" if r.required else ""}
                   for r in records if r.name in wanted},
        # Real rows from the same source, so the sentence lands in house voice.
        "examples": [(r.name, r.description) for r in records if r.description][:5],
    }


def describe_fn(scn, records, reasons, memo=None):
    """llm_fn for resolve_descriptions. Rejections go into `reasons` so the report
    says why a cell is blank, not only that it is. memo is shared across a
    scenario's two sources, so a param on both tabs gets one description."""
    memo = {} if memo is None else memo
    by_name = {r.name: r for r in records}

    def fn(scenario, names):
        out = {n: memo[n] for n in names if n in memo}
        todo = [n for n in names if n not in memo]
        if not todo:
            return out
        errors = []
        got = describe(scenario, todo, context(scn, todo, records), errors=errors)
        for name, text in got.items():
            why = validate(text, asdict(by_name[name]))
            if why is None:
                out[name] = memo[name] = text
            else:
                reasons[name] = why
        # "the model was never reached" and "nothing describes it" need opposite
        # fixes, so the report must not collapse them into one message.
        for n in todo:
            if errors and n not in out:
                reasons.setdefault(n, f"model unavailable: {errors[0]}")
        return out
    return fn


def _post(url, key, body):
    req = urllib.request.Request(
        url, data=json.dumps(body).encode("utf-8"), method="POST",
        headers={"Authorization": f"Bearer {key}",
                 "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=_TIMEOUT) as r:
        return json.loads(r.read())


def _body(err):
    """The status alone names no cause: this endpoint answers 400 for an
    unsupported model and 400 for a malformed body. The body says which."""
    try:
        text = " ".join(err.read().decode("utf-8", "replace").split())
    except Exception:
        text = ""
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
    Returns {} on any failure (non-200, bad JSON, timeout, unset config): a blank
    cell is already legal and reported, so a failed call never fails the run."""
    if not names:
        return {}
    if transport is None:
        key = os.environ.get("LLM_API_KEY")
        if not key:
            return _fail(errors, "no LLM_API_KEY set")
        url = os.environ.get("LLM_BASE_URL", _BASE_URL).rstrip("/") + "/chat/completions"
        transport = lambda body: _post(url, key, body)  # noqa: E731
    # No response_format: some endpoints reject the field outright, and the reply
    # is parsed with json.loads either way.
    body = {"model": os.environ.get("LLM_MODEL", _MODEL),
            "temperature": 0,
            "messages": [{"role": "system", "content": _SYSTEM},
                         {"role": "user",
                          "content": build_prompt(scenario, names, ctx)}]}
    try:
        payload = transport(body)
    except urllib.error.HTTPError as e:
        return _fail(errors, f"endpoint returned HTTP {e.code}: {_body(e)}")
    except Exception as e:
        return _fail(errors, f"endpoint unreachable ({type(e).__name__})")
    try:
        raw = json.loads(_unfence(payload["choices"][0]["message"]["content"]))
    except Exception as e:
        return _fail(errors, f"unexpected response shape ({type(e).__name__})")
    if not isinstance(raw, dict):
        return _fail(errors, "response JSON was not an object")
    return {n: raw[n].strip() for n in names
            if isinstance(raw.get(n), str) and raw[n].strip()}
