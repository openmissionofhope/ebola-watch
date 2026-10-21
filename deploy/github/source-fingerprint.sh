#!/usr/bin/env bash
# Prints a short fingerprint of what the hourly check watches: the time of the
# latest ECDC update, the latest WHO Disease Outbreak News item, and the code
# repository's commit (which includes data/official/statements.yaml). When it
# differs from the fingerprint of the last published run, the pipeline runs in
# full (.github/workflows/publish-static.yml, mode "check").
#
#   deploy/github/source-fingerprint.sh <code repo> [ref]
#
# Exits non-zero when any of them cannot be read, so a source that is briefly
# unreachable never looks like a change. Requires curl, jq and gh.
set -euo pipefail
repo=${1:?usage: source-fingerprint.sh <code repo> [ref]}
ref=${2:-main}
ua="EbolaWatch/0.1 (Open Mission of Hope; +https://openmissionofhope.org)"

page=$(curl -fsS --max-time 30 -A "$ua" https://www.ecdc.europa.eu/en/ebola-outbreak-democratic-republic-congo-and-uganda)
ecdc=$(grep -oE 'last updated on [^<.]{3,40}' <<<"$page" | head -n 1)
# shellcheck disable=SC2016  # OData parameters start with a literal $
who=$(curl -fsS --max-time 30 -A "$ua" -G https://www.who.int/api/news/diseaseoutbreaknews \
  --data-urlencode '$orderby=LastModified desc' --data-urlencode '$top=1' --data-urlencode '$select=DonId,LastModified' \
  | jq -er '.value[0] | "\(.DonId) \(.LastModified)"')
code=$(gh api "repos/$repo/commits/$ref" --jq .sha)

[[ -n "$ecdc" && -n "$who" && -n "$code" ]]
printf '%s\n' "$ecdc" "$who" "$code" | sha256sum | cut -c1-16
