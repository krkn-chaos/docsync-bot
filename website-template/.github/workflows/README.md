# Website Workflows

Copy these into the website repo's `.github/workflows/`. They are the runtime half of the docs-sync bot ([#320](https://github.com/krkn-chaos/website/issues/320)).

&ensp;

## Files

**`doc-sync.md`**, the gh-aw agentic workflow source.

- Runs on a `/fix` comment, a `/resync` on a bot PR, or a dispatch from a source repo
- Generates the parameter data files, then opens a draft PR
- `gh aw compile` produces `doc-sync.lock.yml`, the file Actions actually runs. That lock is generated, so it is not committed here

**`drift-report.yml`**, a weekly report-only scan.

- Opens or updates one rolling `docs-drift` issue, and opens no PRs
- A plain workflow rather than gh-aw: the report is derived from the sources with no judgement involved
- Fixing is done by commenting the `/fix` the issue names, which drives `doc-sync.md`

**`hugo-build.yml`**, a render gate that fails a PR if any generated page or shortcode does not build.

&ensp;

Both workflows clone all three sources:

- krkn-hub and krkn go together, because a per-scenario table can only be built once the global params are known
- krkn-operator supplies the CRDs behind the api-reference pages

&ensp;

## Targets

`doc-sync.md` routes one target per iteration:

| Target | Runs |
| --- | --- |
| a scenario id, e.g. `node-scenarios` | `bot.doc_bot` |
| `globals` | `bot.globals` |
| `operator` | `bot.operator`, all CRDs at once |

`/resync` derives them from the PR's changed files with `bot.targets`, not a grep, because a CRD plural is a group under `data/params/` but only `bot.operator` regenerates it.

&ensp;

## Change these for production

The source URLs, the bot install URL, the target repo and `roles` already point at production. What is left:

**Pick the describer endpoint.** `DOC_SYNC_BOT_LLM_BASE_URL`, `DOC_SYNC_BOT_LLM_API_KEY` and `DOC_SYNC_BOT_LLM_MODEL` on the generation step.

- Unset falls back to a built-in host measured unreachable from Actions, so every model-written description comes out blank while the run stays green
- The krkn-operator target is unaffected either way: it never calls the model

**Recompile with `gh aw compile` after editing `doc-sync.md`.** Only the workflow needs this. The bot installs from `@main` at run time, so a Python change ships without one.

&ensp;

Both workflows need the GitHub App: `DOC_SYNC_BOT_APP_ID` as a repository variable and `DOC_SYNC_BOT_APP_PRIVATE_KEY` as a secret. `drift-report.yml` uses it so the rolling issue has a stable author instead of `github-actions[bot]`.
