# Upstream release update proposals

`Propose upstream release update` runs manually and daily. It asks GitHub for the
latest stable (not draft or prerelease) release of
`anxdpanic/plugin.video.youtube`, fetches that release's tag, and resolves the
peeled **commit** locally in an independent read-only job before candidate code
runs. It never uses a mutable branch name or a release's
`target_commitish` as the merge source.

For a release not already contained in `master`, the candidate job creates a
normal `--no-ff` merge on a release-specific branch name and runs
`python -m unittest discover -s tests -v`. The job has only `contents: read`,
checks out with `persist-credentials: false`, and is the only job that checks out
or tests the upstream merge candidate. The later write-capable job treats the
uploaded bundle as Git data, verifies its release SHA against the independent
job's output, verifies that its two parents are the unchanged `master` tip and
exact release commit, and independently reconstructs the merge tree to reject
forged contents with otherwise valid parents. It then pushes a new branch and opens a PR.
It does not run candidate code.

A release already reachable from `master` is a no-op. An open PR with the same
deterministic update branch is a no-op. A merge conflict aborts the candidate
merge and fails with an error stating that `master` was not changed. The workflow
never resets or force-pushes `master`, and it never auto-merges, creates a release,
or deploys.

GitHub does not necessarily start ordinary `pull_request` workflows for a PR
created with `GITHUB_TOKEN`. Therefore the candidate's read-only test result and
bundle are the automation's gating evidence; the separate `Fork tests` workflow
also supports `workflow_dispatch` for an explicit fork-side CI run. It runs on
PRs and pushes to `master` and does not claim that the upstream-only validation
workflow ran.

## Activation and permissions

Merge this workflow into the fork's default `master` branch only after review.
GitHub schedules run from the default branch; adding a workflow to a feature
branch does not activate the schedule. It runs daily at 04:23 UTC and can also
be dispatched manually after activation. A nightly check is release detection,
not automatic installation into Kodi or publication of a fork release.

The repository owner must allow Actions to create pull requests. GitHub labels
the setting **Allow GitHub Actions to create and approve pull requests**; it was
disabled when this change was prepared. This workflow never approves or merges
a PR. No new PAT or token is needed; job permissions are narrowly explicit and
the default workflow permissions can remain read-only. This change does not
modify repository settings or enable that permission on its own.

Normal merge conflicts, changed target heads and non-fast-forward branch
collisions fail safely and require review. API/network errors fail visibly,
rather than being mistaken for an up-to-date fork. Deterministic merge commit
metadata allows retrying a successful push followed by a failed PR creation
without force-pushing. Git 2.38+ (`merge-tree --write-tree`) is required, as
provided on the Ubuntu Actions runner.

The `Fork tests` pull-request workflow validates this automation's real Git
fixtures; after the companion profile feature is merged, the read-only
candidate tests also include its profile/playback regression tests.
