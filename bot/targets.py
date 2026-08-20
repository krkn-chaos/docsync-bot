"""Website paths a pull request changed -> the targets that regenerate them.

In the package rather than the workflow's shell because /resync cannot be run on a
fork, so this has to be right by construction."""
import argparse
import sys
from pathlib import Path

import yaml

from bot.operator import PAGES_ROOT, SECTION, _PAGE_LINKS

# The bot generates this index, so its keys are exactly the operator groups.
CRD_INDEX = "data/krkn_operator_crds.yaml"
OPERATOR = "operator"
_OPERATOR_PAGES = f"{SECTION}/"
# The six pages link_pages appends a crd-ref to. Derived, not the whole tree:
# that would route prose edits to the operator too.
_LINKED_PAGES = frozenset(f"{PAGES_ROOT}/{rel}" for rel in _PAGE_LINKS)


def operator_groups(website_root) -> set:
    """Plurals the operator source owns. Empty without the index, so a path then
    resolves to itself rather than to a wrong target."""
    path = Path(website_root) / CRD_INDEX
    if not path.exists():
        return set()
    return set(yaml.safe_load(path.read_text(encoding="utf-8")) or {})


def resolve(changed_files, crd_plurals=()) -> list:
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
        parts = name.split("/")
        if len(parts) > 3 and parts[:2] == ["data", "params"]:
            out.add(OPERATOR if parts[2] in plurals else parts[2])
    return sorted(out)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Resolve changed website paths, read on stdin, to doc-sync targets")
    ap.add_argument("--website", default=".", help="Path to the website repo root")
    args = ap.parse_args()
    print(" ".join(resolve(sys.stdin, operator_groups(args.website))))


if __name__ == "__main__":
    main()
