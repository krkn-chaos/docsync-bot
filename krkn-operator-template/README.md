# krkn-operator Trigger

Copy `.github/workflows/trigger-docs-sync.yml` into the krkn-operator repo's `.github/workflows/`.

## What it does

- watches `config/crd/bases/**`, which owns the operator's API surface
- on a push to `main`, dispatches the website's doc-sync workflow with `scenarios=operator`
- that regenerates the api-reference tables for every kind
- authenticates with a short-lived GitHub App token, not a PAT

## Why it looks like this

- `push`, not `pull_request`: a PR from a fork gets no repository secrets, so the token step would fail on exactly the contributions that matter. A merge produces a push either way.
- one target for all nine kinds, unlike the per-scenario krkn-hub trigger: the CRDs sit in one directory and regenerating all of them costs nothing.

## Requires

- `APP_ID` and `APP_PRIVATE_KEY` as repository secrets on krkn-operator
- the app installed on `krkn-chaos/website`, with the doc-sync workflow present there

## Note

Field descriptions come from the Go doc comments in `api/v1alpha1` via `make manifests`. Fix them there, not on the generated page, which the next sync rewrites.
