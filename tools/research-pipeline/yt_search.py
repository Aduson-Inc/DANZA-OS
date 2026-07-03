"""
YouTube URL collector for the DANZA research pipeline.
5-tier search: starts narrow (7 days), expands until 7-20 results found.
Deduplicates across all tiers. Returns 7-20 results max.

Tiers:
  1. Last 7 days (breaking/trending)
  2. Last 30 days (recent)
  3. Last 90 days (quarter)
  4. Last 12 months (annual best)
  5. All time (classics)
"""

import json
import sys
from datetime import datetime, timedelta

import yt_dlp

MIN_RESULTS = 7
MAX_RESULTS = 20

TIERS = [
    {"label": "7 days", "days": 7},
    {"label": "30 days", "days": 30},
    {"label": "90 days", "days": 90},
    {"label": "12 months", "days": 365},
    {"label": "all time", "days": None},
]


def search_youtube(query, max_results=MAX_RESULTS):
    all_results = {}
    for tier in TIERS:
        tier_results = _search_tier(query, days=tier["days"])
        added = 0
        for r in tier_results:
            if r["url"] not in all_results:
                all_results[r["url"]] = r
                added += 1
            if len(all_results) >= max_results:
                break
        print(f"// Tier '{tier['label']}': found {len(tier_results)}, added {added} new, total {len(all_results)}", file=sys.stderr)
        if len(all_results) >= max_results:
            break
    return _finalize(all_results, max_results)


def _search_tier(query, days=None, fetch_count=40):
    if days is not None:
        cutoff = datetime.now() - timedelta(days=days)
        cutoff_str = cutoff.strftime("%Y%m%d")
    else:
        cutoff_str = None

    ydl_opts = {"quiet": True, "no_warnings": True, "extract_flat": False, "skip_download": True}
    raw = []
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(f"ytsearch{fetch_count}:{query}", download=False)
            if not info or "entries" not in info:
                return []
            for entry in info["entries"]:
                if entry is None:
                    continue
                upload_date = entry.get("upload_date", "")
                if cutoff_str and upload_date and upload_date < cutoff_str:
                    continue
                raw_views = entry.get("view_count") or 0
                dur_secs = entry.get("duration") or 0
                if dur_secs < 120:
                    continue
                mins, secs = divmod(int(dur_secs), 60)
                hrs, mins = divmod(mins, 60)
                duration = f"{hrs}:{mins:02d}:{secs:02d}" if hrs else f"{mins}:{secs:02d}"
                if raw_views >= 1_000_000:
                    view_str = f"{raw_views / 1_000_000:.1f}M"
                elif raw_views >= 1_000:
                    view_str = f"{raw_views / 1_000:.1f}K"
                else:
                    view_str = str(raw_views)
                date_str = ""
                if upload_date and len(upload_date) == 8:
                    date_str = f"{upload_date[:4]}-{upload_date[4:6]}-{upload_date[6:]}"
                raw.append({
                    "title": entry.get("title", "Unknown"),
                    "channel": entry.get("channel") or entry.get("uploader", "Unknown"),
                    "views": view_str, "views_raw": raw_views,
                    "duration": duration, "date": date_str,
                    "url": entry.get("webpage_url") or f"https://youtube.com/watch?v={entry.get('id', '')}",
                })
    except Exception as e:
        print(f"Search error: {e}", file=sys.stderr)
        return []
    raw.sort(key=lambda x: x["views_raw"], reverse=True)
    return raw


def _finalize(results_dict, max_results):
    combined = sorted(results_dict.values(), key=lambda x: x["views_raw"], reverse=True)[:max_results]
    return [{"title": r["title"], "channel": r["channel"], "views": r["views"],
             "duration": r["duration"], "date": r["date"], "url": r["url"]} for r in combined]


if __name__ == "__main__":
    query = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else ""
    if not query:
        print("Usage: python yt_search.py <search query>")
        print(f"Returns {MIN_RESULTS}-{MAX_RESULTS} results across 5 tiers: 7d > 30d > 90d > 1yr > all time")
        sys.exit(1)
    results = search_youtube(query)
    print(json.dumps(results, indent=2))
    print(f"\n// Final: {len(results)} results (target {MIN_RESULTS}-{MAX_RESULTS})", file=sys.stderr)
