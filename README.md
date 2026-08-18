# docsync-bot

Automated documentation sync for krkn-chaos. It detects parameter changes in the upstream source repos and opens draft PRs on the [krkn-chaos website](https://github.com/krkn-chaos/website) that keep the scenario parameter tables current, without ever editing human-written markdown.

Project issue: [krkn-chaos/website#320](https://github.com/krkn-chaos/website/issues/320). Tracking: [#2](https://github.com/krkn-chaos/docsync-bot/issues/2).

## How it flows

1. A source changes: a scenario's config in krkn-hub (`env.sh` / `krknctl-input.json`), or a CRD in krkn-operator (`config/crd/bases`).
2. A trigger dispatches the sync workflow on the website repo.
3. The bot extracts parameters deterministically and writes `data/params/<group>/<table>.yaml`.
4. The `param-table` shortcode renders those data files, so human markdown stays untouched.
5. A draft PR opens for review, never auto-merged.

The two path segments are a group and a table within it, and what they mean depends on the source:

| Source | `<group>` | `<table>` |
| --- | --- | --- |
| krkn-hub | the scenario, e.g. `node-scenarios` | the source repo, `krkn-hub` or `krknctl` |
| krkn-hub + krkn globals | `globals` | the source repo, as above |
| krkn-operator | the CRD plural, e.g. `krknscenarioruns` | the section, `spec`, `status` or `columns` |

So an operator page calls `{{< param-table scenario="krknscenarioruns" source="spec" >}}`, and that file's `source_repo:` key holds the section name rather than a repo. The shortcode only resolves a path, so it needs no change per source.

## Layout

```
bot/                    # the Python package
  parser.py             # env.sh + krknctl-input.json parsers
  crd_parser.py         # CRD parser: spec, status and kubectl printcolumns
  descriptions.py       # description priority, five rungs (see below)
  describe.py           # the model rung: calls, validates and rejects
  emitter.py            # writes and reads data/params/<group>/<table>.yaml
  scaffold.py           # id-mapping, new-page creation, shortcode injection
  report.py             # commit-message sections for descriptions not taken from source
  doc_bot.py            # entrypoint, one scenario at a time
  globals.py            # entrypoint for the two global parameter pages
  operator.py           # entrypoint for the krkn-operator api-reference pages
  drift_scanner.py      # entrypoint, report-only: sources vs committed tables
  targets.py            # entrypoint: changed website paths -> the targets that regenerate them
  github_client.py      # opens and edits the rolling docs-drift issue
tests/                  # pytest, also holds the shortcode Hugo harness from the template PR (they coexist)
  fixtures/             # real env.sh and krknctl-input.json from krkn-hub scenarios
  fixtures/crd/         # real CRDs from krkn-operator, unmodified copies
website-template/       # the param-table and crd-ref shortcodes, and the doc-sync workflow (see its own README)
krkn-hub-template/      # trigger workflow for krkn-hub (see its own README)
krkn-template/          # trigger workflow for krkn (see its own README)
krkn-operator-template/ # trigger workflow for krkn-operator (see its own README)
```

Descriptions resolve in order: the source file, then the published table the
shortcode is about to replace, then the existing data file, then the other
source, then the model. Everything below the first rung is reported, so a cell
the bot could not fill from source is visible rather than silent.

Three entry points because the sources have three shapes:

| Entry point | Source shape | Takes |
| --- | --- | --- |
| `doc_bot` | one krkn-hub directory per scenario | a scenario name |
| `globals` | one file for every global, in `krkn-hub/env.sh` and `krkn/containers/krknctl-input.json`, with no scenario directory to read | the two repo roots |
| `operator` | one CRD file per kind, in `krkn-operator/config/crd/bases` | the operator repo root |

`operator` never calls the model: every CRD field carries its Go doc comment, so a
field with no description is a reported gap rather than something to invent. It
also writes `data/krkn_operator_crds.yaml`, an index of kind and short name that
the `crd-ref` shortcode resolves against, so a link to a renamed CRD fails the
site build instead of leaving a 404 for a reader to find.

The `tests/fixtures/` files are real `env.sh` and `krknctl-input.json` taken from krkn-hub scenarios, used as golden inputs so the parser is tested against the actual formats and their quirks (nested braces, malformed defaults, the full krknctl schema), not simplified toy data. `tests/fixtures/crd/` holds the nine krkn-operator CRDs the same way, in a subdirectory and under their own filenames, which are already unique, so each stays a byte-identical copy of the file it came from.

## Running

```
pip install -e .

# Both sources are required, even for one scenario: the bot builds a scenario
# table by leaving out the global params, and those come from krkn.
git clone --depth 1 https://github.com/krkn-chaos/krkn-hub.git
git clone --depth 1 https://github.com/krkn-chaos/krkn.git

KRKN_HUB_PATH=krkn-hub KRKN_PATH=krkn \
  python -m bot.doc_bot --scenario node-scenarios --scaffold

# The operator source needs only its own repo, and never calls the model.
git clone --depth 1 https://github.com/krkn-chaos/krkn-operator.git
python -m bot.operator --operator krkn-operator --website . --scaffold

pytest
```

The model rung needs one secret, `LLM_API_KEY`. The endpoint and model are built
in, so nothing else is configured in CI. Without the key the run still completes:
the affected cells stay empty and the report says the key was unset.

## Not yet wired (TODO)

- krkn `config.yaml` as a further source
- the `/refine` command

