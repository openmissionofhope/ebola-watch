# Ebola Watch operations (private)

This private repository runs the [Ebola Watch](https://github.com/__SITE_REPO__)
pipeline and holds what must not be public: the database, the secrets and the
human-review queue. The public site is a static snapshot published to GitHub
Pages from the public repository.

* **Schedule:** every 6 hours (`.github/workflows/pipeline.yml`). Run it by hand
  from *Actions → pipeline → Run workflow*.
* **Database:** release `state`, asset `ebolawatch.db.gz.enc` (encrypted with
  the `EW_STATE_KEY` secret), replaced by every run; daily backups kept for 14
  days. Do not delete the release.
* **Logs:** the Actions runs of this repository.

## Reviewing

Every item that needs a person — an alert that relies on unofficial reports, a
signal cluster, a machine-extracted official figure that failed a consistency
check, an auto-registered outbreak — arrives as an issue labelled `ew-review`.

1. Read the issue. Source excerpts are in the first comment, which is deleted
   automatically after the raw-content retention period (30 days).
2. Add the label **approve** or **reject**. Whoever adds the label is recorded
   as the reviewer in the audit log.
3. The label starts a short run that applies the decision and republishes the
   site; the issue is then closed with a note.

To ask for more information, comment and leave the issue open: the item stays
pending, and alerts stay unpublished.

## Retractions and transport status

Use *New issue → Retract published output* or *Change a transport service
status*. Nothing happens until someone with write access adds the **apply**
label. If a request cannot be applied, the issue gets `apply-failed` and an
explanation; edit it and add **apply** again.

## Settings

Repository variables (*Settings → Secrets and variables → Actions → Variables*):

| Variable | Purpose |
|---|---|
| `EW_SITE_DOMAIN` | Custom domain for the site (e.g. `ebolawatch.example.org`); empty for `<owner>.github.io/<repo>/` |
| `EW_SOURCE_ACKNOWLEDGEMENTS` | Sources with data-use conditions you have honoured (see `docs/DATA_SOURCES.md`) |
| `EW_DISABLED_SOURCES` | Sources to skip |

Secrets: `EW_SECRET_KEY`, `EW_PSEUDONYM_SALT`, `EW_STATE_KEY`,
`PAGES_DEPLOY_KEY` (write deploy key of the public repository), and optional
source credentials (`EW_RELIEFWEB_APPNAME`, `EW_YOUTUBE_API_KEY`,
`EW_X_BEARER_TOKEN`, `EW_REDDIT_CLIENT_ID`, `EW_REDDIT_CLIENT_SECRET`,
`EW_PROMED_FEED_URL`, `EW_RSS_FEEDS`).

Changing `EW_PSEUDONYM_SALT` changes every author pseudonym; losing
`EW_STATE_KEY` makes the saved database unreadable (a new one is not created
automatically — see `docs/DEPLOYMENT.md` in the public repository).

## Inspecting the database locally

```bash
gh release download state --repo <this repo> --pattern ebolawatch.db.gz.enc
openssl enc -d -aes-256-cbc -pbkdf2 -iter 200000 -pass file:<state key file> \
  -in ebolawatch.db.gz.enc | gunzip > ebolawatch.db
EW_DATABASE_URL=sqlite:///$PWD/ebolawatch.db ebolawatch serve   # read-only use: changes are not uploaded
```
