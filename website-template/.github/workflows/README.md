# Website Workflows

Copy these into the website repo's `.github/workflows/`. They are the runtime half of the docs-sync bot ([#320](https://github.com/krkn-chaos/website/issues/320)).

## Files

- `doc-sync.md`: the gh-aw agentic workflow source. It runs the bot on a `/fix` comment or a dispatch from krkn-hub, generates the parameter data files, and opens a draft PR. Run `gh aw compile` to produce `doc-sync.lock.yml`, the file GitHub Actions actually runs. That lock is generated, so it is not committed here. It clones both parameter sources, krkn-hub and krkn, because a per-scenario table can only be built once the bot knows which params are global.
- `hugo-build.yml`: a render gate that fails a PR if any generated page or shortcode does not build.

## Change these for production

The source and bot install URLs already point at krkn-chaos. Still fork-specific:

- `roles: all` to `[admin, maintainer, write]`
- target repo `StrikerEureka34/website_2` to `krkn-chaos/website`
- recompile with `gh aw compile` after editing `doc-sync.md`
