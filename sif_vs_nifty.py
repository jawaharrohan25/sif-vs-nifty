"""
Daily % change: qsif Equity Long-Short Fund (Direct Growth) vs Nifty 50, last 15 sessions.

Install:  pip install requests pandas yfinance matplotlib
Run:      python sif_vs_nifty.py
Output:   sif_vs_nifty.png (bar chart), sif_vs_nifty_log.csv (the table, overwritten each run)

SIF NAVs come from the free Charlie API; Nifty closes from yfinance (^NSEI).
Only dates present in BOTH series are used, so each bar compares the same
session-to-session move for the fund and the index.
"""
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # no display needed, so it works from a scheduler
import matplotlib.pyplot as plt
import pandas as pd
import requests
import yfinance as yf

SIF_URL = "https://api.charliealpha.in/v1/sif/hnav/1"
N_DAYS = 15
OUT_DIR = Path(__file__).resolve().parent


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


def sif_navs():
    j = get_json(SIF_URL)
    s = pd.Series(pd.to_numeric(j["nav"]), index=pd.to_datetime(j["dates"]), name="sif_nav")
    return s


def nifty_closes():
    h = yf.Ticker("^NSEI").history(period="3mo", auto_adjust=False)
    s = h["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    s.name = "nifty_close"
    return s


def build():
    df = pd.concat([sif_navs(), nifty_closes()], axis=1, join="inner").sort_index()
    pct = df.pct_change() * 100
    pct.columns = ["SIF % chg", "Nifty 50 % chg"]
    out = pd.concat([df, pct], axis=1).dropna().tail(N_DAYS)
    return out


def plot(out):
    labels = [d.strftime("%d %b") for d in out.index]
    x = range(len(out))
    w = 0.4
    fig, ax = plt.subplots(figsize=(12, 5.5))
    b1 = ax.bar([i - w / 2 for i in x], out["SIF % chg"], w,
                label="qsif Equity Long-Short (Direct)", color="#1f6feb")
    b2 = ax.bar([i + w / 2 for i in x], out["Nifty 50 % chg"], w,
                label="Nifty 50", color="#9aa4b2")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_xticks(list(x))
    ax.set_xticklabels(labels, rotation=45, ha="right")
    ax.set_ylabel("Daily change (%)")
    ax.set_title(f"Daily % change, last {len(out)} common sessions "
                 f"(to {out.index[-1]:%d %b %Y})")
    ax.bar_label(b1, fmt="%.2f", fontsize=7, padding=2)
    ax.bar_label(b2, fmt="%.2f", fontsize=7, padding=2)
    ax.legend()
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    path = OUT_DIR / "sif_vs_nifty.png"
    fig.savefig(path, dpi=150)
    return path


if __name__ == "__main__":
    try:
        table = build()
    except Exception as e:
        print(f"Failed to fetch data: {type(e).__name__}: {e}")
        sys.exit(1)
    table.round(4).to_csv(OUT_DIR / "sif_vs_nifty_log.csv", index_label="date")
    png = plot(table)
    print(table.round(2).to_string())
    print(f"\nSaved chart: {png}")
