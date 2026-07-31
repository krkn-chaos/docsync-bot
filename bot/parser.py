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


EXPORT_LINE_RE = re.compile(r'^\s*export\s+([A-Za-z_][A-Za-z0-9_]*)=(.*)$')
VAR_NAME_RE = re.compile(r'[A-Za-z_][A-Za-z0-9_]*')

# Backtick-wrapped uppercase identifiers in markdown tables
GLOBAL_PARAM_RE = re.compile(r'`([A-Z][A-Z0-9_]+)`')


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
        # export VAR=${VAR} -- declared but no default: required
        default, required = None, True
    elif body.startswith((":=", ":-")):
        default, required = _strip_quotes(body[2:]), False
    elif body.startswith(":"):
        # Malformed-but-intentional default, e.g. ${VAR:""} or ${VAR:False}
        default, required = _strip_quotes(body[1:]), False
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
    return list(records.values())


def _as_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() == "true"


def extract_krknctl_params(path: Path, key: str = "variable") -> list[ParamRecord]:
    """Extract ParamRecords from a krknctl-input.json file
    (description, type, required, allowed_values, group).

    key picks which JSON field becomes ParamRecord.name. "variable" is the env
    var, which every caller joins on. "name" is the CLI flag, which is what the
    krknctl page shows the reader."""
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, list):
        return []
    records = []
    for item in data:
        if not isinstance(item, dict) or key not in item:
            continue
        # "type": "Group" entries name and describe a group but configure
        # nothing. They have no "variable", so they only show up under "name".
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
            name=item[key],
            default=default,
            required=_as_bool(item.get("required", "false")),
            type=item.get("type"),
            description=description,
            description_source="krknctl" if description else None,
            allowed_values=allowed,
            group=item.get("group"),
        ))
    return records


def build_skip_list(all_scenario_env_path: Path) -> set[str]:
    """Extract global params shared across all scenarios from all-scenario-env.md."""
    text = all_scenario_env_path.read_text()
    found = set(GLOBAL_PARAM_RE.findall(text))
    found |= {"SCENARIO_TYPE", "SCENARIO_FILE", "IMAGE"}
    return found
