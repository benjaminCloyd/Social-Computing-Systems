"""
Timeline of political videos per run, color-coded by political leaning.

For each participant group (18f/18m/35f/35m × control/treatment):
  - X axis: position in the feed (1–200)
  - Y axis: run number
  - Gray dots: all videos watched
  - Colored dots: political videos
      red    = right
      blue   = left
      purple = center

Output: political_timeline.png
"""

import json
import re
from collections import defaultdict
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

# ---------------------------------------------------------------------------
BASE_DIR = Path(__file__).parent
LEANING_FILE = BASE_DIR / "political_leaning_results.json"
OUTPUT = BASE_DIR / "political_timeline.png"

COLOR = {"right": "#d62728", "left": "#1f77b4", "center": "#9467bd"}
LEANING_LABEL = {"right": "Right", "left": "Left", "center": "Center"}

POS_RE = re.compile(r"\[(\d+)/\d+\]")
VID_RE = re.compile(r"youtube\.com/shorts/([A-Za-z0-9_\-]+)")

GROUPS = [
    ("18F", "control/18fcontrol"),
    ("18M", "control/18mcontrol"),
    ("35F", "control/35fcontrol"),
    ("35M", "control/35mcontrol"),
    ("18F", "treatment/18ftreatment"),
    ("18M", "treatment/18mtreatment"),
    ("35F", "treatment/35ftreatment"),
    ("35M", "treatment/35mtreatment"),
]


# ---------------------------------------------------------------------------
def load_leanings() -> dict[str, str]:
    """video_id -> leaning"""
    with open(LEANING_FILE) as f:
        data = json.load(f)
    return {entry["video_id"]: entry["leaning"] for entry in data}


def load_political_ids(json_path: Path) -> set[str]:
    with open(json_path) as f:
        data = json.load(f)
    return {v["video_id"] for v in data if v.get("is_political")}


def parse_runs(txt_path: Path) -> list[list[tuple[int, str]]]:
    """Return list of runs; each run is [(position, video_id), ...]."""
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
            first = False
            vid_m = VID_RE.search(line)
            if vid_m:
                current.append((pos, vid_m.group(1)))

    if current:
        runs.append(current)
    return runs


# ---------------------------------------------------------------------------
def plot_group(ax, label: str, stem: str, leanings: dict[str, str]):
    txt_path = BASE_DIR / (stem + ".txt")
    json_path = BASE_DIR / (stem + ".json")

    if not txt_path.exists() or not json_path.exists():
        ax.text(0.5, 0.5, "No data", ha="center", va="center", transform=ax.transAxes)
        return

    political_ids = load_political_ids(json_path)
    runs = parse_runs(txt_path)[:3]

    for run_idx, run in enumerate(runs, start=1):
        xs_all, ys_all = [], []
        xs_pol = defaultdict(list)   # leaning -> [x positions]

        for pos, vid in run:
            xs_all.append(pos)
            ys_all.append(run_idx)
            if vid in political_ids:
                leaning = leanings.get(vid, "center")
                xs_pol[leaning].append(pos)

        # Background: all videos
        ax.scatter(xs_all, ys_all, s=4, color="#cccccc", zorder=1, linewidths=0)

        # Political videos by leaning
        for leaning, xs in xs_pol.items():
            ax.scatter(
                xs,
                [run_idx] * len(xs),
                s=60,
                color=COLOR[leaning],
                zorder=3,
                linewidths=0.4,
                edgecolors="white",
            )

    n_runs = len(runs)
    folder = stem.split("/")[0].capitalize()
    ax.set_title(f"{folder} · {label}", fontsize=9, fontweight="bold")
    ax.set_xlabel("Feed position", fontsize=7)
    ax.set_ylabel("Run", fontsize=7)
    ax.set_xlim(0, 202)
    ax.set_ylim(0.4, n_runs + 0.6)
    ax.set_yticks(range(1, n_runs + 1))
    ax.tick_params(labelsize=7)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)


# ---------------------------------------------------------------------------
def main():
    leanings = load_leanings()
    print(f"Loaded leanings for {len(leanings)} videos")

    fig, axes = plt.subplots(
        4, 2,
        figsize=(14, 12),
        gridspec_kw={"hspace": 0.55, "wspace": 0.35},
    )

    # Column 0 = control, column 1 = treatment
    # Row 0-3 = 18F, 18M, 35F, 35M
    positions = [
        (0, 0), (1, 0), (2, 0), (3, 0),   # control column
        (0, 1), (1, 1), (2, 1), (3, 1),   # treatment column
    ]

    for (label, stem), (row, col) in zip(GROUPS, positions):
        ax = axes[row][col]
        plot_group(ax, label, stem, leanings)

    # Column headers
    axes[0][0].set_title(f"Control · {GROUPS[0][0]}", fontsize=9, fontweight="bold")
    axes[0][1].set_title(f"Treatment · {GROUPS[4][0]}", fontsize=9, fontweight="bold")
    for i, (label, _) in enumerate(GROUPS[:4]):
        axes[i][0].set_title(f"Control · {label}", fontsize=9, fontweight="bold")
    for i, (label, _) in enumerate(GROUPS[4:]):
        axes[i][1].set_title(f"Treatment · {label}", fontsize=9, fontweight="bold")

    # Legend
    legend_handles = [
        mpatches.Patch(color=COLOR["left"],   label="Left"),
        mpatches.Patch(color=COLOR["right"],  label="Right"),
        mpatches.Patch(color=COLOR["center"], label="Center"),
        mpatches.Patch(color="#cccccc",       label="Non-political"),
    ]
    fig.legend(
        handles=legend_handles,
        loc="lower center",
        ncol=4,
        fontsize=9,
        frameon=False,
        bbox_to_anchor=(0.5, -0.01),
    )

    fig.suptitle(
        "Political Video Timeline by Run\n(position in feed vs. run number)",
        fontsize=13,
        fontweight="bold",
        y=1.01,
    )

    fig.savefig(OUTPUT, dpi=150, bbox_inches="tight")
    print(f"Saved → {OUTPUT}")


if __name__ == "__main__":
    main()
