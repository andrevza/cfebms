#!/bin/sh
set -eu

exec python -m cfebms.supervisor "$@"
