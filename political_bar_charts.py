"""
Stacked bar chart: political video density per 20-video interval, per run.

For each of the 8 participant groups one PNG is saved to bar_charts/.
Each PNG has 3 subplots (one per run). Each subplot has 10 bars (positions
1-20, 21-40, … 181-200) stacked by leaning: blue=left, red=right, purple=center.
"""

import json
import re
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
import numpy as np

BASE_DIR = Path(__file__).parent
LEANING_FILE = BASE_DIR / "political_leaning_results.json"
OUT_DIR = BASE_DIR / "bar charts"
OUT_DIR.mkdir(exist_ok=True)

BIN_SIZE = 20
MAX_POS = 200
BINS = range(1, MAX_POS + 1, BIN_SIZE)          # 1, 21, 41, …, 181
BIN_LABELS = [f"{b}–{b + BIN_SIZE - 1}" for b in BINS]   # "1–20", "21–40", …
N_BINS = len(list(BINS))

COLOR = {"right": "#d62728", "left": "#1f77b4", "center": "#9467bd"}
LEANINGS = ["left", "right", "center"]

POS_RE = re.compile(r"\[(\d+)/\d+\]")
VID_RE = re.compile(r"youtube\.com/shorts/([A-Za-z0-9_\-]+)")

GROUPS = [
    ("18F", "Control",   "control/18fcontrol"),
    ("18M", "Control",   "control/18mcontrol"),
    ("35F", "Control",   "control/35fcontrol"),
    ("35M", "Control",   "control/35mcontrol"),
    ("18F", "Treatment", "treatment/18ftreatment"),
    ("18M", "Treatment", "treatment/18mtreatment"),
    ("35F", "Treatment", "treatment/35ftreatment"),
    ("35M", "Treatment", "treatment/35mtreatment"),
]


def load_leanings() -> dict[str, str]:
    with open(LEANING_FILE) as f:
        data = json.load(f)
    return {e["video_id"]: e["leaning"] for e in data}


def load_political_ids(json_path: Path) -> set[str]:
    with open(json_path) as f:
        data = json.load(f)
    return {v["video_id"] for v in data if v.get("is_political")}


def parse_runs(txt_path: Path, max_runs: int = 3) -> list[list[tuple[int, str]]]:
    runs: list[list[tuple[int, str]]] = []
    current: list[tuple[int, str]] = []
    first = True
    with open(txt_path) as f:
        for line in f:
            pos_m = POS_RE.search(line)
            if not pos_m:
                continue
            pos = int(pos_m.group(1))
            if pos == 1 and not first:
                runs.append(current)
                current = []
                if len(runs) == max_runs:
                    break
            first = False
            vid_m = VID_RE.search(line)
            if vid_m:
                current.append((pos, vid_m.group(1)))
    if current and len(runs) < max_runs:
        runs.append(current)
    return runs


def bin_index(pos: int) -> int:
    return (pos - 1) // BIN_SIZE


def make_chart(age: str, condition: str, stem: str, leanings: dict[str, str]):
    txt_path = BASE_DIR / (stem + ".txt")
    json_path = BASE_DIR / (stem + ".json")

    political_ids = load_political_ids(json_path)
    runs = parse_runs(txt_path, max_runs=3)

    fig, axes = plt.subplots(
        1, 3,
        figsize=(14, 4),
        sharey=False,
        gridspec_kw={"wspace": 0.35},
    )
    fig.suptitle(
        f"{condition} · {age}  —  Political Video Density per 20-Video Interval",
        fontsize=12, fontweight="bold", y=1.03,
    )

    max_y = 0

    for run_idx, (ax, run) in enumerate(zip(axes, runs), start=1):
        counts = {l: np.zeros(N_BINS, dtype=int) for l in LEANINGS}

        for pos, vid in run:
            if vid in political_ids:
                b = bin_index(pos)
                if 0 <= b < N_BINS:
                    leaning = leanings.get(vid, "center")
                    counts[leaning][b] += 1

        x = np.arange(N_BINS)
        bottom = np.zeros(N_BINS, dtype=int)

        for leaning in LEANINGS:
            vals = counts[leaning]
            ax.bar(x, vals, bottom=bottom, color=COLOR[leaning],
                   width=0.7, edgecolor="white", linewidth=0.5)
            bottom += vals

        run_max = int(bottom.max())
        if run_max > max_y:
            max_y = run_max

        ax.set_title(f"Run {run_idx}", fontsize=10)
        ax.set_xticks(x)
        ax.set_xticklabels(BIN_LABELS, rotation=45, ha="right", fontsize=7)
        ax.set_xlabel("Feed position interval", fontsize=8)
        ax.set_ylabel("Political videos", fontsize=8)
        ax.tick_params(labelsize=7)
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
        ax.yaxis.get_major_locator().set_params(integer=True)

    # Pad any unused subplots if a group has < 3 runs
    for ax in axes[len(runs):]:
        ax.set_visible(False)

    # Uniform y scale across the 3 subplots for this group
    for ax in axes[:len(runs)]:
        ax.set_ylim(0, max(max_y + 1, 2))

    # Shared legend
    legend_handles = [
        mpatches.Patch(color=COLOR["left"],   label="Left"),
        mpatches.Patch(color=COLOR["right"],  label="Right"),
        mpatches.Patch(color=COLOR["center"], label="Center"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=3,
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, -0.12),
    )

    fname = OUT_DIR / f"{condition.lower()}_{age.lower()}.png"
    fig.savefig(fname, dpi=150, bbox_inches="tight")
    plt.close(fig)
    print(f"Saved → {fname}")


def main():
    leanings = load_leanings()
    print(f"Loaded leanings for {len(leanings)} videos")
    for age, condition, stem in GROUPS:
        make_chart(age, condition, stem, leanings)
    print("Done.")


if __name__ == "__main__":
    main()
