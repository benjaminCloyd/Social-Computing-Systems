#!/usr/bin/env python3
"""
Human validation of Ollama political leaning classifications.

Presents videos one at a time, records your label, then computes
agreement statistics (accuracy + Cohen's kappa with 95% CI) as you go.

Progress is saved to label_validation_progress.json so you can quit and resume.
"""

import json
import math
import os
import random
import subprocess
import sys
import webbrowser
from collections import Counter
from pathlib import Path

RESULTS_FILE = Path(__file__).parent / "political_leaning_results.json"
PROGRESS_FILE = Path(__file__).parent / "label_validation_progress.json"

LABELS = {"l": "left", "c": "center", "r": "right"}
LABEL_HINT = "[l]eft  [c]enter  [r]ight  [s]kip  [q]uit"

# Target ~120 samples for a kappa CI width of ±0.09 (95%)
TARGET = 120


def load_data():
    with open(RESULTS_FILE) as f:
        return json.load(f)


def load_progress():
    if PROGRESS_FILE.exists():
        with open(PROGRESS_FILE) as f:
            return json.load(f)
    return {"labels": {}}  # {video_id: {"ai": ..., "human": ...}}


def save_progress(progress):
    with open(PROGRESS_FILE, "w") as f:
        json.dump(progress, f, indent=2)


def stratified_sample(data, progress, n=TARGET):
    """Return up to n items not yet labeled, balanced across AI leanings."""
    labeled_ids = set(progress["labels"].keys())
    unlabeled = [d for d in data if d["video_id"] not in labeled_ids]

    by_leaning = {"left": [], "center": [], "right": []}
    for item in unlabeled:
        by_leaning[item["leaning"]].append(item)
    for v in by_leaning.values():
        random.shuffle(v)

    # Round-robin across leanings so the queue is balanced
    queue = []
    per_group = math.ceil(n / 3)
    for leaning in ("left", "center", "right"):
        queue.extend(by_leaning[leaning][:per_group])
    random.shuffle(queue)
    return queue[:n]


# ── Statistics ───────────────────────────────────────────────────────────────

def cohen_kappa(ai_labels, human_labels, categories=("left", "center", "right")):
    n = len(ai_labels)
    if n == 0:
        return None, None, None

    cat_idx = {c: i for i, c in enumerate(categories)}
    k = len(categories)
    matrix = [[0] * k for _ in range(k)]
    for ai, hu in zip(ai_labels, human_labels):
        if ai in cat_idx and hu in cat_idx:
            matrix[cat_idx[ai]][cat_idx[hu]] += 1

    p_o = sum(matrix[i][i] for i in range(k)) / n  # observed agreement

    row_sums = [sum(matrix[i]) for i in range(k)]
    col_sums = [sum(matrix[i][j] for i in range(k)) for j in range(k)]
    p_e = sum((row_sums[i] / n) * (col_sums[i] / n) for i in range(k))

    if p_e == 1.0:
        kappa = 1.0
    else:
        kappa = (p_o - p_e) / (1 - p_e)

    # Fleiss (1971) asymptotic SE for kappa
    # SE² = (p_o(1-p_o)) / (n * (1-p_e)²)  [simplified]
    se = math.sqrt(p_o * (1 - p_o) / (n * (1 - p_e) ** 2)) if n > 1 else 0
    ci_lo = kappa - 1.96 * se
    ci_hi = kappa + 1.96 * se

    return kappa, ci_lo, ci_hi


def kappa_interpretation(k):
    if k is None:
        return "n/a"
    if k < 0:
        return "worse than chance"
    if k < 0.20:
        return "slight"
    if k < 0.40:
        return "fair"
    if k < 0.60:
        return "moderate"
    if k < 0.80:
        return "substantial"
    return "almost perfect"


def print_stats(progress):
    entries = list(progress["labels"].values())
    n = len(entries)
    if n == 0:
        print("  No labels yet.")
        return

    ai = [e["ai"] for e in entries]
    hu = [e["human"] for e in entries]

    agree = sum(a == h for a, h in zip(ai, hu))
    acc = agree / n
    kappa, ci_lo, ci_hi = cohen_kappa(ai, hu)

    print(f"\n  Labeled: {n} / {TARGET}  |  Agreement: {agree}/{n} ({acc:.1%})")
    if kappa is not None:
        interp = kappa_interpretation(kappa)
        print(f"  Cohen's κ = {kappa:.3f}  95% CI [{ci_lo:.3f}, {ci_hi:.3f}]  ({interp})")

    # Per-class breakdown
    cats = ("left", "center", "right")
    print(f"\n  {'Leaning':<10}  AI→  {'left':>5} {'center':>7} {'right':>6}")
    cat_idx = {c: i for i, c in enumerate(cats)}
    k = 3
    matrix = [[0] * k for _ in range(k)]
    for a, h in zip(ai, hu):
        if a in cat_idx and h in cat_idx:
            matrix[cat_idx[a]][cat_idx[h]] += 1

    print("  " + "-" * 38)
    for row_label, row in zip(("left (you)", "center (you)", "right (you)"), matrix):
        print(f"  {row_label:<14} {row[0]:>5} {row[1]:>7} {row[2]:>6}")

    if n >= TARGET:
        print(f"\n  ✓ Reached target of {TARGET} labels — results are statistically robust.")
    else:
        remaining = TARGET - n
        print(f"\n  {remaining} more labels needed to reach the target of {TARGET}.")


# ── Display ───────────────────────────────────────────────────────────────────

def clear():
    os.system("clear" if sys.platform != "win32" else "cls")


def show_item(item, idx, total, progress):
    clear()
    n_done = len(progress["labels"])

    print("=" * 70)
    print(f"  Political Leaning Validation  |  Item {idx}/{total}  |  Labeled: {n_done}")
    print("=" * 70)
    print(f"  Channel : {item['channel']}")
    print(f"  Folder  : {item['folder']}")
    print(f"  URL     : {item['url']}")
    print()
    print("  TRANSCRIPT SNIPPET:")
    snippet = item.get("transcript_snippet", "")
    # Word-wrap at 66 chars
    words = snippet.split()
    line, lines = [], []
    for w in words:
        if sum(len(x) + 1 for x in line) + len(w) > 66:
            lines.append(" ".join(line))
            line = [w]
        else:
            line.append(w)
    if line:
        lines.append(" ".join(line))
    for l in lines:
        print(f"  {l}")
    print()
    print(f"  AI LABEL  : {item['leaning'].upper()}")
    print(f"  AI REASON : {item.get('reason', '')[:200]}")
    print()


def prompt_label(item):
    print(f"  {LABEL_HINT}")
    print("  [o] open URL in browser")
    while True:
        raw = input("  Your label: ").strip().lower()
        if raw == "o":
            webbrowser.open(item["url"])
            continue
        if raw == "q":
            return "quit"
        if raw == "s":
            return "skip"
        if raw in LABELS:
            return LABELS[raw]
        print("  Please enter l, c, r, s, o, or q.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    random.seed(42)  # reproducible queue order within a session
    data = load_data()
    progress = load_progress()

    n_done = len(progress["labels"])
    print(f"Loaded {len(data)} AI-labeled items. {n_done} already labeled by you.")

    queue = stratified_sample(data, progress, TARGET - n_done + 20)  # slight buffer
    if not queue:
        print("Nothing left to label! Run stats below.")
        print_stats(progress)
        return

    print(f"Queue has {len(queue)} items. Press Enter to start (q to quit at any prompt).")
    input()

    for idx, item in enumerate(queue, start=1):
        show_item(item, idx, len(queue), progress)
        label = prompt_label(item)

        if label == "quit":
            break
        if label == "skip":
            continue

        progress["labels"][item["video_id"]] = {
            "ai": item["leaning"],
            "human": label,
            "channel": item["channel"],
            "folder": item["folder"],
        }
        save_progress(progress)

        print(f"\n  Saved: AI={item['leaning']}  You={label}")
        print_stats(progress)
        input("\n  Press Enter for next item...")

        if len(progress["labels"]) >= TARGET:
            clear()
            print(f"\n  ✓ Reached {TARGET} labels! Final statistics:\n")
            print_stats(progress)
            break

    else:
        clear()
        print("\n  Queue exhausted. Final statistics:\n")
        print_stats(progress)

    save_progress(progress)
    print(f"\n  Progress saved to {PROGRESS_FILE.name}")


if __name__ == "__main__":
    main()
