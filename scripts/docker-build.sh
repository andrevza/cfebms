#!/bin/sh
set -eu

repo_root=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)

if git -C "$repo_root" rev-parse --verify HEAD >/dev/null 2>&1; then
    BUILD_GIT_SHA=$(git -C "$repo_root" rev-parse HEAD)
    if git -C "$repo_root" status --porcelain --untracked-files=all -- . ':!reference/' >/dev/null 2>&1; then
        if [ -n "$(git -C "$repo_root" status --porcelain --untracked-files=all -- . ':!reference/')" ]; then
            BUILD_SOURCE_STATE=dirty
        else
            BUILD_SOURCE_STATE=clean
        fi
    else
        BUILD_SOURCE_STATE=unknown
    fi
else
    BUILD_GIT_SHA=unknown
    BUILD_SOURCE_STATE=unknown
fi

BUILD_VERSION=$(awk -F: '/^version:/ { gsub(/["[:space:]]/, "", $2); print $2; exit }' "$repo_root/config.yaml")
BUILD_TIMESTAMP=$(date -u '+%Y-%m-%dT%H:%M:%SZ')
BUILD_ARCH=${BUILD_ARCH:-unknown}

export BUILD_GIT_SHA BUILD_SOURCE_STATE BUILD_VERSION BUILD_TIMESTAMP BUILD_ARCH
exec docker compose -f "$repo_root/docker-compose.yml" build cfebms
