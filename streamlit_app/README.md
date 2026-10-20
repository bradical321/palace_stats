# FC 27 Streamlit app

Replaces `palace/app.R` + `palace/tagger_app/` with one app, for the FC 27
rollover (club 23137, "Palace"). Confirmed live against that club on
2026-10-14 — see the notes in `collector.py`'s module docstring for exactly
what did and didn't change from the FC 24-26 pipeline.

## Quick start (local storage, no Google Drive needed yet)

```bash
cd streamlit_app
pip install -r requirements.txt
playwright install chromium   # one-time, if not already installed

python collector.py           # pulls matches + roster, pops a visible Chrome window
python opponent_scout.py      # pulls win% + rosters for every opponent you've played
streamlit run Overview.py
```

Data lands in `streamlit_app/data/*.csv` (gitignored). This is enough to use
the whole app today — Drive is an optional upgrade for multi-machine / shared
access, not a requirement to get started.

## Why the collector needs a visible browser window

EA's Akamai bot-protection blocks plain HTTP requests and headless Chromium
alike (403 / `ERR_HTTP2_PROTOCOL_ERROR`) — confirmed again on the FC 27
endpoints. The only thing that gets through is a real, visible browser
loading the ea.com Clubs page and `fetch()`-ing the API from inside that
page's JS context, same as before. That means:

- `collector.py` and `opponent_scout.py` must run somewhere with a display —
  your Mac via cron, same as the current setup. They cannot run on Streamlit
  Community Cloud or any headless CI runner.
- The Streamlit **app** itself has no such restriction — it only reads
  already-collected CSVs (local or Drive), so it can run anywhere.

## Switching to Google Drive storage

1. In the [Google Cloud Console](https://console.cloud.google.com/), create
   a project (or reuse one) and enable the **Google Drive API**.
2. Create a **service account** (IAM & Admin → Service Accounts → Create),
   then add a JSON key for it and download the file.
3. In Google Drive, create a folder for this app's data and **share it**
   with the service account's email address (looks like
   `something@your-project.iam.gserviceaccount.com`) — treat it like sharing
   with a person, Editor access.
4. Copy the folder's id out of its URL:
   `https://drive.google.com/drive/folders/<THIS_PART>`
5. Set these before running anything:
   ```bash
   export FC_STORAGE_BACKEND=drive
   export FC_DRIVE_FOLDER_ID=<the folder id>
   export GOOGLE_SERVICE_ACCOUNT_JSON=/path/to/the-key.json   # or the raw JSON text
   ```
   On Streamlit Community Cloud, put the same three as app **secrets**
   instead of env vars (`GOOGLE_SERVICE_ACCOUNT_JSON` as the raw JSON text is
   usually easier there than a file path).

Nothing else changes — every page and script goes through `storage.py`'s
`get_storage()`, so flipping that one env var moves the whole app's data
source from local CSVs to the shared Drive folder.

## What the app has today

- **Overview** — record, form (last 10), streak. (A "trending hot/cold over
  the last 10 games" per-player view was cut for now — needs more match
  volume and a clearer definition of "trending" before it's worth building.)
- **Player Stats** — season aggregates incl. win %, shot conversion %; every
  stat column (except games played) is percentile-tier shaded — top quarter
  tinted green, bottom quarter tinted red, middle half left alone. Archetype
  shown once named (see Admin). Plus a per-player **scouting report**: a
  FotMob/FBref-style percentile bar list (pass completion, goals/game,
  shot conversion, rating, win rate, etc.) against either just your own
  roster or every roster scouted so far.
- **Match History** — pick a match, see both rosters side by side.
- **Matchup Analysis** — our record broken out by opponent tier (bucketed
  by their own season win %, via `opponent_club_stats.csv`) and by lineup
  size difference (short-handed / even / a player up). No standalone
  opponent-browsing tab anymore — that data now only feeds this page and
  the Player Stats scouting report. Refresh opponent data with
  `python opponent_scout.py`.
- **Win Shares** — not built yet. The page previews the joined inputs
  (player, position, archetype, team sizes, opponent win %, result) the
  model will need; the weighting logic itself is still to design.
- **Admin** (password-protected — see below) — classify EA "friendly"
  matches as our real **Comp** league vs a true casual **Friendly** vs
  **Cup** vs **Exclude**; fix a wrong score; name a newly-seen player
  archetype id; override one player's stats for one match.

## Protecting the Admin page

Set an admin password before anyone else can get into match tagging:

```bash
export FC_ADMIN_PASSWORD=whatever-you-want
```

On Streamlit Community Cloud, set it as a secret instead
(`FC_ADMIN_PASSWORD = "..."` in the app's Secrets). Without it set, the
Admin page stays open to anyone and shows a warning saying so — it's not
locked by default, since local dev shouldn't need a password to test.

## The League / Comp / All filter

EA's own ranked ladder (`leagueMatch`) is auto-tagged **League** — no manual
work. Everything this group's actual competitive league/cup play happens
through shows up in EA's data as `friendlyMatch`, so a new one always starts
as **Needs Review** until you tag it **Comp**, **Friendly**, or **Cup** on
the Tag Matches page. The sidebar filter (League / Comp / All) controls
every other page at once.

## Known gaps / next steps

- **Archetype names**: EA doesn't publish an id → name table, and the ids
  aren't simply numbered per position (id 4/5/6 show up under both
  "defender" and "midfielder" on this club already). Name them as they turn
  up on the Tag Matches page by checking your in-game Clubhouse.
- **Win shares model**: inputs are wired up; the actual scoring logic is a
  follow-on design conversation.
