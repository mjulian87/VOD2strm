#!/usr/bin/env python3
import os
from pathlib import Path

# -----------------------------
# CONFIG
# -----------------------------
# XC / account name to inspect (must match the folder name used by VOD2strm)
ACCOUNT_NAME = "Strong 8K"

# These should match your VOD2strm_vars.sh templates
MOVIES_DIR_TEMPLATE = "/mnt/Share-VOD/{XC_NAME}/Movies"
SERIES_DIR_TEMPLATE = "/mnt/Share-VOD/{XC_NAME}/Series"

# How many unique movies / series to sample
NUM_MOVIES = 10
NUM_SERIES = 10
# -----------------------------


def human_rel(path: Path, base: Path) -> str:
    try:
        return str(path.relative_to(base))
    except ValueError:
        return str(path)


def collect_movie_titles(movies_root: Path, limit: int):
    """
    Collect up to `limit` movie title directories that contain at least one .strm file.
    Returns a list of Paths.
    """
    found = []
    if not movies_root.exists():
        print(f"[WARN] Movies root does not exist: {movies_root}")
        return found

    # movies_root / <Category> / <Title> / files...
    for cat_dir in sorted(p for p in movies_root.iterdir() if p.is_dir()):
        for title_dir in sorted(p for p in cat_dir.iterdir() if p.is_dir()):
            # Does this title dir contain any .strm files?
            strm_files = list(title_dir.glob("*.strm"))
            if strm_files:
                found.append(title_dir)
                if len(found) >= limit:
                    return found
    return found


def collect_series_titles(series_root: Path, limit: int):
    """
    Collect up to `limit` series show directories.
    Returns a list of Paths: series_root/<Category>/<Show>
    """
    found = []
    if not series_root.exists():
        print(f"[WARN] Series root does not exist: {series_root}")
        return found

    # series_root / <Category> / <Show> / ...
    for cat_dir in sorted(p for p in series_root.iterdir() if p.is_dir()):
        for show_dir in sorted(p for p in cat_dir.iterdir() if p.is_dir()):
            # Heuristic: treat as a valid series if there is either tvshow.nfo
            # or at least one Season*/.strm
            tvshow_nfo = show_dir / "tvshow.nfo"
            has_tvshow_nfo = tvshow_nfo.exists()
            has_episode_strm = any(show_dir.glob("Season */*.strm"))

            if has_tvshow_nfo or has_episode_strm:
                found.append(show_dir)
                if len(found) >= limit:
                    return found
    return found


def print_movie_title_info(title_dir: Path, movies_root: Path):
    print(f"\n=== Movie: {human_rel(title_dir, movies_root)} ===")
    # Immediate files in the title dir
    files = sorted(p for p in title_dir.iterdir() if p.is_file())
    if not files:
        print("  (no files found in title directory)")
        return

    for f in files:
        suffix = f.suffix.lower()
        if suffix == ".strm":
            tag = "STRM"
        elif suffix == ".nfo":
            tag = "NFO"
        elif f.name.lower() in ("poster.jpg", "cover.jpg"):
            tag = "POSTER"
        elif f.name.lower() in ("fanart.jpg", "backdrop.jpg"):
            tag = "FANART"
        else:
            tag = "FILE"
        print(f"  [{tag:6}] {f.name}")


def print_series_title_info(show_dir: Path, series_root: Path):
    print(f"\n=== Series: {human_rel(show_dir, series_root)} ===")

    tvshow_nfo = show_dir / "tvshow.nfo"
    poster_jpg = show_dir / "poster.jpg"
    fanart_jpg = show_dir / "fanart.jpg"

    if tvshow_nfo.exists():
        print(f"  [NFO   ] tvshow.nfo")
    else:
        print(f"  [MISS  ] tvshow.nfo")

    if poster_jpg.exists():
        print(f"  [POSTER] poster.jpg")
    else:
        print(f"  [MISS  ] poster.jpg")

    if fanart_jpg.exists():
        print(f"  [FANART] fanart.jpg")
    else:
        print(f"  [MISS  ] fanart.jpg")

    # Look at up to 2 seasons, each with up to 3 episodes
    seasons = sorted(p for p in show_dir.glob("Season *") if p.is_dir())
    if not seasons:
        print("  (no Season directories found)")
        return

    for season_dir in seasons[:2]:
        print(f"  --- {season_dir.name} ---")
        episodes = sorted(p for p in season_dir.glob("*.strm"))
        if not episodes:
            print("    (no .strm episodes found)")
            continue
        for ep_strm in episodes[:3]:
            base = ep_strm.with_suffix("")
            ep_nfo = base.with_suffix(".nfo")
            has_nfo = ep_nfo.exists()
            print(
                f"    [EP] {ep_strm.name}"
                + ("  [NFO]" if has_nfo else "  [no NFO]")
            )


def main():
    movies_dir = Path(MOVIES_DIR_TEMPLATE.replace("{XC_NAME}", ACCOUNT_NAME))
    series_dir = Path(SERIES_DIR_TEMPLATE.replace("{XC_NAME}", ACCOUNT_NAME))

    print(f"Checking VOD2strm output for account: {ACCOUNT_NAME}")
    print(f"Movies root: {movies_dir}")
    print(f"Series root: {series_dir}")

    # Movies
    movie_titles = collect_movie_titles(movies_dir, NUM_MOVIES)
    if not movie_titles:
        print("\nNo movie titles found with .strm files.")
    else:
        print(f"\nFound {len(movie_titles)} movie title(s) to inspect:")
        for d in movie_titles:
            print_movie_title_info(d, movies_dir)

    # Series
    series_titles = collect_series_titles(series_dir, NUM_SERIES)
    if not series_titles:
        print("\nNo series titles found with tvshow.nfo or Season*/.strm files.")
    else:
        print(f"\nFound {len(series_titles)} series title(s) to inspect:")
        for d in series_titles:
            print_series_title_info(d, series_dir)


if __name__ == "__main__":
    main()
