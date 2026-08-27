import re
import json
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ParamRecord:
    """Normalized parameter record shared by all source extractors."""

    name: str
    default: str | None = None  # None = no default declared in source
    required: bool = False
    type: str | None = None
    description: str | None = None
    description_source: str | None = None  # "env-comment" | "krknctl"
    allowed_values: list[str] | None = None
    group: str | None = None  # krknctl-input.json "group", global params only
    flag: str | None = None   # krknctl CLI flag, e.g. cerberus-enabled
    secret: bool = False      # krknctl "secret", keep the value off a command line
    # Wording from the other source, for a param this one does not describe. Kept
    # apart from description so it cannot outrank the curated published table.
    borrowed_description: str | None = None


EXPORT_LINE_RE = re.compile(r'^\s*export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$')
VAR_NAME_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')


def _strip_quotes(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] and value[0] in ('"', "'"):
        return value[1:-1]
    return value


def _find_closing_brace(text: str) -> int | None:
    """Index of the brace closing an already-open ${...}, or None.
    Quote-aware: braces inside quoted sections (e.g. :="a}b") and
    backslash-escaped characters do not affect the depth count."""
    depth = 1
    quote = None
    i = 0
    while i < len(text):
        ch = text[i]
        if ch == "\\" and quote != "'":
            i += 2
            continue
        if quote:
            if ch == quote:
                quote = None
        elif ch in ('"', "'"):
            quote = ch
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return i
        i += 1
    return None


def _parse_export_line(line: str) -> ParamRecord | None:
    m = EXPORT_LINE_RE.match(line)
    if not m:
        return None
    rhs = m.group(2)

    # Unwrap a quote around the whole expansion: export V="${V:-x}"
    quote = None
    if rhs[:1] in ('"', "'") and rhs[1:3] == "${":
        quote = rhs[0]
        rhs = rhs[1:]

    # Command substitution and plain string assignments are not tunable params
    if not rhs.startswith("${"):
        return None

    name_m = VAR_NAME_RE.match(rhs, 2)
    if not name_m:
        return None
    name = name_m.group(0)
    rest = rhs[name_m.end():]

    # Find the closing brace, counting nested braces (defaults like "{}" or
    # regex patterns containing {1,2} appear in real krkn-hub env.sh files)
    body_end = _find_closing_brace(rest)
    if body_end is None:
        return None
    body = rest[:body_end]
    tail = rest[body_end + 1:]
    if quote and tail[:1] == quote:
        tail = tail[1:]

    # A param declaration ends at the expansion; anything after it other than
    # a comment (e.g. PATH=${PATH}:/extra concatenation) is not a declaration
    if tail.strip() and not tail.lstrip().startswith("#"):
        return None

    if body == "":
        # export A=${B} re-exports something else, e.g. KUBECONFIG=${KRKN_KUBE_CONFIG}.
        # That is plumbing, not a knob. export A=${A} is a real required input.
        if name != m.group(1):
            return None
        # export VAR=${VAR} -- declared but no default: required
        default, required = None, True
    elif body.startswith((":=", ":-")):
        default, required = _strip_quotes(body[2:]), False
    elif body.startswith(":"):
        # ${VAR:x} is substring expansion, not a default -- always "" on an
        # unset VAR regardless of x. Verified in bash.
        default, required = "", False
    else:
        # Other expansions (%, #, /, etc.) -- not a tunable default
        return None

    # Harvest a trailing inline comment as the description
    description = None
    comment_m = re.match(r'\s*#+\s*(.*\S)', tail)
    if comment_m:
        description = comment_m.group(1)

    return ParamRecord(
        name=name,
        default=default,
        required=required,
        description=description,
        description_source="env-comment" if description else None,
    )


def extract_env_params(path: Path) -> list[ParamRecord]:
    """Extract ParamRecords from an env.sh file. First declaration of a
    variable wins (later re-exports like KUBECONFIG=${KRKN_KUBE_CONFIG}
    must not demote an already-seen default to required)."""
    records: dict[str, ParamRecord] = {}
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        rec = _parse_export_line(line)
        if rec is not None and rec.name not in records:
            records[rec.name] = rec
    _resolve_references(records)
    return list(records.values())


# Only $NAME and ${NAME}. Braces have to match, or a literal default like
# "${FOO" would be mistaken for a reference and silently dropped.
_REF_RE = re.compile(r'^\$(?:([A-Za-z_][A-Za-z0-9_]*)|\{([A-Za-z_][A-Za-z0-9_]*)\})$')


# Both "|NAME| desc |" and "NAME | desc |" are in use, so the leading pipe is
# optional. Upper snake case only, which no header cell matches.
_DOC_ROW_RE = re.compile(r'^\|?\s*([A-Z][A-Z0-9_]{2,})\s*\|([^|]*)\|', re.M)


def doc_descriptions(scenario_dir: Path) -> dict[str, str]:
    """name -> description from krkn-hub/docs/<scenario>.md, or {} if absent.
    Deterministic, so these never reach the model."""
    doc = Path(scenario_dir).parent / "docs" / f"{Path(scenario_dir).name}.md"
    if not doc.exists():
        return {}
    out = {}
    for name, text in _DOC_ROW_RE.findall(doc.read_text(encoding="utf-8-sig",
                                                        errors="replace")):
        text = " ".join(text.split())
        if text and name not in out:
            out[name] = text
    return out


def _resolve_references(records: dict) -> None:
    """Replace a default that is only a pointer at another variable.
    "$ALERTS_PATH" tells a reader nothing, so look up the sibling it names. No
    sibling means no default. Follows chains, since one pass would resolve them
    in declaration order."""
    def resolve(name, seen):
        rec = records.get(name)
        if rec is None or rec.default is None:
            return None
        m = _REF_RE.match(rec.default.strip())
        if not m:
            return rec.default
        if name in seen:            # A -> $B -> $A, no concrete value to find
            return None
        return resolve(m.group(1) or m.group(2), seen | {name})

    # Resolve every record before assigning any, so no lookup reads a value
    # that this pass has already rewritten.
    for name, default in {n: resolve(n, set()) for n in records}.items():
        records[name].default = default


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def extract_krknctl_params(path: Path) -> list[ParamRecord]:
    """Extract ParamRecords from a krknctl-input.json file.
    Each entry has two identifiers: "variable" is the env var that joins against
    env.sh, "name" is the CLI flag the page shows. Both travel on the record, so
    a caller can swap them rather than re-parse with a different key."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        return []
    records = []
    for item in data:
        if not isinstance(item, dict) or "variable" not in item:
            continue
        # "type": "Group" entries describe a group but configure nothing. They
        # carry no "variable" today; this holds if one ever gains one.
        if item.get("type") == "Group":
            continue
        raw_default = item.get("default")  # JSON null == no default
        default = str(raw_default) if raw_default is not None else None
        allowed = None
        if "allowed_values" in item:
            sep = item.get("separator", ",")
            allowed = [v.strip() for v in str(item["allowed_values"]).split(sep)]
        description = item.get("description") or item.get("short_description")
        records.append(ParamRecord(
            name=item["variable"],
            default=default,
            required=_as_bool(item.get("required", "false")),
            type=item.get("type"),
            description=description,
            description_source="krknctl" if description else None,
            allowed_values=allowed,
            group=item.get("group"),
            flag=item.get("name"),
            # The sources write the string "true", not a boolean.
            secret=_as_bool(item.get("secret", "false")),
        ))
    return records


# Baked into the container image at build time, not a scenario-local knob.
# IMAGE is not here: it's a real, user-configurable per-scenario param.




def build_skip_list(krkn_hub_root, krkn_root) -> dict[str, str | None]:
    """Global params and their defaults, for is_global().
    Tolerant of a missing source so tests can use small fixtures; CLI entry
    points call require_sources() first."""
    out: dict[str, str | None] = {}
    env = Path(krkn_hub_root) / "env.sh"
    if env.exists():
        out |= {r.name: r.default for r in extract_env_params(env)}
    ctl = Path(krkn_root) / "containers/krknctl-input.json"
    if ctl.exists():
        out |= {r.name: r.default for r in extract_krknctl_params(ctl)}
    return out


def is_global(record, skip) -> str | None:
    """Reason a per-scenario table must not repeat this param, or None when it
    belongs there. An override of the default is kept, never excluded."""
    # SCENARIO_TYPE and SCENARIO_FILE were excluded here as infra, they are
    # documented instead now. See krkn-chaos/docsync-bot#31.
    if record.name in skip and record.default == skip[record.name]:
        return f"same as the global default ({skip[record.name]!r})"
    return None


def require_sources(krkn_hub_root, krkn_root) -> None:
    """Fail loudly when a global parameter source is missing. A missing source
    shrinks the skip list to 3 names, leaking 79 global params into every
    per-scenario table."""
    for path, hint in ((Path(krkn_hub_root) / "env.sh", "KRKN_HUB_PATH"),
                       (Path(krkn_root) / "containers/krknctl-input.json", "KRKN_PATH")):
        if not path.exists():
            raise FileNotFoundError(
                f"Global parameter source not found: {path}. "
                f"Set {hint} to the repo root, or clone it in the workflow.")
