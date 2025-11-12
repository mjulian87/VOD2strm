# Dispatcharr VOD Exporter  
### STRM + NFO + TMDB Artwork Generator for Emby / Jellyfin / Plex / Kodi

A high-performance VOD exporter for **Dispatcharr** that builds complete `.strm` libraries for **Movies** and **TV Shows**, enriched with:

- TMDB metadata (movie, TV, episode)
- NFO files (movie, tvshow, episode)
- Posters, fanart, episode thumbnails
- Per-account category-based folder trees
- Full caching + incremental updates
- Dispatcharr proxy URLs for video streaming
- Safe **dry-run mode** for testing

This project replaces earlier database-based exporters and is designed to **supersede** `strmvod` by including all of its strengths plus major enhancements.

---

## 🚀 Features

### 🔹 API-only (No PostgreSQL Needed)

Talks to Dispatcharr’s REST API instead of the DB:

- `/api/vod/movies/`
- `/api/vod/series/`
- `/api/vod/series/{id}/provider-info/?include_episodes=true`

No DB credentials, no schema knowledge required.  
Future Dispatcharr upgrades are less likely to break your exporter.

---

### 🔹 Multi-account Support with Globs

Use `XC_NAMES` with Unix-style globs to match M3U/XC accounts:

```bash
XC_NAMES="Strong 8K"
XC_NAMES="UK *"
XC_NAMES="UK *,Movies*,Strong 8K"
XC_NAMES="*"                  # all accounts
```

Each matched account gets its own Movies/Series folder tree under `/mnt/Share-VOD/{XC_NAME}/...`.

---

### 🔹 Intelligent Caching (Fast Re-Runs)

The exporter maintains per-account caches:

- `movies.json` – cached movie list  
- `series.json` – cached series list  
- `provider-info/*.json` – per-series provider-info (episodes)  
- `tmdb/json/...` – movie/TV/episode TMDB JSON  
- `tmdb/images/...` – TMDB poster/backdrop/still images  

You can force a full rebuild:

```bash
VOD_CLEAR_CACHE=true ./vod_export.py
```

or set `VOD_CLEAR_CACHE="true"` in `vod_export_vars.sh`.

---

### 🔹 High-quality NFO & Artwork Metadata

When `ENABLE_NFO=true` and/or `ENABLE_IMAGES=true`, the exporter writes:

- Movies:
  - `Movie Name (Year).strm`
  - `movie.nfo`
  - `poster.jpg`
  - `fanart.jpg`
- Series:
  - `tvshow.nfo` in the series folder
  - Series-level `poster.jpg` + `fanart.jpg`
  - Episode-level:
    - `S01E01 - Title.strm`
    - `S01E01 - Title.nfo`
    - `S01E01 - Title.thumb.jpg`

All naming is safe for **Emby/Jellyfin/Plex/Kodi**.

---

### 🔹 Clean Naming / Title Normalization

Movies:

```text
/mnt/Share-VOD/<XC_NAME>/Movies/<Category>/Movie Name (Year)/Movie Name (Year).strm
```

Series:

```text
/mnt/Share-VOD/<XC_NAME>/Series/<Category>/Show Name (Year)/Season 01/S01E01 - Title.strm
```

The exporter:

- Normalises Unicode titles
- Strips noise like:
  - `1080p`, `4K`, `HDR`, `H.265`, etc.
  - `[EN]`, `[SUBS]`, `[MULTI]`, etc.
- Removes trailing technical tags and redundant separators

---

### 🔹 TMDB Enriched Metadata

If `TMDB_API_KEY` is set, the exporter:

- Directly fetches metadata for titles with a known `tmdb_id`
- Falls back to TMDB **search** by title and year (movie + TV)
- Pulls per-episode metadata from `tv/{id}/season/{s}/episode/{e}`
- Downloads poster/backdrop/still images from TMDB’s CDN
- Caches everything to avoid re-hitting TMDB unnecessarily

---

### 🔹 Safe Atomic Writes & Optional Cleanup

- `.strm` and `.nfo` are written atomically (temp file then `os.replace`)
- Stale `.strm` files can be removed when they no longer correspond to active content:

```bash
VOD_DELETE_OLD="true"
```

Empty directories are cleaned up from the bottom up (unless in dry-run).

---

### 🔹 Dry-Run Mode (Safe Simulation)

You can **simulate a full export without changing any files**.

See the **Dry-Run Mode** section below for details.

---

## 📦 Requirements

- Python **3.8+**
- `requests` Python package
- A working Dispatcharr instance (0.11+ recommended)
- Optionally, a **TMDB API key** for richer metadata and artwork
- Shared storage directory where Emby/Jellyfin/Plex/Kodi can read the `.strm` libraries

---

## ⚙ Installation

```bash
cd /opt
git clone https://github.com/<YOUR_USER>/DispatcharrEmby
cd DispatcharrEmby
chmod +x vod_export.py
```

Install Python dependencies:

```bash
pip install requests
```

---

## ⚙ Configuration – `vod_export_vars.sh`

Example configuration:

```bash
#!/usr/bin/env bash

########################################
# Core paths
########################################

VOD_MOVIES_DIR="/mnt/Share-VOD/{XC_NAME}/Movies"
VOD_SERIES_DIR="/mnt/Share-VOD/{XC_NAME}/Series"

VOD_LOG_FILE="/opt/dispatcharr_vod/vod_export.log"
VOD_CACHE_DIR="/opt/dispatcharr_vod/cache"

########################################
# Dispatcharr API
########################################

DISPATCHARR_BASE_URL="http://127.0.0.1:9191"
DISPATCHARR_API_USER="admin"
DISPATCHARR_API_PASS="your_admin_password_here"
HTTP_USER_AGENT="DispatcharrEmbyVOD/1.0"

########################################
# XC account filter
########################################

XC_NAMES="*"

########################################
# Export toggles
########################################

VOD_EXPORT_MOVIES="true"
VOD_EXPORT_SERIES="true"

########################################
# NFO / TMDB metadata
########################################

ENABLE_NFO="true"
VOD_OVERWRITE_NFO="false"
TMDB_API_KEY=""
NFO_LANG="en-US"
TMDB_THROTTLE_SEC="0.30"

########################################
# Image / artwork settings
########################################

ENABLE_IMAGES="true"
VOD_OVERWRITE_IMAGES="false"
TMDB_IMAGE_SIZE_POSTER="w500"
TMDB_IMAGE_SIZE_BACKDROP="w780"
TMDB_IMAGE_SIZE_STILL="w300"

########################################
# Cleanup / cache behaviour
########################################

VOD_DELETE_OLD="true"
VOD_CLEAR_CACHE="false"

########################################
# Dry-run mode
########################################

VOD_DRY_RUN="false"
```

You can also override most settings per-run using environment variables, e.g.:

```bash
VOD_CLEAR_CACHE=true VOD_DRY_RUN=true ./vod_export.py
```

---

## 🧪 Dry-Run Mode (Test Without Writing Files)

Dry-run mode lets you run a full simulation of the export:

- Connects to Dispatcharr
- Fetches movies/series and provider-info (episodes)
- Walks through TMDB metadata and image logic
- Builds the full folder and filename layout **in memory**
- Logs everything it **would** do

…but **does not**:

- Create directories  
- Write `.strm` files  
- Write `.nfo` files  
- Download or copy images  
- Save any caches  
- Remove stale `.strm` files  
- Remove empty directories  
- Delete or clear the cache directory  

### Enable dry-run in config

```bash
VOD_DRY_RUN="true"
```

### Or per-run, overriding the config

```bash
VOD_DRY_RUN=true ./vod_export.py
```

### Example dry-run log lines

```text
[2025-11-12 20:10:01] VOD_DRY_RUN=true: DRY RUN - no files, directories, or caches will be written or deleted.
[2025-11-12 20:10:02] [dry-run] Would create directory: /mnt/Share-VOD/Strong 8K/Movies/Action/Die Hard (1988)
[2025-11-12 20:10:02] [dry-run] Would write file: /mnt/Share-VOD/Strong 8K/Movies/Action/Die Hard (1988)/Die Hard (1988).strm
[2025-11-12 20:10:02] [dry-run] Would write file: /mnt/Share-VOD/Strong 8K/Movies/Action/Die Hard (1988)/movie.nfo
[2025-11-12 20:10:02] [dry-run] Would download TMDB image /abc123.jpg size=w500 to /mnt/Share-VOD/Strong 8K/Movies/Action/Die Hard (1988)/poster.jpg
[2025-11-12 20:10:02] [dry-run] Would delete stale movie STRM: /mnt/Share-VOD/Strong 8K/Movies/Old Title (1970)/Old Title (1970).strm
```

Use this mode to validate:

- Folder layout
- Naming rules
- Category mapping
- Episode enumeration
- Proxy URLs
- TMDB/Emby behaviour assumptions

…before doing a real write.

---

## ▶️ Running the Export

Manual run (normal mode):

```bash
./vod_export.py
```

Full reset + real run:

```bash
VOD_CLEAR_CACHE=true ./vod_export.py
```

Full dry-run of a clean rebuild:

```bash
VOD_CLEAR_CACHE=true VOD_DRY_RUN=true ./vod_export.py
```

### Suggested Cron Jobs

Run exporter nightly at 02:00:

```bash
0 2 * * * /opt/dispatcharr_vod/vod_export.py >> /opt/dispatcharr_vod/vod_export.log 2>&1
```

Trigger Emby/Jellyfin library refresh at 04:00:

```bash
0 4 * * * curl "http://emby:8096/emby/Library/Refresh?api_key=YOUR_EMBY_API_KEY" >/dev/null 2>&1
```

---

## 📂 Output Structure Examples

### Movies

```text
/mnt/Share-VOD/Strong 8K/Movies/Action/
  Die Hard (1988)/
    Die Hard (1988).strm
    movie.nfo
    poster.jpg
    fanart.jpg
```

### Series

```text
/mnt/Share-VOD/Strong 8K/Series/Drama/
  Breaking Bad (2008)/
    tvshow.nfo
    poster.jpg
    fanart.jpg
    Season 01/
      S01E01 - Pilot.strm
      S01E01 - Pilot.nfo
      S01E01 - Pilot.thumb.jpg
```

---

## 📘 Emby Library Setup (Recommended Settings)

This exporter is optimized for **Emby**, but the structure works with **Jellyfin, Plex, and Kodi**.

### Library Types

Create separate libraries for:

- **Movies** → `/mnt/Share-VOD/<XC_NAME>/Movies`  
- **TV Shows** → `/mnt/Share-VOD/<XC_NAME>/Series`

Set library types to “Movies” and “TV Shows” respectively.

---

### Metadata Settings (Emby)

Turn **ON**:

- ✅ Use local metadata  
- ✅ Save artwork to media folders  
- ✅ Enable NFO metadata  
- ✅ Use NFO for titles & metadata  
- ✅ Use NFO for images  

Optionally turn **OFF**:

- Online metadata providers (TMDB, TVDB, etc.)  
  → Emby will strictly respect your `.nfo` and local images.

---

### Artwork Settings

Because the exporter writes:

- `poster.jpg`
- `fanart.jpg`
- Episode `*.thumb.jpg`

…you can:

- Disable online artwork providers for these libraries, OR
- Keep them enabled as a fallback – Emby will still prioritize local images.

---

### Library Monitoring

For very large IPTV libraries:

- Disable **real-time monitoring** of folders  
- Use scheduled library refresh (e.g. 04:00 daily)

---

### Skip Intro / Chapter Images

For STRM-based playback, these features usually add overhead:

- You can safely **disable intro detection** and **chapter image extraction** to speed up scanning.

---

## ✔ Summary

This exporter provides:

- Clean, cross-platform folder structures  
- STRM playback via Dispatcharr proxy  
- NFO metadata for movies, tvshow, and episodes  
- High-quality TMDB artwork (poster/fanart/thumbs)  
- Account-based caching and incremental updates  
- A robust **dry-run mode** for safe testing  

Works great with:

- ✅ Emby  
- ✅ Jellyfin  
- ✅ Kodi  
- ✅ Plex (with some naming tolerances)

---

## 🛠 Roadmap / Ideas

- Dispatcharr plugin wrapper
- Optional Plex `.plexmatch` / `.plexignore` support
- Web UI to trigger exports and show progress
- Parallelized TMDB/artwork fetching
- JSON/HTML catalogs of exported content
- Notifications (Telegram/Discord) on run summary

Contributions, issues, and PRs are very welcome.

---

## 📄 License

MIT License.
