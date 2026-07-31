# docsync-bot

Automated documentation sync for krkn-chaos. It detects parameter changes in the upstream source repos and opens draft PRs on the [krkn-chaos website](https://github.com/krkn-chaos/website) that keep the scenario parameter tables current, without ever editing human-written markdown.

Project issue: [krkn-chaos/website#320](https://github.com/krkn-chaos/website/issues/320). Tracking: [#2](https://github.com/krkn-chaos/docsync-bot/issues/2).

## How it flows

1. A scenario's config changes in krkn-hub (`env.sh` / `krknctl-input.json`).
2. A trigger dispatches the sync workflow on the website repo.
3. The bot extracts parameters deterministically and writes `data/params/<scenario>/<source>.yaml`.
4. The `param-table` shortcode renders those data files, so human markdown stays untouched.
5. A draft PR opens for review, never auto-merged.

## Layout

```
bot/                # the Python package
  parser.py         # env.sh + krknctl-input.json parsers
  descriptions.py   # description priority (source > existing file > LLM)
  emitter.py        # writes and reads data/params/<scenario>/<source>.yaml
  scaffold.py       # id-mapping, new-page creation, shortcode injection
  doc_bot.py        # entrypoint
tests/              # pytest, also holds the shortcode Hugo harness from the template PR (they coexist)
  fixtures/         # real env.sh and krknctl-input.json from krkn-hub scenarios
website-template/   # the param-table shortcode (see its own README)
```

The `tests/fixtures/` files are real `env.sh` and `krknctl-input.json` taken from krkn-hub scenarios, used as golden inputs so the parser is tested against the actual formats and their quirks (nested braces, malformed defaults, the full krknctl schema), not simplified toy data.

## Running

```
pip install -e .
python -m bot.doc_bot --scenario node-scenarios --scaffold
pytest
```

## Not yet wired (TODO)

- krkn `config.yaml` as a third source
- drift scan on a schedule
- the `/refine` and `/resync` commands

