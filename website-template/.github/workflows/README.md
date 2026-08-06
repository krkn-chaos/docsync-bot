# Website Workflows

Copy these into the website repo's `.github/workflows/`. They are the runtime half of the docs-sync bot ([#320](https://github.com/krkn-chaos/website/issues/320)).

## Files

- `doc-sync.md`: the gh-aw agentic workflow source. It runs the bot on a `/fix` comment or a dispatch from krkn-hub, generates the parameter data files, and opens a draft PR. Run `gh aw compile` to produce `doc-sync.lock.yml`, the file GitHub Actions actually runs. That lock is generated, so it is not committed here. It clones both parameter sources, krkn-hub and krkn, because a per-scenario table can only be built once the bot knows which params are global.
- `drift-report.yml`: a weekly report-only scan. It opens or updates one rolling `docs-drift` issue listing what has changed upstream, and opens no PRs. A plain workflow, not gh-aw: the report is derived from the sources with no judgement involved. Fixing is done by commenting `/fix <scenario>` on that issue, which drives `doc-sync.md`.
- `hugo-build.yml`: a render gate that fails a PR if any generated page or shortcode does not build.

## Change these for production

The source and bot install URLs already point at krkn-chaos. Still fork-specific:

- `roles: all` to `[admin, maintainer, write]`
- target repo `StrikerEureka34/website_2` to `krkn-chaos/website`
- recompile with `gh aw compile` after editing `doc-sync.md`

Both workflows need the GitHub App: `APP_ID` as a repository variable and `APP_PRIVATE_KEY` as a secret. `drift-report.yml` uses it so the rolling issue has a stable author instead of `github-actions[bot]`.
