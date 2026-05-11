#!/usr/bin/env python3
"""
Human validation of Ollama political classifications.

Two modes:
  1. Leaning validation  — left / center / right labels from political_leaning_results.json
  2. Binary validation   — political / apolitical from control + treatment JSONs

Progress for each mode is saved separately so you can quit and resume.
Agreement statistics (accuracy + Cohen's kappa with 95% CI) are shown as you go.
"""

import json
import math
import os
import random
import sys
import webbrowser
from pathlib import Path

BASE = Path(__file__).parent

RESULTS_FILE     = BASE / "political_leaning_results.json"
LEANING_PROGRESS = BASE / "label_validation_progress.json"
BINARY_PROGRESS  = BASE / "binary_validation_progress.json"

CONTROL_DIR   = BASE / "control"
TREATMENT_DIR = BASE / "treatment"

TARGET_LEANING = 120
TARGET_BINARY  = 120


# ── Data loading ──────────────────────────────────────────────────────────────

def load_leaning_data():
    with open(RESULTS_FILE) as f:
        return json.load(f)


def load_binary_data():
    """Load all items from control + treatment JSONs, tagging source."""
    items = []
    for folder, dirpath in (("control", CONTROL_DIR), ("treatment", TREATMENT_DIR)):
        for path in sorted(dirpath.glob("*.json")):
            with open(path) as f:
                chunk = json.load(f)
            for item in chunk:
                item = dict(item)
                item["folder"] = folder
                item["source_file"] = path.name
                items.append(item)
    return items


def load_progress(path):
    if path.exists():
        with open(path) as f:
            return json.load(f)
    return {"labels": {}}


def save_progress(progress, path):
    with open(path, "w") as f:
        json.dump(progress, f, indent=2)


# ── Sampling ──────────────────────────────────────────────────────────────────

def stratified_leaning_sample(data, progress, n):
    """Balanced sample across left/center/right not yet labeled."""
    labeled_ids = set(progress["labels"].keys())
    unlabeled = [d for d in data if d["video_id"] not in labeled_ids]

    by_leaning = {"left": [], "center": [], "right": []}
    for item in unlabeled:
        by_leaning[item["leaning"]].append(item)
    for v in by_leaning.values():
        random.shuffle(v)

    queue = []
    per_group = math.ceil(n / 3)
    for leaning in ("left", "center", "right"):
        queue.extend(by_leaning[leaning][:per_group])
    random.shuffle(queue)
    return queue[:n]


def stratified_binary_sample(data, progress, n):
    """Balanced sample across political/apolitical not yet labeled."""
    labeled_ids = set(progress["labels"].keys())
    unlabeled = [d for d in data if d["video_id"] not in labeled_ids]

    political  = [d for d in unlabeled if d.get("is_political") is True]
    apolitical = [d for d in unlabeled if d.get("is_political") is False]
    random.shuffle(political)
    random.shuffle(apolitical)

    per_group = math.ceil(n / 2)
    queue = political[:per_group] + apolitical[:per_group]
    random.shuffle(queue)
    return queue[:n]


# ── Statistics ────────────────────────────────────────────────────────────────

def cohen_kappa(ai_labels, human_labels, categories):
    n = len(ai_labels)
    if n == 0:
        return None, None, None

    cat_idx = {c: i for i, c in enumerate(categories)}
    k = len(categories)
    matrix = [[0] * k for _ in range(k)]
    for ai, hu in zip(ai_labels, human_labels):
        if ai in cat_idx and hu in cat_idx:
            matrix[cat_idx[ai]][cat_idx[hu]] += 1

    p_o = sum(matrix[i][i] for i in range(k)) / n
    row_sums = [sum(matrix[i]) for i in range(k)]
    col_sums = [sum(matrix[i][j] for i in range(k)) for j in range(k)]
    p_e = sum((row_sums[i] / n) * (col_sums[i] / n) for i in range(k))

    kappa = 1.0 if p_e == 1.0 else (p_o - p_e) / (1 - p_e)
    se = math.sqrt(p_o * (1 - p_o) / (n * (1 - p_e) ** 2)) if n > 1 else 0
    return kappa, kappa - 1.96 * se, kappa + 1.96 * se


def kappa_interpretation(k):
    if k is None:  return "n/a"
    if k < 0:      return "worse than chance"
    if k < 0.20:   return "slight"
    if k < 0.40:   return "fair"
    if k < 0.60:   return "moderate"
    if k < 0.80:   return "substantial"
    return "almost perfect"


def print_leaning_stats(progress):
    entries = list(progress["labels"].values())
    n = len(entries)
    if n == 0:
        print("  No labels yet.")
        return

    ai = [e["ai"] for e in entries]
    hu = [e["human"] for e in entries]
    agree = sum(a == h for a, h in zip(ai, hu))
    kappa, ci_lo, ci_hi = cohen_kappa(ai, hu, ("left", "center", "right"))

    print(f"\n  Labeled: {n} / {TARGET_LEANING}  |  Agreement: {agree}/{n} ({agree/n:.1%})")
    if kappa is not None:
        print(f"  Cohen's κ = {kappa:.3f}  95% CI [{ci_lo:.3f}, {ci_hi:.3f}]  ({kappa_interpretation(kappa)})")

    cats = ("left", "center", "right")
    cat_idx = {c: i for i, c in enumerate(cats)}
    matrix = [[0] * 3 for _ in range(3)]
    for a, h in zip(ai, hu):
        if a in cat_idx and h in cat_idx:
            matrix[cat_idx[a]][cat_idx[h]] += 1

    print(f"\n  {'You \\ AI':<15} {'left':>5} {'center':>7} {'right':>6}")
    print("  " + "-" * 38)
    for row_label, row in zip(("left (you)", "center (you)", "right (you)"), matrix):
        print(f"  {row_label:<15} {row[0]:>5} {row[1]:>7} {row[2]:>6}")

    remaining = TARGET_LEANING - n
    if remaining <= 0:
        print(f"\n  ✓ Reached target of {TARGET_LEANING} labels.")
    else:
        print(f"\n  {remaining} more labels needed to reach target of {TARGET_LEANING}.")


def print_binary_stats(progress):
    entries = list(progress["labels"].values())
    n = len(entries)
    if n == 0:
        print("  No labels yet.")
        return

    ai = [e["ai"] for e in entries]
    hu = [e["human"] for e in entries]
    agree = sum(a == h for a, h in zip(ai, hu))
    kappa, ci_lo, ci_hi = cohen_kappa(ai, hu, ("political", "apolitical"))

    print(f"\n  Labeled: {n} / {TARGET_BINARY}  |  Agreement: {agree}/{n} ({agree/n:.1%})")
    if kappa is not None:
        print(f"  Cohen's κ = {kappa:.3f}  95% CI [{ci_lo:.3f}, {ci_hi:.3f}]  ({kappa_interpretation(kappa)})")

    cats = ("political", "apolitical")
    cat_idx = {c: i for i, c in enumerate(cats)}
    matrix = [[0] * 2 for _ in range(2)]
    for a, h in zip(ai, hu):
        if a in cat_idx and h in cat_idx:
            matrix[cat_idx[a]][cat_idx[h]] += 1

    print(f"\n  {'You \\ AI':<20} {'political':>10} {'apolitical':>11}")
    print("  " + "-" * 44)
    for row_label, row in zip(("political (you)", "apolitical (you)"), matrix):
        print(f"  {row_label:<20} {row[0]:>10} {row[1]:>11}")

    remaining = TARGET_BINARY - n
    if remaining <= 0:
        print(f"\n  ✓ Reached target of {TARGET_BINARY} labels.")
    else:
        print(f"\n  {remaining} more labels needed to reach target of {TARGET_BINARY}.")


# ── Display ───────────────────────────────────────────────────────────────────

def clear():
    os.system("clear" if sys.platform != "win32" else "cls")


def wrap(text, width=66):
    words = text.split()
    line, lines = [], []
    for w in words:
        if sum(len(x) + 1 for x in line) + len(w) > width:
            lines.append(" ".join(line))
            line = [w]
        else:
            line.append(w)
    if line:
        lines.append(" ".join(line))
    return lines


def show_leaning_item(item, idx, total, progress):
    clear()
    print("=" * 70)
    print(f"  Leaning Validation  |  Item {idx}/{total}  |  Labeled: {len(progress['labels'])}")
    print("=" * 70)
    print(f"  Channel   : {item['channel']}")
    print(f"  Folder    : {item['folder']}")
    print(f"  URL       : {item['url']}")
    print()
    print("  TRANSCRIPT SNIPPET:")
    for line in wrap(item.get("transcript_snippet", "")):
        print(f"  {line}")
    print()
    print(f"  AI LABEL  : {item['leaning'].upper()}")
    print(f"  AI REASON : {item.get('reason', '')[:200]}")
    print()


def show_binary_item(item, idx, total, progress):
    clear()
    ai_label = "POLITICAL" if item.get("is_political") else "APOLITICAL"
    print("=" * 70)
    print(f"  Binary Validation  |  Item {idx}/{total}  |  Labeled: {len(progress['labels'])}")
    print("=" * 70)
    print(f"  Channel   : {item['channel']}")
    print(f"  Source    : {item['folder']} / {item['source_file']}")
    print(f"  URL       : {item['url']}")
    print()
    print("  TRANSCRIPT (first 500 chars):")
    for line in wrap(item.get("transcript", "")[:500]):
        print(f"  {line}")
    print()
    print(f"  AI LABEL  : {ai_label}")
    print(f"  AI CONF.  : {item.get('confidence', 'n/a')}")
    print(f"  AI REASON : {item.get('reason', '')[:200]}")
    print()


# ── Prompt helpers ────────────────────────────────────────────────────────────

def prompt_leaning(item):
    labels = {"l": "left", "c": "center", "r": "right"}
    print("  [l]eft  [c]enter  [r]ight  [s]kip  [q]uit  [o]pen URL")
    while True:
        raw = input("  Your label: ").strip().lower()
        if raw == "o":
            webbrowser.open(item["url"])
        elif raw == "q":
            return "quit"
        elif raw == "s":
            return "skip"
        elif raw in labels:
            return labels[raw]
        else:
            print("  Please enter l, c, r, s, o, or q.")


def prompt_binary(item):
    print("  [p]olitical  [a]political  [s]kip  [q]uit  [o]pen URL")
    while True:
        raw = input("  Your label: ").strip().lower()
        if raw == "o":
            webbrowser.open(item["url"])
        elif raw == "q":
            return "quit"
        elif raw == "s":
            return "skip"
        elif raw == "p":
            return "political"
        elif raw == "a":
            return "apolitical"
        else:
            print("  Please enter p, a, s, o, or q.")


# ── Mode runners ──────────────────────────────────────────────────────────────

def run_leaning_mode():
    data = load_leaning_data()
    progress = load_progress(LEANING_PROGRESS)
    n_done = len(progress["labels"])
    print(f"\nLoaded {len(data)} AI-labeled items. {n_done} already labeled by you.")

    queue = stratified_leaning_sample(data, progress, max(0, TARGET_LEANING - n_done) + 20)
    if not queue:
        print("Nothing left to label!")
        print_leaning_stats(progress)
        return

    print(f"Queue: {len(queue)} items. Press Enter to start...")
    input()

    for idx, item in enumerate(queue, start=1):
        show_leaning_item(item, idx, len(queue), progress)
        label = prompt_leaning(item)

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
        save_progress(progress, LEANING_PROGRESS)
        print(f"\n  Saved: AI={item['leaning']}  You={label}")
        print_leaning_stats(progress)
        input("\n  Press Enter for next item...")

        if len(progress["labels"]) >= TARGET_LEANING:
            clear()
            print(f"\n  ✓ Reached {TARGET_LEANING} labels! Final statistics:\n")
            print_leaning_stats(progress)
            break
    else:
        clear()
        print("\n  Queue exhausted. Statistics:\n")
        print_leaning_stats(progress)

    save_progress(progress, LEANING_PROGRESS)
    print(f"\n  Progress saved to {LEANING_PROGRESS.name}")


def run_binary_mode():
    data = load_binary_data()
    progress = load_progress(BINARY_PROGRESS)
    n_done = len(progress["labels"])
    n_political  = sum(1 for d in data if d.get("is_political") is True)
    n_apolitical = sum(1 for d in data if d.get("is_political") is False)
    print(f"\nLoaded {len(data)} items ({n_political} political, {n_apolitical} apolitical). {n_done} already labeled by you.")

    queue = stratified_binary_sample(data, progress, max(0, TARGET_BINARY - n_done) + 20)
    if not queue:
        print("Nothing left to label!")
        print_binary_stats(progress)
        return

    print(f"Queue: {len(queue)} items (balanced political/apolitical). Press Enter to start...")
    input()

    for idx, item in enumerate(queue, start=1):
        show_binary_item(item, idx, len(queue), progress)
        label = prompt_binary(item)

        if label == "quit":
            break
        if label == "skip":
            continue

        ai_label = "political" if item.get("is_political") else "apolitical"
        progress["labels"][item["video_id"]] = {
            "ai": ai_label,
            "human": label,
            "channel": item["channel"],
            "folder": item["folder"],
            "source_file": item["source_file"],
        }
        save_progress(progress, BINARY_PROGRESS)
        print(f"\n  Saved: AI={ai_label}  You={label}")
        print_binary_stats(progress)
        input("\n  Press Enter for next item...")

        if len(progress["labels"]) >= TARGET_BINARY:
            clear()
            print(f"\n  ✓ Reached {TARGET_BINARY} labels! Final statistics:\n")
            print_binary_stats(progress)
            break
    else:
        clear()
        print("\n  Queue exhausted. Statistics:\n")
        print_binary_stats(progress)

    save_progress(progress, BINARY_PROGRESS)
    print(f"\n  Progress saved to {BINARY_PROGRESS.name}")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    random.seed(42)

    print("=" * 70)
    print("  Label Validation Tool")
    print("=" * 70)
    print()
    print("  [1] Leaning validation   — left / center / right")
    print("      source: political_leaning_results.json")
    print()
    print("  [2] Binary validation    — political / apolitical")
    print("      source: control + treatment JSONs")
    print()
    print("  [q] Quit")
    print()

    while True:
        choice = input("  Mode: ").strip().lower()
        if choice == "1":
            run_leaning_mode()
            break
        elif choice == "2":
            run_binary_mode()
            break
        elif choice == "q":
            break
        else:
            print("  Please enter 1, 2, or q.")


if __name__ == "__main__":
    main()
