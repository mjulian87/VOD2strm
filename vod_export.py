#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import re
import json
import shlex
import subprocess
import shutil
import os
import unicodedata
from pathlib import Path
from datetime import datetime

import psycopg2
from psycopg2.extras import DictCursor
import requests

VARS_FILE = "/opt/dispatcharr_vod/vod_export_vars.sh"

# ------------------------------------------------------------
# Load vars from vod_export_vars.sh
# ------------------------------------------------------------
def load_vars(file_path: str) -> dict:
    env = {}
    with open(file_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


VARS = load_vars(VARS_FILE)

# --- DB ---
PG_HOST = VARS.get("PG_HOST", "localhost")
PG_PORT = int(VARS.get("PG_PORT", "5432"))
PG_DB = VARS.get("PG_DB", "dispatcharr")
PG_USER = VARS.get("PG_USER", "dispatch")
PG_PASSWORD = VARS.get("PG_PASSWORD", "")

# --- Output paths ---
VOD_MOVIES_DIR_TEMPLATE = VARS["VOD_MOVIES_DIR"]
VOD_SERIES_DIR_TEMPLATE = VARS["VOD_SERIES_DIR"]

DELETE_OLD = VARS.get("VOD_DELETE_OLD", "false").lower() == "true"
LOG_FILE = VARS.get("VOD_LOG_FILE", "/opt/dispatcharr_vod/vod_export.log")
XC_NAMES_RAW = VARS.get("XC_NAMES", "").strip()

# NEW: Dispatcharr API for series provider-info
DISPATCHARR_BASE = VARS.get("DISPATCHARR_BASE", "http://127.0.0.1:9191")
DISPATCHARR_API_USER = VARS.get("DISPATCHARR_API_USER", "admin")
DISPATCHARR_API_PASS = VARS.get("DISPATCHARR_API_PASS", "")

# Env override for a single run
clear_cache_env = os.getenv("VOD_CLEAR_CACHE")
if clear_cache_env is not None:
    CLEAR_CACHE = clear_cache_env.lower() == "true"
else:
    CLEAR_CACHE = VARS.get("VOD_CLEAR_CACHE", "false").lower() == "true"

MAX_COMPONENT_LEN = 80
CACHE_BASE_DIR = Path("/opt/dispatcharr_vod/cache")


# ------------------------------------------------------------
# Logging helpers
# ------------------------------------------------------------
def log(msg: str) -> None:
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    Path(LOG_FILE).parent.mkdir(parents=True, exist_ok=True)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ------------------------------------------------------------
# String / filesystem helpers
# ------------------------------------------------------------
def sanitize(name: str) -> str:
    return re.sub(r'[\\/*?:"<>|]', "", (name or "").strip())


def shorten_component(name: str, limit: int = MAX_COMPONENT_LEN) -> str:
    name = sanitize(name)
    if len(name) <= limit:
        return name
    return name[: limit - 10].rstrip() + "..." + name[-7:]


def safe_account_name(account_name: str) -> str:
    return sanitize(account_name).replace(" ", "_")


def clean_title(raw: str) -> str:
    """
    Clean provider-style junk from titles and normalize odd unicode.

    - Normalizes unicode (fixes superscripts/small-caps style glyphs)
    - Strips common quality/language tags in [] or ()
    - Removes trailing '- EN' / '- 1080p' style suffixes
    - Removes existing '(YYYY)' at the end (we add our own)
    - Collapses multiple spaces
    """
    if not raw:
        return ""

    # Normalize odd unicode to standard form
    s = unicodedata.normalize("NFKC", str(raw))

    # Remove [bracketed] and (parenthesized) common junk tags
    # e.g. [EN], [4K], (1080p), (Multi-Audio)
    s = re.sub(
        r"\s*[\[(](?:\d{3,4}p|4K|UHD|FHD|HD|SD|EN|ENG|DUAL|MULTI|MULTI-AUDIO|SUBS?|DUBBED)[\])]",
        "",
        s,
        flags=re.IGNORECASE,
    )

    # Remove trailing '- XXX' resolution / language tags
    s = re.sub(
        r"\s*-\s*(?:\d{3,4}p|4K|UHD|FHD|HD|SD|EN|ENG|DUAL|MULTI|MULTI-AUDIO|SUBS?|DUBBED)\s*$",
        "",
        s,
        flags=re.IGNORECASE,
    )

    # Remove a trailing (YYYY)
    s = re.sub(r"\(\s*\d{4}\s*\)\s*$", "", s)

    # Collapse whitespace
    s = re.sub(r"\s+", " ", s).strip()

    return s


def mkdir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_strm(path: Path, url: str) -> None:
    """
    Write a .strm file with the given URL (one line, trailing newline).
    """
    mkdir(path.parent)
    content = f"{url}\n"
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(content)
    os.replace(tmp, path)


# ------------------------------------------------------------
# DB helpers
# ------------------------------------------------------------
def get_pg_conn():
    return psycopg2.connect(
        host=PG_HOST,
        port=PG_PORT,
        dbname=PG_DB,
        user=PG_USER,
        password=PG_PASSWORD,
    )


def parse_xc_name_filters(raw: str):
    """
    XC_NAMES: comma-separated list of account names or SQL LIKE patterns.
    If empty or '%' -> match all.
    """
    if not raw:
        return ["%"]
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return parts or ["%"]


def get_xc_accounts():
    """
    Return a list of XC accounts with fields:
      id, name, server_url, username, password
    Filtered by XC_NAMES patterns.
    """
    patterns = parse_xc_name_filters(XC_NAMES_RAW)

    with get_pg_conn() as conn, conn.cursor(cursor_factory=DictCursor) as cur:
        if patterns == ["%"]:
            sql = """
                SELECT id, name, server_url, username, password
                FROM m3u_m3uaccount
                ORDER BY name
            """
            cur.execute(sql)
        else:
            where_clauses = []
            params = []
            for p in patterns:
                where_clauses.append("name LIKE %s")
                params.append(p)
            sql = f"""
                SELECT id, name, server_url, username, password
                FROM m3u_m3uaccount
                WHERE {" OR ".join(where_clauses)}
                ORDER BY name
            """
            cur.execute(sql, params)

        rows = cur.fetchall()
        accounts = [dict(r) for r in rows]

    log(
        f"Selected {len(accounts)} XC account(s) from m3u_m3uaccount "
        f"with patterns: {', '.join(patterns)}"
    )
    for a in accounts:
        log(f"  - Account '{a['name']}' ({a['server_url']})")
    return accounts


# ------------------------------------------------------------
# Movie queries + cache
# ------------------------------------------------------------
def fetch_movies_for_account(account_id: int):
    """
    One row per movie for this m3u_account_id.
    """
    sql = """
        SELECT DISTINCT
            m.name              AS title,
            m.year              AS year,
            cat.name            AS category,
            rel.stream_id       AS stream_id,
            rel.container_extension AS container_extension
        FROM vod_movie m
        JOIN vod_m3umovierelation rel
          ON rel.movie_id = m.id
        LEFT JOIN vod_vodcategory cat
          ON cat.id = rel.category_id
        WHERE rel.m3u_account_id = %s
    """
    with get_pg_conn() as conn, conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(sql, (account_id,))
        return cur.fetchall()


def get_movies_cache_path(account_name: str) -> Path:
    safe_name = sanitize(account_name).replace(" ", "_")
    return CACHE_BASE_DIR / safe_name / "movies.json"


def fetch_movies_for_account_cached(acc: dict):
    """
    Cached wrapper around fetch_movies_for_account.

    Cache file:
      /opt/dispatcharr_vod/cache/<account_name_sanitized>/movies.json
    """
    account_id = acc["id"]
    account_name = acc["name"]
    cache_path = get_movies_cache_path(account_name)

    # Try cache first
    if cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                data = json.load(f)
            return data
        except Exception as e:
            log(f"Failed to read movie cache for account '{account_name}': {e}")

    # No cache or bad cache -> query DB
    rows = fetch_movies_for_account(account_id)
    data = [dict(r) for r in rows]

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(data, f)
    except Exception as e:
        log(f"Failed to write movie cache for account '{account_name}': {e}")

    return data


def fetch_series_list_for_account(account_id: int):
    """
    One row per series for this m3u_account_id.
    """
    sql = """
        SELECT DISTINCT
            s.id                AS series_id,
            s.name              AS series_title,
            cat.name            AS category
        FROM vod_series s
        JOIN vod_m3useriesrelation sr
          ON sr.series_id = s.id
        LEFT JOIN vod_vodcategory cat
          ON cat.id = sr.category_id
        WHERE sr.m3u_account_id = %s
    """
    with get_pg_conn() as conn, conn.cursor(cursor_factory=DictCursor) as cur:
        cur.execute(sql, (account_id,))
        return cur.fetchall()


# ------------------------------------------------------------
# Dispatcharr API helpers (for series provider-info)
# ------------------------------------------------------------
def api_login(base: str, username: str, password: str) -> str:
    """
    Authenticate against Dispatcharr and return JWT access token.
    """
    url = f"{base.rstrip('/')}/api/accounts/token/"
    resp = requests.post(url, json={"username": username, "password": password}, timeout=30)
    if resp.status_code != 200:
        raise RuntimeError(f"Dispatcharr login failed: {resp.status_code} {resp.text}")
    data = resp.json()
    token = data.get("access")
    if not token:
        raise RuntimeError("Dispatcharr login succeeded but no 'access' token found")
    return token


def api_get_series_provider_info(base: str, token: str, series_id: int) -> dict:
    """
    Call /api/vod/series/{id}/provider-info/?include_episodes=true
    (this is what the Dispatcharr UI uses for episodes).
    """
    url = f"{base.rstrip('/')}/api/vod/series/{series_id}/provider-info/?include_episodes=true"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    resp = requests.get(url, headers=headers, timeout=60)
    resp.raise_for_status()
    if not resp.content:
        return {}
    return resp.json()


def normalize_provider_info(info: dict) -> dict:
    """
    Convert provider-info JSON into:
        { "episodes": { "<season_key>": [ episode_dict, ... ], ... } }

    Each episode dict will have at least:
      - season_number
      - episode_number
      - title
      - uuid
      - id
      - container_extension
    """
    episodes_by_season = {}

    raw_eps = info.get("episodes") or []
    if isinstance(raw_eps, dict):
        flat = []
        for v in raw_eps.values():
            if isinstance(v, list):
                flat.extend(v)
        raw_eps = flat

    if not isinstance(raw_eps, list):
        return {"episodes": {}}

    for ep in raw_eps:
        if not isinstance(ep, dict):
            continue

        # Season
        season_val = (
            ep.get("season_number")
            or ep.get("season")
            or ep.get("season_num")
            or 0
        )
        try:
            season_int = int(season_val)
        except Exception:
            season_int = 0
        season_key = str(season_int)

        # Episode number
        ep_num_val = ep.get("episode_number") or ep.get("episode_num") or 0
        try:
            ep_num_int = int(ep_num_val)
        except Exception:
            ep_num_int = 0

        # Title
        title = ep.get("title") or ep.get("name") or f"Episode {ep_num_int}"

        norm_ep = dict(ep)
        norm_ep["season_number"] = season_int
        norm_ep["episode_number"] = ep_num_int
        norm_ep["title"] = title

        episodes_by_season.setdefault(season_key, []).append(norm_ep)

    for key, eps in episodes_by_season.items():
        episodes_by_season[key] = sorted(
            eps, key=lambda e: e.get("episode_number") or 0
        )

    return {"episodes": episodes_by_season}


def normalize_host_for_proxy(base: str) -> str:
    """
    Strip scheme and trailing slashes so we can build http://host/proxy/... URLs.
    """
    host = (base or "").strip()
    host = re.sub(r"^https?://", "", host, flags=re.I)
    return host.strip().strip("/")


def get_provider_info_cache_path(account_name: str, series_id: int) -> Path:
    safe_name = sanitize(account_name).replace(" ", "_")
    return CACHE_BASE_DIR / safe_name / f"provider_series_{series_id}.json"


def dispatcharr_provider_info_cached(
    account_name: str,
    api_base: str,
    token: str,
    series_id: int,
) -> dict:
    """
    Cached wrapper around api_get_series_provider_info.

    Cache file:
      /opt/dispatcharr_vod/cache/<account_name_sanitized>/provider_series_<id>.json
    """
    cache_path = get_provider_info_cache_path(account_name, series_id)

    if cache_path.exists():
        try:
            with open(cache_path, "r") as f:
                return json.load(f)
        except Exception as e:
            log(f"Failed to read provider-info cache for series_id={series_id} ({account_name}): {e}")

    info = api_get_series_provider_info(api_base, token, series_id)
    if not info:
        return {}

    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        with open(cache_path, "w") as f:
            json.dump(info, f)
    except Exception as e:
        log(f"Failed to write provider-info cache for series_id={series_id} ({account_name}): {e}")

    return info


# ------------------------------------------------------------
# Exporters (per account)
# ------------------------------------------------------------
def export_movies_for_account(acc: dict):
    """
    Movies: unchanged – still use XC URLs via DB info.
    """
    account_id = acc["id"]
    account_name = acc["name"]
    endpoint = (acc["server_url"] or "").rstrip("/")
    username = acc["username"] or ""
    password = acc["password"] or ""

    movies_dir = Path(
        VOD_MOVIES_DIR_TEMPLATE.replace("{XC_NAME}", account_name)
    )

    log(f"=== Exporting Movies for account '{account_name}' ===")
    log(f"Movies dir: {movies_dir}")

    mkdir(movies_dir)

    rows = fetch_movies_for_account_cached(acc)
    total_movies = len(rows)

    if total_movies == 0:
        log(f"No movies found for account '{account_name}', skipping movie export.")
        return

    log(f"Movies to process for '{account_name}': {total_movies}")

    count_written = 0
    movies_processed = 0
    next_progress_pct = 10  # log at 10%, 20%, ...

    added = 0
    updated = 0
    removed = 0

    expected_files = set()

    for r in rows:
        raw_title = r.get("title") or "Unknown Movie"
        cleaned_title = clean_title(raw_title) or "Unknown Movie"

        category = shorten_component(r.get("category") or "Uncategorized")

        year = r.get("year")
        try:
            year_int = int(year) if year is not None else 0
        except Exception:
            year_int = 0

        if year_int > 0:
            title_with_year = f"{cleaned_title} ({year_int})"
        else:
            title_with_year = cleaned_title

        title_clean = shorten_component(title_with_year)

        stream_id = r.get("stream_id")
        ext = r.get("container_extension") or "mp4"

        movies_processed += 1

        if not stream_id or not endpoint or not username or not password:
            pct = (movies_processed * 100) // total_movies
            if pct >= next_progress_pct:
                log(
                    f"Movies export '{account_name}': {pct}% "
                    f"({movies_processed}/{total_movies} movies processed, "
                    f"{count_written} .strm written so far)"
                )
                while next_progress_pct <= pct and next_progress_pct < 100:
                    next_progress_pct += 10
            continue

        url = f"{endpoint}/movie/{username}/{password}/{stream_id}.{ext}"
        folder = movies_dir / category / title_clean
        strm_file = folder / f"{title_clean}.strm"

        expected_files.add(strm_file)

        existed_before = strm_file.exists()
        write_strm(strm_file, url)
        count_written += 1
        if existed_before:
            updated += 1
        else:
            added += 1

        pct = (movies_processed * 100) // total_movies
        if pct >= next_progress_pct:
            log(
                f"Movies export '{account_name}': {pct}% "
                f"({movies_processed}/{total_movies} movies processed, "
                f"{count_written} .strm written so far)"
            )
            while next_progress_pct <= pct and next_progress_pct < 100:
                next_progress_pct += 10

    if DELETE_OLD and movies_dir.exists():
        for existing in movies_dir.glob("**/*.strm"):
            if existing not in expected_files:
                existing.unlink()
                removed += 1
        log(f"Movies cleanup for '{account_name}': removed {removed} stale .strm files.")

        dirs = [p for p in movies_dir.glob("**/*") if p.is_dir()]
        for d in sorted(dirs, key=lambda p: len(p.as_posix()), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass

    active = len(expected_files)
    log(
        f"Movies export summary for '{account_name}': "
        f"{added} added, {updated} updated, {removed} removed, {active} active."
    )


def export_series_for_account(acc: dict, api_base: str, api_token: str):
    """
    Series: use Dispatcharr API provider-info for episodes,
    still using DB to know which series belong to the account.
    """
    account_id = acc["id"]
    account_name = acc["name"]

    series_dir = Path(
        VOD_SERIES_DIR_TEMPLATE.replace("{XC_NAME}", account_name)
    )

    log(f"=== Exporting Series for account '{account_name}' (Dispatcharr API) ===")
    log(f"Series dir: {series_dir}")

    mkdir(series_dir)

    series_rows = fetch_series_list_for_account(account_id)
    total_series = len(series_rows)

    if total_series == 0:
        log(f"No series found for account '{account_name}' in DB, skipping series export.")
        return

    log(f"Series to process for '{account_name}': {total_series}")

    total_episodes = 0
    series_processed = 0
    next_progress_pct = 10

    added_eps = 0
    updated_eps = 0
    removed_eps = 0

    expected_files = set()
    proxy_host = normalize_host_for_proxy(api_base)

    for s in series_rows:
        series_id = s.get("series_id")
        if not series_id:
            continue

        category = shorten_component(s.get("category") or "Uncategorized")
        raw_series_title = s.get("series_title") or f"Series-{series_id}"
        series_title = shorten_component(clean_title(raw_series_title))

        # Fetch provider-info via Dispatcharr API (cached)
        info = dispatcharr_provider_info_cached(
            account_name,
            api_base,
            api_token,
            series_id,
        )
        data = normalize_provider_info(info)
        episodes_by_season = data.get("episodes") or {}

        if not episodes_by_season:
            series_processed += 1
            pct = (series_processed * 100) // total_series
            if pct >= next_progress_pct:
                log(
                    f"Series export '{account_name}': {pct}% "
                    f"({series_processed}/{total_series} series processed, "
                    f"{total_episodes} episodes written so far)"
                )
                while next_progress_pct <= pct and next_progress_pct < 100:
                    next_progress_pct += 10
            continue

        series_processed += 1

        for season_key, eps in episodes_by_season.items():
            try:
                season = int(re.sub(r"\D", "", str(season_key)) or "0")
            except Exception:
                season = 0

            season_label = f"Season {season:02d}" if season else "Season 00"

            for ep in eps:
                ep_uuid = ep.get("uuid")
                ep_id = ep.get("id")
                if not ep_uuid and not ep_id:
                    continue

                ep_num = ep.get("episode_number") or ep.get("episode_num") or 0
                try:
                    ep_num = int(ep_num)
                except Exception:
                    ep_num = 0

                raw_ep_title = ep.get("title") or ep.get("name") or f"Episode {ep_num}"
                ep_title = shorten_component(clean_title(raw_ep_title))

                code = f"S{season:02d}E{ep_num:02d}" if ep_num else f"S{season:02d}"

                # Prefer Dispatcharr proxy via UUID
                if ep_uuid:
                    url = f"http://{proxy_host}/proxy/vod/episode/{ep_uuid}"
                else:
                    # Fallback to XC-like URL shape if needed (no real creds here)
                    ext = ep.get("container_extension") or "mp4"
                    url = f"http://{proxy_host}/series/UNKNOWN_USERNAME/UNKNOWN_PASSWORD/{ep_id}.{ext}"

                folder = series_dir / category / series_title / season_label
                filename_base = shorten_component(f"{code} - {ep_title}")
                strm_file = folder / f"{filename_base}.strm"

                expected_files.add(strm_file)

                existed_before = strm_file.exists()
                write_strm(strm_file, url)
                total_episodes += 1
                if existed_before:
                    updated_eps += 1
                else:
                    added_eps += 1

        pct = (series_processed * 100) // total_series
        if pct >= next_progress_pct:
            log(
                f"Series export '{account_name}': {pct}% "
                f"({series_processed}/{total_series} series processed, "
                f"{total_episodes} episodes written so far)"
            )
            while next_progress_pct <= pct and next_progress_pct < 100:
                next_progress_pct += 10

    if DELETE_OLD and series_dir.exists():
        for existing in series_dir.glob("**/*.strm"):
            if existing not in expected_files:
                existing.unlink()
                removed_eps += 1
        log(f"Series cleanup for '{account_name}': removed {removed_eps} stale .strm files.")

        dirs = [p for p in series_dir.glob("**/*") if p.is_dir()]
        for d in sorted(dirs, key=lambda p: len(p.as_posix()), reverse=True):
            try:
                d.rmdir()
            except OSError:
                pass

    active_eps = len(expected_files)
    log(
        f"Series export summary for '{account_name}': "
        f"{added_eps} added, {updated_eps} updated, {removed_eps} removed, {active_eps} active."
    )


# ------------------------------------------------------------
# MAIN
# ------------------------------------------------------------
if __name__ == "__main__":
    log("=== Dispatcharr -> Emby VOD Export (PostgreSQL + Dispatcharr API, multi-account) started ===")
    try:
        accounts = get_xc_accounts()

        # Login once to Dispatcharr API
        api_token = api_login(DISPATCHARR_BASE, DISPATCHARR_API_USER, DISPATCHARR_API_PASS)
        log("Authenticated with Dispatcharr API.")

        if CLEAR_CACHE:
            log("VOD_CLEAR_CACHE=true: clearing cache and output folders before export")

        for acc in accounts:
            account_name = acc["name"]

            if CLEAR_CACHE:
                safe_name = safe_account_name(account_name)

                # Account-specific cache dir
                acc_cache_dir = CACHE_BASE_DIR / safe_name
                if acc_cache_dir.exists():
                    shutil.rmtree(acc_cache_dir, ignore_errors=True)
                    log(f"Cleared cache for account '{account_name}' ({acc_cache_dir})")

                # Account-specific Movies / Series dirs
                movies_dir = Path(
                    VOD_MOVIES_DIR_TEMPLATE.replace("{XC_NAME}", account_name)
                )
                series_dir = Path(
                    VOD_SERIES_DIR_TEMPLATE.replace("{XC_NAME}", account_name)
                )

                if movies_dir.exists():
                    shutil.rmtree(movies_dir, ignore_errors=True)
                    log(f"Removed movies dir for '{account_name}': {movies_dir}")

                if series_dir.exists():
                    shutil.rmtree(series_dir, ignore_errors=True)
                    log(f"Removed series dir for '{account_name}': {series_dir}")

            # Movies: current behaviour
            export_movies_for_account(acc)

            # Series: new API-based behaviour
            export_series_for_account(acc, DISPATCHARR_BASE, api_token)

        log("=== Export finished successfully for all accounts ===")
    except Exception as e:
        log(f"ERROR: {e}")
        raise
