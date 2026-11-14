# Releasing CFE BMS

This is the authoritative release procedure for the Home Assistant App and
its prebuilt Docker images. Publish a release only when the user explicitly
requests it. A release is complete only after GitHub Actions and Docker Hub
publication have both been verified.

## Release rules

- Use `vX.Y.Z` version strings, including the leading `v`.
- `config.yaml` is authoritative for the Home Assistant App version. The Git
  tag and Docker Hub tag must match it exactly.
- Keep `image: "andrevza/cfebms"` untagged. Supervisor selects the versioned
  image tag from the App version.
- Publish only the `vX.Y.Z` image tag. Do not publish `latest` or an unprefixed
  version tag.
- Do not bump the Python package version in `pyproject.toml` or
  `src/cfebms/__init__.py` unless explicitly requested.
- Ordinary development does not bump the App version, update the changelog, or
  publish an image. Do not create release tags during ordinary development.
- Do not stage or alter the untracked `reference/` directory. Never use
  `git add .` or `git add -A` for a release.
- There is no `Unreleased` changelog section. Write release notes at release
  time from actual commits, code changes and other intended work. Use the
  actual release date, omit empty categories, and preserve all prior entries.
- Never force-push, rewrite published history, overwrite a tag, manually push
  replacement images, or deploy to a live Home Assistant installation as part
  of a release.

## Prepare a release

Set the target version explicitly in the shell, using the requested release
version:

```sh
RELEASE_VERSION=vX.Y.Z
```

Inspect the repository and remote before editing or publishing:

```sh
git status --short
git branch --show-current
git log -10 --oneline --decorate
git fetch origin --tags
git tag --list
git ls-remote --heads origin main
git ls-remote --tags origin "refs/tags/$RELEASE_VERSION"
```

Identify the previous published release tag, then review both committed and
uncommitted changes since it:

```sh
PREVIOUS_VERSION=$(git describe --tags --abbrev=0)
git log --oneline "$PREVIOUS_VERSION..HEAD"
git diff "$PREVIOUS_VERSION..HEAD"
git diff
git diff --cached
```

Confirm the target tag does not already exist locally or remotely. If it
exists, stop; never move or overwrite it. Confirm the prior tag, target version,
and included changes are correct. Keep unrelated files and `reference/`
untouched.

Update `config.yaml` to `version: "$RELEASE_VERSION"`, preserving the
untagged `image: "andrevza/cfebms"` and the existing options, schema,
privileges and startup behavior. Do not change the Python package version.

Create a changelog entry named `## $RELEASE_VERSION — YYYY-MM-DD` with the
actual local release date. Review the source diff and commits since the previous
tag; include only substantiated user, operator or maintainer changes. Remove
any `Unreleased` section. Preserve all previous release history.

Update version examples intended to describe the current release in `README.md`
and `DOCS.md`, plus version-sensitive tests. Preserve historical release
references. Ensure tests cover the manifest version, image repository,
matching changelog entry, previous history, absence of an `Unreleased` section,
and existing App configuration and telemetry behavior. Do not alter MQTT
discovery topics or entity identifiers for release housekeeping.

## Validate and review

Run development and release checks in Docker:

```sh
docker compose run --build --rm test
docker compose build cfebms
git diff --check
git status --short
git diff
```

Where available, build checks for `linux/amd64` and `linux/arm64` as well. The
GitHub Actions workflow performs the release platform builds. Distinguish
local build results from remote platform verification. Do not publish if
required checks fail, and do not weaken tests to hide a failure.

Review every intended release file. Stage paths explicitly, excluding
`reference/`, credentials, generated artifacts and unrelated local changes.
Then inspect the staged result:

```sh
git add path/to/intended-file ...
git diff --cached --check
git diff --cached
git status --short
```

Verify that `reference/` is not staged and that no secret or unrelated data is
included.

## Commit and publish to GitHub

Use the release commit message `Release vX.Y.Z` (with the actual target
version). Follow the repository's branch protection and PR requirements. The
verified release commit must be on remote `main` before tagging it. Do not
bypass permissions or publish unrelated branches.

For a direct-to-main workflow, ensure the branch is current before committing:

```sh
git switch main
git pull --ff-only origin main
git commit -m "Release $RELEASE_VERSION"
git push origin main
```

If the repository requires a branch and PR, commit the release change on that
branch, push it, and merge it through the normal review process instead. Once
the release commit is on `main`, refresh local `main` and verify it is the
remote head:

```sh
git switch main
git pull --ff-only origin main
git status --short
git log -1 --oneline
RELEASE_COMMIT=$(git rev-parse HEAD)
REMOTE_MAIN=$(git ls-remote --heads origin main | awk '{print $1}') || exit 1
test "$RELEASE_COMMIT" = "$REMOTE_MAIN" || { echo "Release commit is not remote main"; exit 1; }
```

Before creating the tag, require both tag checks below to show that it does not
exist. Record the release commit SHA and confirm that it is the intended commit
on `main`. Create an annotated tag on that commit and push only the tag:

```sh
if git show-ref --quiet "refs/tags/$RELEASE_VERSION"; then
  echo "Local tag already exists; stop"
  exit 1
fi
REMOTE_TAG=$(git ls-remote --tags origin "refs/tags/$RELEASE_VERSION") || exit 1
if [ -n "$REMOTE_TAG" ]; then
  echo "Remote tag already exists; stop"
  exit 1
fi
git tag -a "$RELEASE_VERSION" -m "Release $RELEASE_VERSION" "$RELEASE_COMMIT"
git push origin "$RELEASE_VERSION"
git ls-remote --tags origin "refs/tags/$RELEASE_VERSION" "refs/tags/$RELEASE_VERSION^{}"
```

The pushed tag must point to the same commit as remote `main`. Do not force-push
or push a tag that already exists.

## GitHub Actions and Docker Hub

`.github/workflows/docker.yml` is the release publisher. A pushed `v*` tag
starts the workflow. It checks that the tag matches `config.yaml`, runs
`docker compose run --build --rm test`, builds digest-addressed images for
`linux/amd64` and `linux/arm64`, combines them into a multi-platform manifest,
and publishes only the matching versioned tag to `andrevza/cfebms`. It uses
the Home Assistant Python base image, preserves the `/init` runtime and
`/run.sh service` startup, and supplies the Home Assistant architecture values:

| Docker platform | `io.hass.arch` |
| --- | --- |
| `linux/amd64` | `amd64` |
| `linux/arm64` | `aarch64` |

The workflow needs the repository Actions variable `DOCKERHUB_USERNAME` and
secret `DOCKERHUB_TOKEN`. Confirm they are configured without displaying or
copying secret values. Do not manually push an image; let the existing workflow
publish it.

After pushing the tag, inspect its GitHub Actions run. Confirm version
validation and tests passed, both platform builds succeeded, the manifest was
assembled, and Docker Hub publication completed. A successful Git push alone
does not mean the release was published.

Verify the registry tag and platform manifest:

```sh
docker buildx imagetools inspect "andrevza/cfebms:$RELEASE_VERSION"
docker buildx imagetools inspect --raw "andrevza/cfebms:$RELEASE_VERSION"
```

Confirm both Linux architectures are present. Pull each platform and inspect
its labels, substituting the target version:

```sh
docker pull --platform linux/amd64 "andrevza/cfebms:$RELEASE_VERSION"
docker image inspect --format '{{json .Config.Labels}}' "andrevza/cfebms:$RELEASE_VERSION"
docker pull --platform linux/arm64 "andrevza/cfebms:$RELEASE_VERSION"
docker image inspect --format '{{json .Config.Labels}}' "andrevza/cfebms:$RELEASE_VERSION"
```

Verify `org.opencontainers.image.version`,
`org.opencontainers.image.revision`, and `org.opencontainers.image.created`,
plus the matching `io.hass.version` and `io.hass.arch`. The embedded revision
must equal the tagged release commit; the architecture labels must be `amd64`
and `aarch64` respectively. Confirm the runtime entrypoint and `/run.sh`
service command remain present. If an architecture cannot be tested locally,
record that and rely on the successful GitHub Actions build plus registry
manifest inspection for that platform.

If the workflow fails for a transient reason, diagnose it and rerun the same
workflow when safe. If a code or release-file change is needed after a tag has
been published, do not move the tag or replace its image. Prepare a new version
and release. Report any partial publication clearly; call the release complete
only after the Actions run and registry image are verified.

## Home Assistant update

Do not change or restart a live Home Assistant installation automatically.
After publication is verified, tell the operator to refresh the App repository
and update CFE BMS to the released version. Preserve existing App configuration
and MQTT discovery identifiers. The operator should confirm Supervisor pulled
the prebuilt image, then check startup logs for the App version and full Git
revision, MQTT connection, battery TCP connection, fresh CFE telemetry, and
continued availability of expected entities.
