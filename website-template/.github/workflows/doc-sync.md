---
# Source workflow, compiled to doc-sync.lock.yml by `gh aw compile`.
# All deterministic work runs in the custom steps below, before the agent.
# The agent only commits the generated files and opens the pull request.

on:
  slash_command:
    name: [fix, resync]
  workflow_dispatch:
    inputs:
      scenarios:
        description: "Scenario name(s), space-separated (e.g. 'node-scenarios pod-scenarios')"
        required: false
  # TESTING: allow anyone to run /fix and /resync. Tighten to
  # [admin, maintainer, write] for production. The comment must still start
  # with "/fix <scenario>" or "/resync" as its first text.
  roles: all
  bots: [krkn-docs-bot]

permissions: read-all

engine:
  id: copilot
  model: gpt-4o-mini

steps:
  - name: Checkout website
    uses: actions/checkout@v7
    with:
      persist-credentials: false
  - name: Resolve scenarios
    id: scn
    env:
      DISPATCH_SCENARIOS: ${{ github.event.inputs.scenarios }}
      COMMENT_BODY: ${{ github.event.comment.body }}
      PR_NUMBER: ${{ github.event.issue.number }}
      REPO: ${{ github.repository }}
      GH_TOKEN: ${{ github.token }}
    run: |
      # A merged krkn-hub PR can touch several scenarios (space-separated dispatch
      # input); a /fix comment names exactly one; /resync derives them from the PR.
      if [ -n "$DISPATCH_SCENARIOS" ]; then
        scenarios="$DISPATCH_SCENARIOS"
      else
        scenarios="$(printf '%s' "$COMMENT_BODY" | awk 'NR==1{print $2}')"
        if [ -z "$scenarios" ] && [ -n "$PR_NUMBER" ]; then
          scenarios="$(gh api "repos/$REPO/pulls/$PR_NUMBER/files" --jq '.[].filename' 2>/dev/null \
            | grep -oE 'data/params/[a-z0-9-]+/' | cut -d/ -f3 | sort -u | tr '\n' ' ')"
        fi
      fi
      scenarios="$(echo $scenarios | tr -s ' ')"
      if [ -z "$scenarios" ]; then
        echo "no scenario given" >&2
        exit 1
      fi
      for s in $scenarios; do
        case "$s" in
          *[!a-z0-9-]*)
            echo "invalid scenario: '$s'" >&2
            exit 1 ;;
        esac
      done
      echo "scenarios=$scenarios" >> "$GITHUB_OUTPUT"
  - name: Install docs bot
    run: pip3 install "git+https://github.com/krkn-chaos/docsync-bot.git@main"
  - name: Clone the parameter sources
    run: |
      # krkn-hub holds the per-scenario params, krkn the global ones. Both are
      # needed even for a single scenario: the bot has to know which params are
      # global so it can leave them out of that scenario's table.
      git clone --depth 1 https://github.com/krkn-chaos/krkn-hub.git "$RUNNER_TEMP/krkn-hub"
      git clone --depth 1 https://github.com/krkn-chaos/krkn.git "$RUNNER_TEMP/krkn"
  - name: Generate parameter data and scaffold
    env:
      KRKN_HUB_PATH: ${{ runner.temp }}/krkn-hub
      KRKN_PATH: ${{ runner.temp }}/krkn
    run: |
      for scenario in ${{ steps.scn.outputs.scenarios }}; do
        echo "Generating: $scenario"
        # "globals" is not a krkn-hub directory. Those params come from
        # krkn-hub/env.sh and krkn/containers/krknctl-input.json, so they have
        # their own entry point rather than a scenario folder to read.
        if [ "$scenario" = "globals" ]; then
          python3 -m bot.globals --krkn-hub "$KRKN_HUB_PATH" --krkn "$KRKN_PATH"
        else
          python3 -m bot.doc_bot --scenario "$scenario" --scaffold
        fi
      done
  - name: Commit generated files to a branch
    env:
      SCENARIOS: ${{ steps.scn.outputs.scenarios }}
    run: |
      git config user.name "krkn-docs-bot"
      git config user.email "krkn-docs-bot@users.noreply.github.com"
      git checkout -b "docs-sync-${{ github.run_number }}"
      git add -A
      git commit -s -m "docs-sync: parameter tables for $SCENARIOS" || echo "no changes to commit"

network:
  allowed:
    - defaults
    - github

max-turns: 3
timeout-minutes: 15

safe-outputs:
  github-app:
    app-id: ${{ vars.APP_ID }}
    private-key: ${{ secrets.APP_PRIVATE_KEY }}
  create-pull-request:
    # Threat detection (a separate ~68k-token LLM scan) runs by default and is
    # kept ON for the mentor demo. To disable it for this workflow, add:
    #   threat-detection: false
    target-repo: "StrikerEureka34/website_2"
    draft: true
    title-prefix: "[docs-sync] "
    max: 1
  push-to-pull-request-branch:
    target-repo: "StrikerEureka34/website_2"
---

# Doc Sync

Earlier workflow steps already regenerated the changed krkn-chaos scenarios' parameter data files, injected the shortcode, and committed everything to the branch `docs-sync-${{ github.run_number }}`. Your only job is to open a single pull request for that branch. Do not run git or any other command.

The triggering command was `${{ needs.pre_activation.outputs.matched_command }}`.

Call exactly one safe-output tool:
- if the triggering command was `resync`, call `push_to_pull_request_branch` to update the existing pull request.
- otherwise call `create_pull_request` with `branch` set to `docs-sync-${{ github.run_number }}`, a short title, and a body noting that the parameter data files and shortcode were regenerated from krkn-hub.

You must call exactly one safe-output tool before finishing. Never read or log secrets.
