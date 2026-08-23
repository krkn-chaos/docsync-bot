# krkn-hub Trigger

Copy `.github/workflows/trigger-docs-sync.yml` into the krkn-hub repo's `.github/workflows/`.

When a scenario's `env.sh` or `krknctl-input.json` lands on `main`, it dispatches the website's doc-sync workflow for every changed scenario, so one source change produces one docs PR. The root `env.sh` dispatches `globals`, which regenerates the krkn-hub global parameter page. It authenticates with a short-lived GitHub App token, not a PAT.

It triggers on `push` rather than a merged `pull_request` because a pull request opened from a fork gets no repository secrets, so the app token step would fail on exactly the contributions that matter. A merge produces a push either way.

## Requires

- `DOC_SYNC_BOT_APP_ID` and `DOC_SYNC_BOT_APP_PRIVATE_KEY` as repository secrets on krkn-hub
- the app installed on `krkn-chaos/website`, with the doc-sync workflow present there
