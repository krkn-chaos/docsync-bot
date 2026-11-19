"""Website paths a pull request changed -> the targets that regenerate them.

In the package rather than the workflow's shell because /resync cannot be run on a
fork, so this has to be right by construction."""
import argparse
import re
import sys
from pathlib import Path

import yaml

from bot.globals import GLOBAL_SCENARIO, _PAGES as _GLOBAL_PAGE_TUPLES
from bot.operator import PAGES_ROOT, SECTION, _PAGE_LINKS

# The bot generates this index, so its keys are exactly the operator groups.
CRD_INDEX = "data/krkn_operator_crds.yaml"
OPERATOR = "operator"
_OPERATOR_PAGES = f"{SECTION}/"
# The six pages link_pages appends a crd-ref to. Derived, not the whole tree:
# that would route prose edits to the operator too.
_LINKED_PAGES = frozenset(f"{PAGES_ROOT}/{rel}" for rel in _PAGE_LINKS)
# The two global pages where group-filtered shortcodes live.
_GLOBAL_PAGES = frozenset(rel for _, rel in _GLOBAL_PAGE_TUPLES)
_SCENARIO_ROOT = "content/en/docs/scenarios/"
_MARKER_RE = re.compile(r'<krkn-hub-scenario\s+id="([^"]+)"')


def operator_groups(website_root) -> set:
    """Plurals the operator source owns. Empty without the index, so a path then
    resolves to itself rather than to a wrong target."""
    path = Path(website_root) / CRD_INDEX
    if not path.exists():
        return set()
    return set(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def resolve(changed_files, crd_plurals=(), website_root=None) -> list:
    """Sorted, deduplicated targets. `globals` needs no special case: it is the
    group name the emitter already writes under."""
    plurals, out = set(crd_plurals), set()
    for raw in changed_files:
        name = raw.strip().replace("\\", "/")
        if not name:
            continue
        if (name == CRD_INDEX or name in _LINKED_PAGES
                or name.startswith(_OPERATOR_PAGES)):
            out.add(OPERATOR)
            continue
        if name in _GLOBAL_PAGES:
            out.add(GLOBAL_SCENARIO)
            continue
        parts = name.split("/")
        if len(parts) > 3 and parts[:2] == ["data", "params"]:
            out.add(OPERATOR if parts[2] in plurals else parts[2])
            continue
        # Scenario tab files. Page directories can diverge from scenario names
        # (e.g. pod-network-scenario maps to pod-network-chaos), so the declared
        # marker in the companion _index.md takes precedence.
        if name.startswith(_SCENARIO_ROOT) and parts[-1].startswith("_tab-") and len(parts) > 5:
            scenario_id = None
            if website_root:
                index_path = Path(website_root) / "/".join(parts[:-1]) / "_index.md"
                if index_path.exists():
                    m = _MARKER_RE.search(index_path.read_text(encoding="utf-8", errors="replace"))
                    if m:
                        scenario_id = m.group(1)
            out.add(scenario_id or parts[-2])
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Resolve changed website paths, read on stdin, to doc-sync targets")
    ap.add_argument("--website", default=".", help="Path to the website repo root")
    args = ap.parse_args()
    print(" ".join(resolve(sys.stdin, operator_groups(args.website), website_root=args.website)))


if __name__ == "__main__":
    main()
