#!/usr/bin/env python3
"""
political_exposure_analysis.py

Research analysis of how the YouTube Shorts algorithm exposes users to
political content depending on condition (control vs treatment), gender
(male vs female), and age group (18 vs 35).

Outcomes measured
-----------------
1. Overall political exposure rate  — P(video is political)
2. Leaning-specific exposure rates  — P(video is left/center/right)
3. Leaning distribution conditional on political — P(leaning | political)

Statistical methods
-------------------
- Wilson 95% confidence intervals for proportions
- Chi-squared test (Fisher's exact when any expected cell < 5)
- Cohen's h effect size for pairwise proportion comparisons
- Binary logistic regression: all main effects + two-way interactions
- Bonferroni correction across the pairwise family of tests
"""

import json
import warnings
from pathlib import Path
from itertools import combinations
from collections import defaultdict

import numpy as np
import pandas as pd
from scipy import stats
from statsmodels.stats.proportion import proportion_confint
import statsmodels.formula.api as smf

warnings.filterwarnings("ignore")

BASE = Path(__file__).parent

# ---------------------------------------------------------------------------
# 1. Load data
# ---------------------------------------------------------------------------

FILE_META = {
    "control/18mcontrol.json":     ("control",   "18", "male"),
    "control/18fcontrol.json":     ("control",   "18", "female"),
    "control/35mcontrol.json":     ("control",   "35", "male"),
    "control/35fcontrol.json":     ("control",   "35", "female"),
    "treatment/18mtreatment.json": ("treatment", "18", "male"),
    "treatment/18ftreatment.json": ("treatment", "18", "female"),
    "treatment/35mtreatment.json": ("treatment", "35", "male"),
    "treatment/35ftreatment.json": ("treatment", "35", "female"),
}


def load_videos() -> pd.DataFrame:
    rows = []
    for fname, (condition, age, gender) in FILE_META.items():
        data = json.loads((BASE / fname).read_text())
        for v in data:
            rows.append({
                "video_id":   v["video_id"],
                "source_file": Path(fname).name,
                "condition":  condition,
                "age":        age,
                "gender":     gender,
                "is_political": bool(v.get("is_political")),
                "leaning":    None,  # filled in below
            })
    return pd.DataFrame(rows)


def merge_leanings(df: pd.DataFrame) -> pd.DataFrame:
    leaning_data = json.loads((BASE / "political_leaning_results.json").read_text())
    # Key by (video_id, source_file) to handle same video in multiple groups
    leaning_map = {(r["video_id"], r["source_file"]): r["leaning"] for r in leaning_data}
    df["leaning"] = df.apply(
        lambda row: leaning_map.get((row["video_id"], row["source_file"])), axis=1
    )
    return df


# ---------------------------------------------------------------------------
# 2. Statistical helpers
# ---------------------------------------------------------------------------

def wilson_ci(count: int, nobs: int, alpha: float = 0.05):
    """Return (proportion, lower, upper) with Wilson 95% CI."""
    if nobs == 0:
        return (np.nan, np.nan, np.nan)
    p = count / nobs
    lo, hi = proportion_confint(count, nobs, alpha=alpha, method="wilson")
    return p, lo, hi


def cohen_h(p1: float, p2: float) -> float:
    """Cohen's h effect size for two proportions."""
    return 2 * np.arcsin(np.sqrt(p1)) - 2 * np.arcsin(np.sqrt(p2))


def chi2_or_fisher(ct: np.ndarray):
    """
    Run chi-squared or Fisher's exact test on a contingency table.
    Falls back to Fisher's when any expected cell < 5.
    Returns (test_name, statistic, p_value).
    """
    chi2, p_chi2, dof, expected = stats.chi2_contingency(ct, correction=False)
    if (expected < 5).any():
        if ct.shape == (2, 2):
            _, p_fish = stats.fisher_exact(ct)
            return "Fisher's exact", np.nan, p_fish
        else:
            # For larger tables use chi2 with Yates correction
            chi2, p_chi2, _, _ = stats.chi2_contingency(ct, correction=True)
            return "Chi-sq (corrected)", chi2, p_chi2
    return "Chi-sq", chi2, p_chi2


def pairwise_proportion_tests(group_stats: dict, label: str, n_comparisons: int):
    """
    Run all pairwise chi-squared/Fisher tests between groups.
    Applies Bonferroni correction.
    Prints a formatted table.
    """
    groups = list(group_stats.keys())
    rows = []
    for (g1, g2) in combinations(groups, 2):
        s1 = group_stats[g1]
        s2 = group_stats[g2]
        ct = np.array([[s1["pol"], s1["n"] - s1["pol"]],
                       [s2["pol"], s2["n"] - s2["pol"]]])
        test_name, stat, p = chi2_or_fisher(ct)
        h = cohen_h(s1["rate"], s2["rate"])
        p_bonf = min(p * n_comparisons, 1.0)
        rows.append({
            "Group A": g1, "Group B": g2,
            "Rate A": s1["rate"], "Rate B": s2["rate"],
            "Cohen h": h, "Test": test_name,
            "p": p, "p (Bonf.)": p_bonf,
            "sig": significance_stars(p_bonf),
        })
    if rows:
        df_out = pd.DataFrame(rows)
        _print_df(df_out, f"Pairwise comparisons — {label}")


def significance_stars(p: float) -> str:
    if p < 0.001:
        return "***"
    if p < 0.01:
        return "**"
    if p < 0.05:
        return "*"
    if p < 0.10:
        return "."
    return "ns"


# ---------------------------------------------------------------------------
# 3. Display helpers
# ---------------------------------------------------------------------------

def _print_df(df: pd.DataFrame, title: str = ""):
    sep = "─" * 80
    if title:
        print(f"\n{sep}")
        print(f"  {title}")
        print(sep)
    fmt = df.copy()
    for col in fmt.select_dtypes(include="float").columns:
        if col in ("p", "p (Bonf.)"):
            fmt[col] = fmt[col].apply(lambda x: f"{x:.4f}" if not np.isnan(x) else "NaN")
        elif "Rate" in col or col in ("prop", "lo", "hi"):
            fmt[col] = fmt[col].apply(lambda x: f"{x:.3f}" if not np.isnan(x) else "NaN")
        elif col in ("Cohen h", "OR", "Stat"):
            fmt[col] = fmt[col].apply(lambda x: f"{x:.3f}" if not np.isnan(x) else "NaN")
    print(fmt.to_string(index=False))


def section(title: str):
    print("\n" + "=" * 80)
    print(f"  {title}")
    print("=" * 80)


# ---------------------------------------------------------------------------
# 4. Exposure rate tables
# ---------------------------------------------------------------------------

def exposure_table(df: pd.DataFrame, groupby: list[str]) -> pd.DataFrame:
    """
    Returns a summary table with political exposure rates and Wilson CIs
    for the given groupby columns.
    """
    rows = []
    for keys, grp in df.groupby(groupby):
        if not isinstance(keys, tuple):
            keys = (keys,)
        n = len(grp)
        pol = grp["is_political"].sum()
        rate, lo, hi = wilson_ci(pol, n)
        row = {col: k for col, k in zip(groupby, keys)}
        row.update({"n": n, "political": pol, "rate": rate, "CI_lo": lo, "CI_hi": hi})
        rows.append(row)
    return pd.DataFrame(rows)


def leaning_exposure_table(df: pd.DataFrame, groupby: list[str]) -> pd.DataFrame:
    """
    For each group, computes:
    - Exposure rate for each leaning (left/center/right) out of ALL videos
    - Distribution of leanings among political videos
    """
    rows = []
    pol_df = df[df["is_political"]]
    for keys, grp in df.groupby(groupby):
        if not isinstance(keys, tuple):
            keys = (keys,)
        n_total = len(grp)
        pol_grp = grp[grp["is_political"]]
        n_pol = len(pol_grp)

        for leaning in ("left", "center", "right"):
            n_lean = (pol_grp["leaning"] == leaning).sum()
            # Rate out of all videos in group
            rate_all, lo_all, hi_all = wilson_ci(n_lean, n_total)
            # Rate out of political videos only
            rate_pol, lo_pol, hi_pol = wilson_ci(n_lean, n_pol)
            row = {col: k for col, k in zip(groupby, keys)}
            row.update({
                "leaning": leaning,
                "n_total": n_total,
                "n_political": n_pol,
                "n_leaning": n_lean,
                "rate_of_all":      rate_all,
                "CI_lo (all)":      lo_all,
                "CI_hi (all)":      hi_all,
                "rate_of_political": rate_pol,
                "CI_lo (pol)":      lo_pol,
                "CI_hi (pol)":      hi_pol,
            })
            rows.append(row)
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------------
# 5. Logistic regression
# ---------------------------------------------------------------------------

def run_logit(df: pd.DataFrame, outcome_col: str, title: str):
    """Fit logit with condition, gender, age + all two-way interactions."""
    model_df = df.copy()
    model_df["political"] = model_df[outcome_col].astype(int)
    model_df["treated"]   = (model_df["condition"] == "treatment").astype(int)
    model_df["male"]      = (model_df["gender"] == "male").astype(int)
    model_df["older"]     = (model_df["age"] == "35").astype(int)

    formula = (
        "political ~ treated + male + older "
        "+ treated:male + treated:older + male:older"
    )
    try:
        result = smf.logit(formula, data=model_df).fit(disp=False)
        # Build readable output table
        coef_df = pd.DataFrame({
            "Coefficient": result.params,
            "Std Err":     result.bse,
            "z":           result.tvalues,
            "p":           result.pvalues,
            "OR":          np.exp(result.params),
            "OR CI lo":    np.exp(result.conf_int()[0]),
            "OR CI hi":    np.exp(result.conf_int()[1]),
        })
        coef_df["sig"] = coef_df["p"].apply(significance_stars)
        sep = "─" * 80
        print(f"\n{sep}\n  Logistic regression — {title}\n{sep}")
        print(f"  N = {int(result.nobs)}, "
              f"Pseudo-R² (McFadden) = {result.prsquared:.4f}, "
              f"LLR p = {result.llr_pvalue:.4g}")
        print()
        _print_df(coef_df.reset_index().rename(columns={"index": "Term"}), "")
    except Exception as exc:
        print(f"  [logit failed: {exc}]")


# ---------------------------------------------------------------------------
# 6. Main analysis
# ---------------------------------------------------------------------------

def main():
    print("Loading data …")
    df = load_videos()
    df = merge_leanings(df)
    print(f"  Total videos: {len(df):,}")
    print(f"  Political:    {df['is_political'].sum():,} "
          f"({df['is_political'].mean()*100:.1f}%)")
    print(f"  With leaning: {df['leaning'].notna().sum():,}")

    # ------------------------------------------------------------------ #
    section("1. OVERALL POLITICAL EXPOSURE RATES BY GROUP")
    # ------------------------------------------------------------------ #

    for groupby, label in [
        (["condition"],           "Condition"),
        (["gender"],              "Gender"),
        (["age"],                 "Age group"),
        (["condition", "gender"], "Condition × Gender"),
        (["condition", "age"],    "Condition × Age"),
        (["gender", "age"],       "Gender × Age"),
        (["condition", "gender", "age"], "Condition × Gender × Age (all cells)"),
    ]:
        tbl = exposure_table(df, groupby)
        display_cols = groupby + ["n", "political", "rate", "CI_lo", "CI_hi"]
        _print_df(tbl[display_cols], f"Political exposure rate by {label}")

    # ------------------------------------------------------------------ #
    section("2. PAIRWISE TESTS — POLITICAL EXPOSURE RATE")
    # ------------------------------------------------------------------ #

    # Build stats dict for each main-effect group
    def stats_by(col):
        out = {}
        for key, grp in df.groupby(col):
            n = len(grp)
            pol = grp["is_political"].sum()
            out[key] = {"n": n, "pol": pol, "rate": pol / n if n else np.nan}
        return out

    # Condition
    cond_stats = stats_by("condition")
    pairwise_proportion_tests(cond_stats, "condition", n_comparisons=1)

    # Gender
    gender_stats = stats_by("gender")
    pairwise_proportion_tests(gender_stats, "gender", n_comparisons=1)

    # Age
    age_stats = stats_by("age")
    pairwise_proportion_tests(age_stats, "age", n_comparisons=1)

    # All 8 condition×gender×age cells (28 pairs, Bonferroni n=28)
    all_stats = {}
    for keys, grp in df.groupby(["condition", "gender", "age"]):
        label = "/".join(keys)
        n = len(grp)
        pol = grp["is_political"].sum()
        all_stats[label] = {"n": n, "pol": pol, "rate": pol / n if n else np.nan}
    pairwise_proportion_tests(all_stats, "all 8 cells (Bonferroni n=28)", n_comparisons=28)

    # ------------------------------------------------------------------ #
    section("3. LOGISTIC REGRESSION — POLITICAL EXPOSURE")
    # ------------------------------------------------------------------ #
    run_logit(df, "is_political", "P(political) ~ condition + gender + age + interactions")

    # ------------------------------------------------------------------ #
    section("4. LEANING-SPECIFIC EXPOSURE RATES (out of ALL videos)")
    # ------------------------------------------------------------------ #

    for groupby, label in [
        (["condition"],           "Condition"),
        (["gender"],              "Gender"),
        (["age"],                 "Age group"),
        (["condition", "gender", "age"], "Condition × Gender × Age"),
    ]:
        tbl = leaning_exposure_table(df, groupby)
        display_cols = groupby + ["leaning", "n_total", "n_leaning",
                                  "rate_of_all", "CI_lo (all)", "CI_hi (all)"]
        _print_df(tbl[display_cols], f"Leaning exposure rates (of all videos) by {label}")

    # ------------------------------------------------------------------ #
    section("5. LEANING DISTRIBUTION AMONG POLITICAL VIDEOS")
    # ------------------------------------------------------------------ #

    pol_df = df[df["is_political"] & df["leaning"].notna()]
    for groupby, label in [
        (["condition"],           "Condition"),
        (["gender"],              "Gender"),
        (["age"],                 "Age group"),
        (["condition", "gender", "age"], "Condition × Gender × Age"),
    ]:
        tbl = leaning_exposure_table(df, groupby)
        display_cols = groupby + ["leaning", "n_political", "n_leaning",
                                  "rate_of_political", "CI_lo (pol)", "CI_hi (pol)"]
        _print_df(tbl[display_cols], f"Leaning distribution (of political) by {label}")

    # ------------------------------------------------------------------ #
    section("6. CHI-SQUARED TESTS — LEANING DISTRIBUTION BY GROUP")
    # ------------------------------------------------------------------ #

    def leaning_ct(subdf) -> np.ndarray:
        """2-D contingency table: rows=groups, cols=[left, center, right]."""
        return np.array([
            [
                ((subdf["leaning"] == lean)).sum()
                for lean in ("left", "center", "right")
            ]
        ])

    def compare_leaning_distribution(split_col: str, label: str):
        categories = df[split_col].unique()
        rows_ct = []
        for cat in categories:
            sub = pol_df[pol_df[split_col] == cat]
            rows_ct.append([
                (sub["leaning"] == lean).sum()
                for lean in ("left", "center", "right")
            ])
        ct = np.array(rows_ct)
        if ct.shape[0] < 2:
            return
        test_name, stat, p = chi2_or_fisher(ct)
        print(f"\n  {label}  ({test_name}, p = {p:.4f} {significance_stars(p)})")
        tbl = pd.DataFrame(ct, index=list(categories),
                           columns=["left", "center", "right"])
        tbl["total"] = tbl.sum(axis=1)
        for lean in ("left", "center", "right"):
            tbl[f"{lean}_%"] = (tbl[lean] / tbl["total"] * 100).round(1)
        print(tbl.to_string())

    compare_leaning_distribution("condition", "Leaning distribution: control vs treatment")
    compare_leaning_distribution("gender",    "Leaning distribution: male vs female")
    compare_leaning_distribution("age",       "Leaning distribution: age 18 vs 35")

    # ------------------------------------------------------------------ #
    section("7. LOGISTIC REGRESSIONS — LEANING (among political videos)")
    # ------------------------------------------------------------------ #

    # Binary: right vs. not-right | left vs. not-left  (among political)
    pol_model_df = pol_df.copy()
    pol_model_df["is_right"]  = (pol_model_df["leaning"] == "right").astype(int)
    pol_model_df["is_left"]   = (pol_model_df["leaning"] == "left").astype(int)
    pol_model_df["is_center"] = (pol_model_df["leaning"] == "center").astype(int)
    pol_model_df["is_political"] = 1  # reuse run_logit helper

    for outcome, title in [
        ("is_right",  "P(right | political) ~ condition + gender + age + interactions"),
        ("is_left",   "P(left  | political) ~ condition + gender + age + interactions"),
    ]:
        run_logit(pol_model_df, outcome, title)

    # ------------------------------------------------------------------ #
    section("8. SUMMARY — KEY FINDINGS")
    # ------------------------------------------------------------------ #

    # Compute summary numbers for narrative
    c_tbl = exposure_table(df, ["condition"])
    g_tbl = exposure_table(df, ["gender"])
    a_tbl = exposure_table(df, ["age"])

    c_ctrl  = c_tbl[c_tbl["condition"] == "control"].iloc[0]
    c_treat = c_tbl[c_tbl["condition"] == "treatment"].iloc[0]
    g_male  = g_tbl[g_tbl["gender"] == "male"].iloc[0]
    g_fem   = g_tbl[g_tbl["gender"] == "female"].iloc[0]
    a_18    = a_tbl[a_tbl["age"] == "18"].iloc[0]
    a_35    = a_tbl[a_tbl["age"] == "35"].iloc[0]

    # Leaning rates among political
    def leaning_pct(cond=None, gender=None, age=None, leaning=None):
        sub = pol_df.copy()
        if cond:   sub = sub[sub["condition"] == cond]
        if gender: sub = sub[sub["gender"] == gender]
        if age:    sub = sub[sub["age"] == age]
        if len(sub) == 0:
            return np.nan
        return (sub["leaning"] == leaning).mean() * 100

    print(f"""
  Political exposure rates
  ─────────────────────────────────────────────────────────────────────
  Control:         {c_ctrl['rate']*100:5.1f}%  [{c_ctrl['CI_lo']*100:.1f}%, {c_ctrl['CI_hi']*100:.1f}%]
  Treatment:       {c_treat['rate']*100:5.1f}%  [{c_treat['CI_lo']*100:.1f}%, {c_treat['CI_hi']*100:.1f}%]
  Cohen h (cond):  {cohen_h(c_treat['rate'], c_ctrl['rate']):.3f}

  Male:            {g_male['rate']*100:5.1f}%  [{g_male['CI_lo']*100:.1f}%, {g_male['CI_hi']*100:.1f}%]
  Female:          {g_fem['rate']*100:5.1f}%  [{g_fem['CI_lo']*100:.1f}%, {g_fem['CI_hi']*100:.1f}%]
  Cohen h (sex):   {cohen_h(g_male['rate'], g_fem['rate']):.3f}

  Age 18:          {a_18['rate']*100:5.1f}%  [{a_18['CI_lo']*100:.1f}%, {a_18['CI_hi']*100:.1f}%]
  Age 35:          {a_35['rate']*100:5.1f}%  [{a_35['CI_lo']*100:.1f}%, {a_35['CI_hi']*100:.1f}%]
  Cohen h (age):   {cohen_h(a_18['rate'], a_35['rate']):.3f}

  Among political — right-leaning %
  ─────────────────────────────────────────────────────────────────────
  Control:         {leaning_pct(cond='control', leaning='right'):5.1f}%
  Treatment:       {leaning_pct(cond='treatment', leaning='right'):5.1f}%
  Male:            {leaning_pct(gender='male', leaning='right'):5.1f}%
  Female:          {leaning_pct(gender='female', leaning='right'):5.1f}%
  Age 18:          {leaning_pct(age='18', leaning='right'):5.1f}%
  Age 35:          {leaning_pct(age='35', leaning='right'):5.1f}%

  Among political — left-leaning %
  ─────────────────────────────────────────────────────────────────────
  Control:         {leaning_pct(cond='control', leaning='left'):5.1f}%
  Treatment:       {leaning_pct(cond='treatment', leaning='left'):5.1f}%
  Male:            {leaning_pct(gender='male', leaning='left'):5.1f}%
  Female:          {leaning_pct(gender='female', leaning='left'):5.1f}%
  Age 18:          {leaning_pct(age='18', leaning='left'):5.1f}%
  Age 35:          {leaning_pct(age='35', leaning='left'):5.1f}%
""")

    print("  Significance codes:  *** p<0.001  ** p<0.01  * p<0.05  . p<0.10  ns")


if __name__ == "__main__":
    main()
