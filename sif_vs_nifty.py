"""
Daily % change (bars) and cumulative return (lines) for several SIF schemes vs Nifty 50,
last 15 common sessions. One chart + one CSV per scheme, written to ./charts/.

Install:  pip install requests pandas yfinance matplotlib
Run:      python sif_vs_nifty.py

Add or remove funds in SCHEMES below (Charlie internal code or ISIN).
Find ISINs with: https://api.charliealpha.in/v1/sif/search?q=quant
SIF NAVs come from the free Charlie API; Nifty closes from yfinance (^NSEI).
Only dates present in BOTH series are used, so each bar compares the same
session-to-session move for the fund and the index.
"""
import re
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # no display needed, so it works from a scheduler / CI
import matplotlib.pyplot as plt
import pandas as pd
import requests
import yfinance as yf

# Charlie internal scheme codes (or ISINs). Chart labels come from the API's scheme name.
SCHEMES = ["1", "5", "90", "23"]

BASE_URL = "https://api.charliealpha.in/v1/sif/hnav/"
N_DAYS = 15
OUT_DIR = Path(__file__).resolve().parent / "charts"

HEADERS = {
    # Some hosts reject the default python-requests User-Agent (403), especially
    # from cloud/CI IP ranges, so identify like a normal browser.
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Referer": "https://api.charliealpha.in/",
}


def get_json(url, tries=4):
    last = None
    for i in range(tries):
        r = requests.get(url, headers=HEADERS, timeout=30)
        if r.status_code == 200:
            return r.json()
        last = r
        print(f"{url} -> HTTP {r.status_code}: {r.text[:200]!r}", file=sys.stderr)
        if r.status_code not in (403, 429, 500, 502, 503, 504):
            break
        time.sleep(5 * (i + 1))
    last.raise_for_status()


def sif_navs(code):
    j = get_json(BASE_URL + code)
    s = pd.Series(pd.to_numeric(j["nav"]), index=pd.to_datetime(j["dates"]), name="sif_nav")
    return s, j.get("scheme_name", code)


def nifty_closes():
    h = yf.Ticker("^NSEI").history(period="3mo", auto_adjust=False)
    s = h["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    s.name = "nifty_close"
    return s


def build(sif, nifty):
    df = pd.concat([sif, nifty], axis=1, join="inner").sort_index()
    pct = df.pct_change() * 100
    pct.columns = ["SIF % chg", "Nifty 50 % chg"]
    out = pd.concat([df, pct], axis=1).dropna().tail(N_DAYS)
    if out.empty:
        raise ValueError("no overlapping dates between the fund and Nifty")
    # Cumulative return since the close BEFORE the first bar (that day = 0%).
    out["SIF cum %"] = ((1 + out["SIF % chg"] / 100).cumprod() - 1) * 100
    out["Nifty 50 cum %"] = ((1 + out["Nifty 50 % chg"] / 100).cumprod() - 1) * 100
    base_date = df.index[df.index.get_loc(out.index[0]) - 1]
    return out, base_date


def plot(out, base_date, label, path):
    n = len(out)
    labels = [base_date.strftime("%d %b")] + [d.strftime("%d %b") for d in out.index]
    blue, grey = "#1f6feb", "#6b7686"
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(12, 9.5), sharex=True, gridspec_kw={"height_ratios": [3, 2.4]}
    )

    # --- Top: daily % change bars (bar i sits at x = i + 1; x = 0 is the base day) ---
    xs = [i + 1 for i in range(n)]
    w = 0.4
    b1 = ax.bar([x - w / 2 for x in xs], out["SIF % chg"], w, label=label, color=blue)
    b2 = ax.bar([x + w / 2 for x in xs], out["Nifty 50 % chg"], w,
                label="Nifty 50", color="#9aa4b2")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel("Daily change (%)")
    ax.set_title(f"{label} vs Nifty 50: daily % change, last {n} common sessions "
                 f"(to {out.index[-1]:%d %b %Y})")
    ax.bar_label(b1, fmt="%.2f", fontsize=7, padding=2)
    ax.bar_label(b2, fmt="%.2f", fontsize=7, padding=2)
    ax.legend(loc="upper left")
    ax.grid(axis="y", alpha=0.3)

    # --- Bottom: cumulative return lines, both start at 0% on the base day ---
    xl = [0] + xs
    sif_cum = [0.0] + list(out["SIF cum %"])
    nif_cum = [0.0] + list(out["Nifty 50 cum %"])
    ax2.plot(xl, sif_cum, color=blue, marker="o", markersize=4, linewidth=2, label=label)
    ax2.plot(xl, nif_cum, color=grey, marker="o", markersize=4, linewidth=2,
             label="Nifty 50")
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.fill_between(xl, sif_cum, nif_cum, color=blue, alpha=0.08)
    ax2.set_ylabel("Cumulative return (%)")
    ax2.set_title(f"Cumulative return since {base_date:%d %b} close")
    ax2.grid(alpha=0.3)
    ax2.legend(loc="upper left")
    ax2.annotate(f"{sif_cum[-1]:+.2f}%", (xl[-1], sif_cum[-1]), xytext=(8, 0),
                 textcoords="offset points", va="center", color=blue, fontweight="bold")
    ax2.annotate(f"{nif_cum[-1]:+.2f}%", (xl[-1], nif_cum[-1]), xytext=(8, 0),
                 textcoords="offset points", va="center", color=grey, fontweight="bold")
    ax2.set_xlim(-0.6, n + 1.2)

    ax2.set_xticks(range(n + 1))
    ax2.set_xticklabels(labels, rotation=45, ha="right")
    fig.tight_layout()
    fig.savefig(path, dpi=150)
    plt.close(fig)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def clean_name(api_name):
    """'qsif Equity Long Short Fund - Growth Option - Direct Plan' -> 'qsif Equity Long Short Fund (Direct)'"""
    plan = "Direct" if "direct" in api_name.lower() else ("Regular" if "regular" in api_name.lower() else "")
    base = api_name.split(" - ")[0].strip()
    return f"{base} ({plan})" if plan else base


def write_readme(done):
    lines = [
        "# SIF funds vs Nifty 50", "",
        "Daily % change (bars) and cumulative return (lines) of each fund against Nifty 50 for the",
        f"last {N_DAYS} common sessions. Updated automatically by GitHub Actions on weekday mornings.", "",
    ]
    for label, code in done:
        lines += [f"### {label}", f"![{label}](charts/sif_{slug(code)}.png)", ""]
    lines += [
        "- Fund NAVs: free Charlie API (`/v1/sif/hnav/{code}`)",
        "- Nifty 50 closes: yfinance (`^NSEI`)",
        "- Data tables: the `.csv` files in [`charts/`](charts/)",
        "- Add or change funds: edit the `SCHEMES` list at the top of `sif_vs_nifty.py`",
        "- This file is regenerated on every run",
        "",
        "Only dates present in both series are used, so each bar compares the same session-to-session move.",
        "For education and research, not investment advice.", "",
    ]
    (OUT_DIR.parent / "README.md").write_text("\n".join(lines))


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    try:
        nifty = nifty_closes()
    except Exception as e:
        print(f"Failed to fetch Nifty: {type(e).__name__}: {e}")
        sys.exit(1)

    failures, done = [], []
    for code in SCHEMES:
        try:
            sif, api_name = sif_navs(str(code))
            label = clean_name(api_name)
            table, base = build(sif, nifty)
            name = f"sif_{slug(str(code))}"
            table.round(4).to_csv(OUT_DIR / f"{name}.csv", index_label="date")
            plot(table, base, label, OUT_DIR / f"{name}.png")
            done.append((label, str(code)))
            print(f"\n== {label}  [code {code}] ==")
            print(table.round(2).to_string())
        except Exception as e:
            failures.append(str(code))
            print(f"\n!! code {code} failed: {type(e).__name__}: {e}", file=sys.stderr)

    if done:
        write_readme(done)
    print(f"\nCharts saved in: {OUT_DIR}")
    if failures:
        print(f"Failed codes: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)
