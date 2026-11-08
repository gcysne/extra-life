# Releasing Extra Life

How versions, branches and releases work. Maintainer steps first, then the plan for the alpha, beta and 1.0 phases.

## Rules

- **`main` is the only permanent branch** (and the default). The maintainer pushes to it directly; everyone else
  sends pull requests (see [CONTRIBUTING.md](CONTRIBUTING.md)).
- **A release is an annotated tag** `v<version>` on a commit of `main`. CI builds the release from the tag.
- **Never move, delete or re-use a published tag.** Installed copies only offer an update when the version number
  goes up: a release fixed under the same number never reaches the people who already have it. A broken release is
  fixed by the next version.
- Versions follow [semver](https://semver.org): `MAJOR.MINOR.PATCH[-pre]`, ordered
  `0.2.0-alpha < 0.2.0-alpha.2 < 0.2.0-beta.1 < 0.2.0`.

## Making a release

1. On `main`, set the version in `extralife/__init__.py` and `decky-plugin/package.json` (they must match; the build checks).
2. In `CHANGELOG.md`, rename `## Unreleased` to `## <version> (<date>)` (it becomes the release notes) and start a
   new empty `## Unreleased` above it when work continues.
3. Commit (`release: <version>`), push, wait for CI to pass.
4. `git tag -a v<version> -m "Extra Life <version>" && git push origin v<version>`.
5. `.github/workflows/release.yml` runs the tests and publishes `extra-life.tar.gz` (with the prebuilt
   plugin), `get-release.sh` and `SHA256SUMS` as the **latest** release (`scripts/make-release.sh`).
6. Check the release page and its files, then install it on a real device the way users do
   (the `get-release.sh` one-liner from the README) and check the update notice in the plugin's About tab.

## Phases

### Alpha (now): `0.x.y-alpha`

Features still change; things may break. Everything happens on `main`.

| Release | For | Example |
|---|---|---|
| `0.1.1-alpha` | fixes only | a bug reported in an issue |
| `0.2.0-alpha` | new features | a new storage provider or emulator profiles |
| `0.2.1-alpha` | fixes for 0.2 | |

### Beta: `1.0.0-beta.N`

Feature-complete for 1.0. **Feature freeze on `main`**: only fixes are merged; feature pull requests wait (label
`after-1.0`). Each round of fixes is `1.0.0-beta.2`, `1.0.0-beta.3`...

Exception: if a feature must land while the beta still has a while to go, create `release/1.0` from the latest
beta tag. Fixes go to `main` first, then `git cherry-pick -x` to `release/1.0`; betas and `v1.0.0` are tagged on the
branch while `main` moves on to 1.1.

### 1.0 and later: `MAJOR.MINOR.PATCH`

- `v1.0.0` is tagged on `main` (or on `release/1.0` if one exists).
- Fixes are `1.0.1`, `1.0.2`... from `main`, as long as `main` holds nothing unreleased.
- **Maintenance branch only when needed**: when `main` already has unreleased 1.1 work and 1.0 needs a fix, create
  `release/1.0` from `v1.0.0`, land the fix on `main` first, cherry-pick it to `release/1.0` and tag `v1.0.1`
  there. Delete the branch when 1.0 is no longer supported.
- When the first `release/*` branch is created, add `refs/heads/release/**` to `.github/rulesets/main.json`
  (run `.github/rulesets/apply.sh`) and to the CI workflow's branches in the same commit, so it is protected and
  built like `main`.

## Pre-releases and update checks

The update check (`extralife/update.py`, shown in the plugin's About tab) and `get-release.sh` use GitHub's
`releases/latest`, which ignores pre-releases. So **every release, alpha and beta included, is published as
latest, never as a pre-release**; otherwise nobody would be offered it.

From 1.0: someone on a stable version should only be offered stable releases, someone on an alpha or beta
everything newer. Before the first `1.x` beta, switch the check to the release list (like Sidequest's) and let
`get-release.sh` take a channel.
