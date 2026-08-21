# Website Workflows

Copy these into the website repo's `.github/workflows/`. They are the runtime half of the docs-sync bot ([#320](https://github.com/krkn-chaos/website/issues/320)).

&ensp;

## Files

**`doc-sync.md`**, the gh-aw agentic workflow source.

- Runs on a `/fix` comment, a `/resync` on a bot PR, or a dispatch from a source repo
- Generates the parameter data files, then requests a draft PR
- `/resync` regenerates on the PR's own branch and pushes a commit to it, so the patch is a fast-forward rather than a three-way merge onto the previous run's tables
- `gh aw compile` produces `doc-sync.lock.yml`, the file Actions actually runs. It is not committed here, but it **must** be committed in the website repo beside `doc-sync.md`: the prompt body is read from the `.md` at run time and the two are checked against each other, so they always ship together

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

## The model

Agent and describer both run on NVIDIA NIM, keyed by one secret.

| | Set in | Model |
| --- | --- | --- |
| Agent | `engine.env` | `openai/gpt-oss-20b`, a name the api-proxy allows while BYOK routes to NVIDIA |
| Describer | `Generate parameter data and scaffold` | `nvidia/nemotron-3.5-lightning-30b-a3b` |

- **The base URL is a literal in both places, never an expression.** `gh aw compile` reads it to allowlist the host; an expression and the firewall blocks every call
- BYOK sends the CLI no tool definitions, so the agent cannot call a safe-output tool. `Request the pull request` writes the item and the patch, and the prompt tells the agent to do nothing
- A run allows three model invocations. The agent uses one
- `threat-detection` is off: it reuses the engine, doubling calls against a rate-limited tier

&ensp;

## Onboarding

| Name | Kind |
| --- | --- |
| `DOC_SYNC_BOT_APP_ID` | repository variable |
| `DOC_SYNC_BOT_APP_PRIVATE_KEY` | secret |
| `DOC_SYNC_BOT_LLM_API_KEY` | secret |

- Both workflows use the App, so the rolling `docs-drift` issue has a stable author instead of `github-actions[bot]`
- Without the LLM key every model-written description comes out blank and the run stays green. The krkn-operator target never calls the model, so it is unaffected
- **Recompile with `gh aw compile` after editing `doc-sync.md`.** Only the workflow needs it: the bot installs from `@main` at run time
