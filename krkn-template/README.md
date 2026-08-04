# krkn Trigger

Copy `.github/workflows/trigger-docs-sync.yml` into the krkn repo's `.github/workflows/`.

krkn owns the global parameters, in `containers/krknctl-input.json`. When a merged PR changes that file, this dispatches the website's doc-sync workflow with `scenarios=globals`, which regenerates the two global parameter pages. It authenticates with a short-lived GitHub App token, not a PAT.

Separate from the krkn-hub trigger because the two sources have different shapes: krkn-hub has one directory per scenario, krkn has one file for every global.

## Change these for production

- the target owner and repo `StrikerEureka34` / `website_2` to `krkn-chaos` / `website`
