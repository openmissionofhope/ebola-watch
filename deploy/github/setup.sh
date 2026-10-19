#!/usr/bin/env bash
# Set up Ebola Watch without a server: a private operations repository runs the
# pipeline on a schedule and publishes a static site to GitHub Pages of the
# public repository. See docs/DEPLOYMENT.md ("GitHub Pages").
#
#   deploy/github/setup.sh init  <site repo> <ops repo>   create/configure the operations repository
#   deploy/github/setup.sh pages <site repo> [domain]     enable Pages (after the first successful run)
#
# Requires gh (signed in as an owner of both repositories), git, openssl and
# ssh-keygen. Secrets are generated locally and sent straight to GitHub; they are
# never printed. The state key is also kept in $EW_STATE_KEY_FILE (default
# ~/.config/ebola-watch/state-key) so the database can be decrypted outside
# GitHub Actions: store it in a password manager.
set -euo pipefail

usage() { sed -n '5,7p' "$0" >&2; exit 2; }
cmd=${1:-}; site=${2:-}
[[ -n "$cmd" && "$site" == */* ]] || usage
here=$(cd "$(dirname "$0")" && pwd)

has_secret() { gh secret list --repo "$1" --json name --jq '.[].name' | grep -qx "$2"; }

case "$cmd" in
init)
  ops=${3:-}; [[ "$ops" == */* ]] || usage
  key_file=${EW_STATE_KEY_FILE:-$HOME/.config/ebola-watch/state-key}
  tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT

  if ! gh repo view "$ops" >/dev/null 2>&1; then
    gh repo create "$ops" --private --description "Ebola Watch operations: scheduled pipeline, encrypted state and review queue"
  fi

  for name in EW_SECRET_KEY EW_PSEUDONYM_SALT; do
    has_secret "$ops" "$name" || openssl rand -base64 48 | tr -d '\n' | gh secret set "$name" --repo "$ops"
  done
  if ! has_secret "$ops" EW_STATE_KEY; then
    (umask 077; mkdir -p "$(dirname "$key_file")"; [[ -s "$key_file" ]] || openssl rand -base64 48 | tr -d '\n' > "$key_file")
    gh secret set EW_STATE_KEY --repo "$ops" < "$key_file"
    echo "State key saved to $key_file"
  fi
  # The deploy key can push to the site repository: keep it off the default
  # branch (people with write access or above are unaffected).
  if ! gh api "repos/$site/rulesets" --jq '.[].name' | grep -qx "Default branch: people only"; then
    gh api -X POST "repos/$site/rulesets" --input - >/dev/null <<'JSON'
{"name": "Default branch: people only", "target": "branch", "enforcement": "active",
 "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
 "rules": [{"type": "update"}, {"type": "deletion"}, {"type": "non_fast_forward"}],
 "bypass_actors": [{"actor_id": 5, "actor_type": "RepositoryRole", "bypass_mode": "always"},
                   {"actor_id": 2, "actor_type": "RepositoryRole", "bypass_mode": "always"},
                   {"actor_id": 4, "actor_type": "RepositoryRole", "bypass_mode": "always"}]}
JSON
  fi

  gh repo clone "$ops" "$tmp/ops" -- -q 2>/dev/null
  git -C "$tmp/ops" checkout -q -B main
  cp -R "$here/ops-repo/." "$tmp/ops/"
  grep -rl --exclude-dir=.git __SITE_REPO__ "$tmp/ops" | while read -r f; do
    perl -pi -e "s#__SITE_REPO__#$site#g" "$f"
  done
  git -C "$tmp/ops" add -A
  if ! git -C "$tmp/ops" diff --cached --quiet; then
    git -C "$tmp/ops" commit -q -m "Ebola Watch operations repository"
    git -C "$tmp/ops" push -q origin main
  fi
  gh label create data-error --repo "$site" --color d93f0b --description "Report of an error in published data" 2>/dev/null || true
  # Publishing uses a deploy key with write access to the site repository.
  # Organisations created since late 2024 disallow deploy keys by default.
  owner=${site%%/*}
  if [[ "$(gh api "orgs/$owner" --jq '.deploy_keys_enabled_for_repositories' 2>/dev/null)" == "false" ]]; then
    echo "Deploy keys are disabled in the $owner organisation, so the site cannot be published yet." >&2
    echo "An owner can enable them at https://github.com/organizations/$owner/settings/member_privileges" >&2
    echo "(Deploy keys -> Enabled -> Save), then run this command again." >&2
    exit 1
  fi
  if ! has_secret "$ops" PAGES_DEPLOY_KEY; then
    ssh-keygen -q -t ed25519 -N "" -C "ebola-watch publisher ($ops)" -f "$tmp/deploy_key"
    gh repo deploy-key add "$tmp/deploy_key.pub" --repo "$site" --allow-write --title "Ebola Watch publisher ($ops)"
    gh secret set PAGES_DEPLOY_KEY --repo "$ops" < "$tmp/deploy_key"
  fi

  echo "Done. Start the first run with: gh workflow run pipeline.yml --repo $ops"
  echo "When it has succeeded: $0 pages $site [custom domain]"
  ;;
pages)
  domain=${3:-}
  if ! gh api "repos/$site/pages" >/dev/null 2>&1; then
    gh api --silent -X POST "repos/$site/pages" -f "source[branch]=gh-pages" -f "source[path]=/" || true
  fi
  if [[ -n "$domain" ]]; then
    gh api --silent -X PUT "repos/$site/pages" -f "cname=$domain" || true
    # refused until GitHub has issued the certificate (usually within the hour): rerun later
    gh api --silent -X PUT "repos/$site/pages" -F https_enforced=true 2>/dev/null \
      || echo "HTTPS not enforced yet (certificate pending); run this step again later"
  fi
  gh api "repos/$site/pages" --jq '"Pages: " + .html_url + " (status: " + (.status // "pending") + ")"'
  ;;
*) usage ;;
esac
