import os
import shutil
import subprocess
import sys
from pathlib import Path
from shutil import which

import pytest

# Bot unit tests: make the `bot` package importable and set placeholder env.
sys.path.insert(0, str(Path(__file__).parent.parent))
os.environ.setdefault("OPENROUTER_API_KEY", "test-key-for-tests")
os.environ.setdefault("GITHUB_TOKEN", "test-token-for-tests")


@pytest.fixture(autouse=True)
def _no_live_model_calls(monkeypatch):
    """The base URL and model are built in, so a developer with LLM_API_KEY
    exported would otherwise have the suite call the real endpoint."""
    monkeypatch.delenv("LLM_API_KEY", raising=False)


# Shortcode Hugo build harness (used only by the shortcode tests). hugo is looked
# up lazily at build time so the bot tests can run without hugo or npm installed.
REPO = Path(__file__).resolve().parents[1]                       # docsync-bot
SHORTCODES = REPO / "website-template" / "layouts" / "shortcodes"


def find_hugo() -> str:
    """Locate a hugo extended binary, preferring the real executable over npm shims."""
    found = which("hugo")
    if found:
        return found
    search_roots = [REPO, REPO.parent / "krkn_Sync" / "website"]
    # The hugo-extended npm package ships the real binary under vendor/.
    for root in search_roots:
        for name in ("hugo.exe", "hugo"):
            cand = root / "node_modules" / "hugo-extended" / "vendor" / name
            if cand.exists():
                return str(cand)
    # Fallback to the .bin shim (works on POSIX; on Windows prefer the vendor exe above).
    for root in search_roots:
        for name in ("hugo.exe", "hugo"):
            cand = root / "node_modules" / ".bin" / name
            if cand.exists():
                return str(cand)
    raise RuntimeError(
        "hugo not found. Run `npm install` in docsync-bot (provides hugo-extended)."
    )


HUGO_CONFIG = """\
baseURL: {base_url}
title: param-table harness
disableKinds: [taxonomy, term, sitemap, robotsTXT, rss]
markup:
  goldmark:
    renderer:
      unsafe: true
"""

SINGLE = "{{ .Content }}"


class Site:
    """A throwaway minimal Hugo site for testing the param-table shortcode in isolation."""

    def __init__(self, root: Path, base_url: str = "http://example.org/"):
        self.root = root
        (root / "layouts" / "shortcodes").mkdir(parents=True)
        (root / "layouts" / "_default").mkdir(parents=True)
        (root / "content").mkdir(parents=True)
        (root / "data").mkdir(parents=True)
        (root / "hugo.yaml").write_text(
            HUGO_CONFIG.format(base_url=base_url), encoding="utf-8")
        (root / "layouts" / "_default" / "single.html").write_text(SINGLE, encoding="utf-8")
        (root / "layouts" / "index.html").write_text(SINGLE, encoding="utf-8")
        # All of them, so a shortcode calling another still resolves.
        for sc in SHORTCODES.glob("*.html"):
            shutil.copy(sc, root / "layouts" / "shortcodes" / sc.name)

    def data(self, scenario: str, source: str, yaml_text: str):
        d = self.root / "data" / "params" / scenario
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{source}.yaml").write_text(yaml_text, encoding="utf-8")

    def page(self, slug: str, scenario: str, source: str, **attrs) -> str:
        """attrs become extra shortcode arguments, e.g. group="cerberus"."""
        extra = "".join(f' {k}="{v}"' for k, v in attrs.items())
        body = (
            "---\n"
            f"title: {slug}\n"
            "---\n\n"
            f'{{{{< param-table scenario="{scenario}" source="{source}"{extra} >}}}}\n'
        )
        (self.root / "content" / f"{slug}.md").write_text(body, encoding="utf-8")
        return f"{slug}/index.html"

    def build(self) -> subprocess.CompletedProcess:
        return subprocess.run(
            [find_hugo(), "--logLevel", "warn", "--destination", str(self.root / "public")],
            cwd=self.root, capture_output=True, text=True,
        )

    def html(self, rel: str) -> str:
        return (self.root / "public" / rel).read_text(encoding="utf-8")


@pytest.fixture
def site(tmp_path):
    return Site(tmp_path)
