# krkn Trigger

Copy `.github/workflows/trigger-docs-sync.yml` into the krkn repo's `.github/workflows/`.

krkn owns the global parameters, in `containers/krknctl-input.json`. When that file lands on `main`, this dispatches the website's doc-sync workflow with `scenarios=globals`, which regenerates the two global parameter pages. It authenticates with a short-lived GitHub App token, not a PAT.

It triggers on `push` rather than a merged `pull_request` because a pull request opened from a fork gets no repository secrets, so the app token step would fail on exactly the contributions that matter. A merge produces a push either way.

Separate from the krkn-hub trigger because the two sources have different shapes: krkn-hub has one directory per scenario, krkn has one file for every global.

## Requires

- `DOC_SYNC_BOT_APP_ID` and `DOC_SYNC_BOT_APP_PRIVATE_KEY` as repository secrets on krkn
- the app installed on `krkn-chaos/website`, with the doc-sync workflow present there
