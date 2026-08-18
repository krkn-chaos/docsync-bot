# Website Workflows

Copy these into the website repo's `.github/workflows/`. They are the runtime half of the docs-sync bot ([#320](https://github.com/krkn-chaos/website/issues/320)).

## Files

- `doc-sync.md`: the gh-aw agentic workflow source. It runs the bot on a `/fix` comment, a `/resync` on a bot PR, or a dispatch from a source repo, generates the parameter data files, and opens a draft PR. Run `gh aw compile` to produce `doc-sync.lock.yml`, the file GitHub Actions actually runs. That lock is generated, so it is not committed here.
- `drift-report.yml`: a weekly report-only scan. It opens or updates one rolling `docs-drift` issue and opens no PRs. A plain workflow, not gh-aw: the report is derived from the sources with no judgement involved. Fixing is done by commenting the `/fix` the issue names, which drives `doc-sync.md`.
- `hugo-build.yml`: a render gate that fails a PR if any generated page or shortcode does not build.

Both workflows clone all three sources. krkn-hub and krkn go together because a per-scenario table can only be built once the bot knows which params are global; krkn-operator supplies the CRDs behind the api-reference pages.

## Targets

`doc-sync.md` routes one target per iteration:

| Target | Runs |
| --- | --- |
| a scenario id, e.g. `node-scenarios` | `bot.doc_bot` |
| `globals` | `bot.globals` |
| `operator` | `bot.operator`, all CRDs at once |

`/resync` derives them from the PR's changed files with `bot.targets`, not a grep, because a CRD plural is a group under `data/params/` but only `bot.operator` regenerates it.

## Change these for production

The source URLs, the bot install URL, the target repo and `roles` already point at production. What is left:

- pick the describer endpoint: `LLM_BASE_URL`, `LLM_API_KEY` and `LLM_MODEL` on the generation step. Leaving them unset falls back to a built-in host measured unreachable from GitHub Actions, which leaves every generated description blank while the run stays green
- recompile with `gh aw compile` after editing `doc-sync.md`

Both workflows need the GitHub App: `APP_ID` as a repository variable and `APP_PRIVATE_KEY` as a secret. `drift-report.yml` uses it so the rolling issue has a stable author instead of `github-actions[bot]`.
