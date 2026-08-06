# krkn-hub Trigger

Copy `.github/workflows/trigger-docs-sync.yml` into the krkn-hub repo's `.github/workflows/`.

When a scenario's `env.sh` or `krknctl-input.json` lands on `main`, it dispatches the website's doc-sync workflow for every changed scenario, so one source change produces one docs PR. The root `env.sh` dispatches `globals`, which regenerates the krkn-hub global parameter page. It authenticates with a short-lived GitHub App token, not a PAT.

It triggers on `push` rather than a merged `pull_request` because a pull request opened from a fork gets no repository secrets, so the app token step would fail on exactly the contributions that matter. A merge produces a push either way.

## Change these for production

- the target owner and repo `StrikerEureka34` / `website_2` to `krkn-chaos` / `website`
