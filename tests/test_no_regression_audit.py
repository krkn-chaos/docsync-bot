"""Every published cell that has text today still has text after regeneration.

The other tests use fixtures. This runs the real corpus against the real pages,
which is the only way to know the fallback chain fires where it should.
"""
import io
import os
import subprocess
import tarfile
import tempfile
from pathlib import Path

import pytest
import yaml

from bot import globals as g
from bot.doc_bot import run
from bot.scaffold import find_tab, published_cell, published_table

_SYNC = Path(__file__).resolve().parents[3]
WEBSITE = Path(os.environ.get("WEBSITE_REPO", _SYNC / "website"))
HUB = Path(os.environ.get("KRKN_HUB_PATH", _SYNC / "krkn-hub"))
KRKN = Path(os.environ.get("KRKN_PATH", _SYNC / "krkn"))
# A ref that still holds hand-written tables; local main may already be converted.
REF = os.environ.get("PUBLISHED_REF", "upstream/main")

REQUIRED = (HUB / "node-scenarios" / "env.sh",
            KRKN / "containers" / "krknctl-input.json",
            WEBSITE / ".git")

pytestmark = pytest.mark.skipif(
    not all(p.exists() for p in REQUIRED),
    reason="needs local krkn-hub, krkn and website checkouts")


@pytest.fixture(scope="module")
def seeded():
    """A website root holding the hand-written pages. Without this the published
    rung never fires and every assertion here fails against correct code."""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        raw = subprocess.run(["git", "archive", REF, "content/en/docs/scenarios"],
                             cwd=WEBSITE, capture_output=True, check=True).stdout
        with tarfile.open(fileobj=io.BytesIO(raw)) as tf:
            if hasattr(tarfile, "data_filter"):
                tf.extractall(root, filter="data")
            else:
                tf.extractall(root)
        assert list(root.rglob("_tab-krkn-hub.md")), f"{REF}: no tabs extracted"
        yield root


def _generated(root, scenario, source):
    """Keyed the way the published page keys rows: the krknctl page lists flags."""
    f = root / "data/params" / scenario / f"{source}.yaml"
    if not f.exists():
        return {}
    rows = yaml.safe_load(f.read_text(encoding="utf-8"))["params"]
    return {r.get("flag") or r["name"]: r for r in rows}


# Use-case pages carry a real scenario's marker, so the bot refuses to guess
# which page to convert. Tracked as krkn-chaos/website#566.
AMBIGUOUS = {"node-network-filter", "pod-network-filter", "pod-network-chaos"}


@pytest.mark.parametrize("source", ["krkn-hub", "krknctl"])
def test_no_published_description_or_type_goes_blank(source, seeded):
    checked, lost, ambiguous = 0, [], []
    for scenario in sorted(p.parent.name for p in HUB.glob("*/env.sh")):
        try:
            tab = find_tab(seeded, scenario, source)
        except ValueError:
            ambiguous.append(scenario)
            continue
        if tab is None:
            continue
        rows = published_table(tab.read_text(encoding="utf-8"))
        if not rows:
            continue
        run(scenario, HUB, seeded, KRKN)
        gen = _generated(seeded, scenario, source)
        for name in rows:
            rec = gen.get(name)
            if rec is None:      # gone from the source: dropping it is the job
                continue
            checked += 1
            for col in ("description", "type"):
                if published_cell(rows, name, col) and not rec.get(col):
                    lost.append(f"{scenario}/{name}: {col}")
    assert checked > 100, f"only {checked} rows compared, the corpus did not load"
    assert lost == []
    # Shrinks as website#566 is fixed. A new name here is a new duplicate marker.
    assert set(ambiguous) <= AMBIGUOUS, f"new ambiguous markers: {set(ambiguous) - AMBIGUOUS}"


def test_no_published_global_description_goes_blank(seeded):
    """The two global pages carry nine tables each and nobody audits them.
    SIGNAL_STATE and RESILIENCY_RUN_MODE are what this catches."""
    g.emit(seeded, HUB, KRKN)
    lost = []
    for source, rel in g._PAGES:
        rows = published_table((seeded / rel).read_text(encoding="utf-8"))
        assert len(rows) > 40, f"{rel}: fixture did not load"
        gen = {r["name"]: r for r in yaml.safe_load(
            (seeded / "data/params/globals" / f"{source}.yaml")
            .read_text(encoding="utf-8"))["params"]}
        for name in rows:
            if (name in gen and published_cell(rows, name, "description")
                    and not gen[name].get("description")):
                lost.append(f"globals/{source}/{name}")
    assert lost == []
