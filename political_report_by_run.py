#!/usr/bin/env python3
"""Report political video counts per run, using the .txt log to identify run boundaries.

Each .txt file contains lines like:
  [2026-04-24 01:32:09] [2/200] @Channel | https://www.youtube.com/shorts/<video_id> (48.4s)

A new run begins whenever the position resets to [1/200].
"""

import json
import re
from collections import defaultdict
from pathlib import Path

# Matches the position counter in each log line.
POS_RE = re.compile(r'\[(\d+)/\d+\]')
# Matches a video ID in a YouTube Shorts URL.
VID_RE = re.compile(r'youtube\.com/shorts/([A-Za-z0-9_\-]+)')


def parse_run_map(txt_file: Path) -> dict[str, set[int]]:
    """Return {video_id: {run_numbers}} for every line in the log file.

    The same video_id can appear in multiple runs (shared pool), so we track
    all runs a video was shown in rather than just the last one.
    """
    video_runs: dict[str, set[int]] = {}
    run = 1
    first_line = True

    with open(txt_file, encoding="utf-8") as f:
        for line in f:
            pos_m = POS_RE.search(line)
            if not pos_m:
                continue

            position = int(pos_m.group(1))

            # A reset to position 1 (after the very first line) means a new run.
            if position == 1 and not first_line:
                run += 1
            first_line = False

            vid_m = VID_RE.search(line)
            if vid_m:
                video_runs.setdefault(vid_m.group(1), set()).add(run)

    return video_runs


def analyze_folder(folder: Path) -> dict | None:
    txt_files = list(folder.glob("*.txt"))
    json_files = list(folder.glob("*.json"))
    if not json_files:
        return None

    # Build video → {runs} map from the txt log (if present).
    video_runs: dict[str, set[int]] = {}
    if txt_files:
        for txt in txt_files:
            for vid, runs in parse_run_map(txt).items():
                video_runs.setdefault(vid, set()).update(runs)

    # Load all JSON entries.
    entries = []
    for json_file in json_files:
        with open(json_file, encoding="utf-8") as f:
            try:
                data = json.load(f)
            except json.JSONDecodeError as e:
                print(f"  WARNING: Could not parse {json_file.name}: {e}")
                continue
        if isinstance(data, list):
            entries.extend(data)

    if not entries:
        return None

    # Group entries by run — a video shown in multiple runs is counted in each.
    run_totals: dict[int, int] = defaultdict(int)
    run_political: dict[int, int] = defaultdict(int)
    run_political_videos: dict[int, list] = defaultdict(list)
    unmatched_total = 0
    unmatched_political = 0

    for entry in entries:
        vid = entry.get("video_id", "")
        runs = video_runs.get(vid)
        is_pol = bool(entry.get("is_political"))

        if not runs:
            unmatched_total += 1
            if is_pol:
                unmatched_political += 1
            continue

        for run in runs:
            run_totals[run] += 1
            if is_pol:
                run_political[run] += 1
                run_political_videos[run].append({
                    "video_id": vid,
                    "channel": entry.get("channel", "unknown"),
                    "confidence": entry.get("confidence", "unknown"),
                    "reason": entry.get("reason", ""),
                })

    return {
        "json_files": [f.name for f in json_files],
        "txt_files": [f.name for f in txt_files],
        "run_totals": run_totals,
        "run_political": run_political,
        "run_political_videos": run_political_videos,
        "unmatched_total": unmatched_total,
        "unmatched_political": unmatched_political,
    }


def main():
    results_dir = Path(__file__).parent
    folders = sorted([f for f in results_dir.iterdir() if f.is_dir() and not f.name.startswith(".")])

    if not folders:
        print("No subfolders found.")
        return

    print("=" * 70)
    print("POLITICAL VIDEO ANALYSIS — BY RUN")
    print("=" * 70)

    summary_rows = []  # (folder_name, run, total, political, pct)

    for folder in folders:
        result = analyze_folder(folder)
        if result is None:
            continue

        runs = sorted(result["run_totals"].keys())
        folder_total = sum(result["run_totals"].values()) + result["unmatched_total"]
        folder_political = sum(result["run_political"].values()) + result["unmatched_political"]

        print(f"\nFolder: {folder.name}")
        print(f"  JSON: {', '.join(result['json_files'])}")
        print(f"  Log : {', '.join(result['txt_files']) if result['txt_files'] else '(none)'}")

        for run in runs:
            total = result["run_totals"][run]
            political = result["run_political"][run]
            pct = political / total * 100 if total > 0 else 0.0
            print(f"\n  Run {run}:  {political}/{total} political ({pct:.1f}%)")
            for v in result["run_political_videos"][run]:
                print(f"    - {v['video_id']} | {v['channel']} | {v['confidence']}")
                if v["reason"]:
                    print(f"      {v['reason'][:120]}")
            summary_rows.append((folder.name, run, total, political, pct))

        if result["unmatched_total"]:
            u_total = result["unmatched_total"]
            u_pol = result["unmatched_political"]
            u_pct = u_pol / u_total * 100 if u_total > 0 else 0.0
            print(f"\n  (unmatched): {u_pol}/{u_total} political ({u_pct:.1f}%)")

        folder_pct = folder_political / folder_total * 100 if folder_total > 0 else 0.0
        print(f"\n  Folder total: {folder_political}/{folder_total} political ({folder_pct:.1f}%)")

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY BY RUN")
    print("=" * 70)
    print(f"{'Folder':<35} {'Run':>4} {'Total':>6} {'Political':>10} {'%':>7}")
    print("-" * 70)
    grand_total = grand_political = 0
    prev_folder = None
    for folder_name, run, total, political, pct in summary_rows:
        if prev_folder and prev_folder != folder_name:
            print()
        print(f"{folder_name:<35} {run:>4} {total:>6} {political:>10} {pct:>6.1f}%")
        grand_total += total
        grand_political += political
        prev_folder = folder_name
    print("-" * 70)
    grand_pct = grand_political / grand_total * 100 if grand_total > 0 else 0.0
    print(f"{'TOTAL':<35} {'':>4} {grand_total:>6} {grand_political:>10} {grand_pct:>6.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    main()
