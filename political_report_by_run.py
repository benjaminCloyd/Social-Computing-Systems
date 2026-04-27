#!/usr/bin/env python3
"""Report political video counts per account per run.

Each account is a paired (JSON + TXT) file with a matching stem, e.g.:
  treatment/18mtreatment.json  <->  treatment/18mtreatment.txt

A new run begins whenever the position counter in the TXT resets to [1/...].
"""

import json
import re
from collections import defaultdict
from pathlib import Path

POS_RE = re.compile(r'\[(\d+)/\d+\]')
VID_RE = re.compile(r'youtube\.com/shorts/([A-Za-z0-9_\-]+)')
ACCOUNT_RE = re.compile(r'^(\d+)([mf])(treatment|control)$', re.IGNORECASE)

SCRIPT_DIR = Path(__file__).parent
FOLDERS = [SCRIPT_DIR / "treatment", SCRIPT_DIR / "control"]


def parse_account_label(stem: str) -> str:
    m = ACCOUNT_RE.match(stem)
    if m:
        age, gender, group = m.group(1), m.group(2).upper(), m.group(3).capitalize()
        return f"{age}{gender} {group}"
    return stem


def parse_run_map(txt_file: Path) -> dict[str, set[int]]:
    """Return {video_id: {run_numbers}} from a single account's TXT log."""
    video_runs: dict[str, set[int]] = {}
    run = 1
    first_line = True

    with open(txt_file, encoding="utf-8") as f:
        for line in f:
            pos_m = POS_RE.search(line)
            if not pos_m:
                continue
            position = int(pos_m.group(1))
            if position == 1 and not first_line:
                run += 1
            first_line = False
            vid_m = VID_RE.search(line)
            if vid_m:
                video_runs.setdefault(vid_m.group(1), set()).add(run)

    return video_runs


def analyze_account(json_file: Path, txt_file: Path | None) -> dict:
    with open(json_file, encoding="utf-8") as f:
        try:
            entries = json.load(f)
        except json.JSONDecodeError as e:
            return {"error": str(e)}

    if not isinstance(entries, list):
        return {"error": "JSON root is not a list"}

    video_runs: dict[str, set[int]] = {}
    if txt_file and txt_file.exists():
        video_runs = parse_run_map(txt_file)

    run_totals: dict[int, int] = defaultdict(int)
    run_political: dict[int, int] = defaultdict(int)
    run_political_videos: dict[int, list] = defaultdict(list)
    unmatched_total = 0
    unmatched_political = 0

    for entry in entries:
        vid = entry.get("video_id", "")
        is_pol = bool(entry.get("is_political"))
        runs = video_runs.get(vid)

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
        "run_totals": run_totals,
        "run_political": run_political,
        "run_political_videos": run_political_videos,
        "unmatched_total": unmatched_total,
        "unmatched_political": unmatched_political,
    }


def main():
    print("=" * 70)
    print("POLITICAL VIDEO ANALYSIS — BY ACCOUNT & RUN")
    print("=" * 70)

    summary_rows = []

    for folder in FOLDERS:
        if not folder.exists():
            continue

        json_files = sorted(folder.glob("*.json"))
        if not json_files:
            continue

        print(f"\n{'─' * 70}")
        print(f"  {folder.name.upper()}")
        print(f"{'─' * 70}")

        for json_file in json_files:
            txt_file = json_file.with_suffix(".txt")
            label = parse_account_label(json_file.stem)

            result = analyze_account(json_file, txt_file if txt_file.exists() else None)

            if "error" in result:
                print(f"\n  [{label}] ERROR: {result['error']}")
                continue

            runs = sorted(result["run_totals"].keys())
            has_runs = bool(runs)

            print(f"\n  Account: {label}  ({json_file.name})")
            if not txt_file.exists():
                print(f"    WARNING: no matching log file ({txt_file.name})")

            if has_runs:
                for run in runs:
                    total = result["run_totals"][run]
                    political = result["run_political"][run]
                    pct = political / total * 100 if total else 0.0
                    print(f"\n    Run {run}:  {political}/{total} political ({pct:.1f}%)")
                    for v in result["run_political_videos"][run]:
                        print(f"      - {v['video_id']} | {v['channel']} | {v['confidence']}")
                        if v["reason"]:
                            print(f"        {v['reason'][:120]}")
                    summary_rows.append((label, run, total, political, pct))

            if result["unmatched_total"]:
                u = result["unmatched_total"]
                up = result["unmatched_political"]
                upct = up / u * 100 if u else 0.0
                print(f"\n    (no log match): {up}/{u} political ({upct:.1f}%)")
                summary_rows.append((label, "?", u, up, upct))

            all_total = sum(result["run_totals"].values()) + result["unmatched_total"]
            all_pol = sum(result["run_political"].values()) + result["unmatched_political"]
            all_pct = all_pol / all_total * 100 if all_total else 0.0
            print(f"\n    Account total: {all_pol}/{all_total} political ({all_pct:.1f}%)")

    # Summary table
    print("\n" + "=" * 70)
    print("SUMMARY BY ACCOUNT & RUN")
    print("=" * 70)
    print(f"{'Account':<20} {'Run':>4} {'Total':>6} {'Political':>10} {'%':>7}")
    print("-" * 70)
    grand_total = grand_political = 0
    prev_account = None
    for account, run, total, political, pct in summary_rows:
        if prev_account and prev_account != account:
            print()
        run_str = str(run) if isinstance(run, int) else run
        print(f"{account:<20} {run_str:>4} {total:>6} {political:>10} {pct:>6.1f}%")
        if isinstance(total, int):
            grand_total += total
            grand_political += political
        prev_account = account
    print("-" * 70)
    grand_pct = grand_political / grand_total * 100 if grand_total else 0.0
    print(f"{'TOTAL':<20} {'':>4} {grand_total:>6} {grand_political:>10} {grand_pct:>6.1f}%")
    print("=" * 70)


if __name__ == "__main__":
    main()
