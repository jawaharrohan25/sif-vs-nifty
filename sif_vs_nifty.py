"""
SIF schemes vs Nifty 50: daily and monthly charts.

For each scheme this writes, into ./charts/:
  sif_<code>.png / .csv           daily % change (bars) + cumulative return (lines), last N_DAYS sessions
  sif_<code>_monthly.png / .csv   monthly % change (bars) + cumulative return (lines), last N_MONTHS months
and regenerates README.md and index.html (a web page for GitHub Pages) with all the charts.

Install:  pip install requests pandas yfinance matplotlib
Run:      python sif_vs_nifty.py

Add or remove funds in SCHEMES below (Charlie internal code or ISIN).
Find ISINs with: https://api.charliealpha.in/v1/sif/search?q=quant
SIF NAVs come from the free Charlie API; Nifty closes from yfinance (^NSEI).
Only dates present in BOTH series are used, so each bar compares the same period for
the fund and the index. Monthly bars use each month's last common trading day, and the
current month is shown month-to-date (marked with *).
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
N_DAYS = 30      # daily chart: last N common sessions
N_MONTHS = 12    # monthly chart: last N months
OUT_DIR = Path(__file__).resolve().parent / "charts"

HEADERS = {
    # Some hosts reject the default python-requests User-Agent (403), especially
    # from cloud/CI IP ranges, so identify like a normal browser.
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
    "Accept": "application/json",
    "Referer": "https://api.charliealpha.in/",
}


class NotEnoughData(Exception):
    """Fund/Nifty overlap is too short for this chart (expected for new funds)."""


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
    # 2y covers both the 30-session daily view and the 12-month monthly view.
    h = yf.Ticker("^NSEI").history(period="2y", auto_adjust=False)
    s = h["Close"].copy()
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    s.name = "nifty_close"
    return s


def _add_cumulative(out):
    # Cumulative return since the close BEFORE the first bar (that point = 0%).
    out["SIF cum %"] = ((1 + out["SIF % chg"] / 100).cumprod() - 1) * 100
    out["Nifty 50 cum %"] = ((1 + out["Nifty 50 % chg"] / 100).cumprod() - 1) * 100
    return out


def build_daily(sif, nifty):
    df = pd.concat([sif, nifty], axis=1, join="inner").sort_index()
    pct = df.pct_change() * 100
    pct.columns = ["SIF % chg", "Nifty 50 % chg"]
    out = pd.concat([df, pct], axis=1).dropna().tail(N_DAYS)
    if out.empty:
        raise NotEnoughData("no overlapping dates between the fund and Nifty")
    base_label = df.index[df.index.get_loc(out.index[0]) - 1].strftime("%d %b")
    bar_labels = [d.strftime("%d %b") for d in out.index]
    return _add_cumulative(out), base_label, bar_labels, None


def build_monthly(sif, nifty):
    df = pd.concat([sif, nifty], axis=1, join="inner").sort_index()
    per = df.index.to_period("M")
    lvl = df.groupby(per).last()                       # last common trading day's level per month
    last_day = df.index.to_series().groupby(per).last()  # which day that was
    pct = lvl.pct_change() * 100
    pct.columns = ["SIF % chg", "Nifty 50 % chg"]
    out = pd.concat([lvl, pct], axis=1).dropna().tail(N_MONTHS)
    if out.empty:
        raise NotEnoughData("need at least two month-ends of overlapping data")
    base_label = lvl.index[lvl.index.get_loc(out.index[0]) - 1].strftime("%b '%y")
    bar_labels = [p.strftime("%b '%y") for p in out.index]
    footnote = None
    newest = out.index[-1]
    if last_day[newest].normalize() < newest.end_time.normalize():
        bar_labels[-1] += "*"
        footnote = f"* month to date (to {last_day[newest]:%d %b %Y})"
    out = _add_cumulative(out)
    out.index = out.index.astype(str)
    return out, base_label, bar_labels, footnote


def plot(out, base_label, bar_labels, label, path, kind, footnote=None):
    n = len(out)
    unit = "daily" if kind == "daily" else "monthly"
    span = f"last {n} common sessions" if kind == "daily" else f"last {n} months"
    labels = [base_label] + bar_labels
    blue, grey = "#1f6feb", "#6b7686"
    width = 12 if n <= 15 else 16
    fig, (ax, ax2) = plt.subplots(
        2, 1, figsize=(width, 9.5), sharex=True, gridspec_kw={"height_ratios": [3, 2.4]}
    )

    # --- Top: % change bars (bar i sits at x = i + 1; x = 0 is the base point) ---
    xs = [i + 1 for i in range(n)]
    w = 0.4
    b1 = ax.bar([x - w / 2 for x in xs], out["SIF % chg"], w, label=label, color=blue)
    b2 = ax.bar([x + w / 2 for x in xs], out["Nifty 50 % chg"], w,
                label="Nifty 50", color="#9aa4b2")
    ax.axhline(0, color="black", linewidth=0.8)
    ax.set_ylabel(f"{unit.capitalize()} change (%)")
    ax.set_title(f"{label} vs Nifty 50: {unit} % change, {span}")
    fs = 7 if n <= 15 else 5.5
    ax.bar_label(b1, fmt="%.2f", fontsize=fs, padding=2)
    ax.bar_label(b2, fmt="%.2f", fontsize=fs, padding=2)
    ax.legend(loc="upper left")
    ax.grid(axis="y", alpha=0.3)

    # --- Bottom: cumulative return lines, both start at 0% at the base point ---
    xl = [0] + xs
    sif_cum = [0.0] + list(out["SIF cum %"])
    nif_cum = [0.0] + list(out["Nifty 50 cum %"])
    ax2.plot(xl, sif_cum, color=blue, marker="o", markersize=4, linewidth=2, label=label)
    ax2.plot(xl, nif_cum, color=grey, marker="o", markersize=4, linewidth=2, label="Nifty 50")
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.fill_between(xl, sif_cum, nif_cum, color=blue, alpha=0.08)
    ax2.set_ylabel("Cumulative return (%)")
    ax2.set_title(f"Cumulative return since {base_label} close")
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
    if footnote:
        fig.text(0.01, 0.005, footnote, fontsize=8, color=grey)
    fig.savefig(path, dpi=150)
    plt.close(fig)


def slug(text):
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def clean_name(api_name):
    """'qsif Equity Long Short Fund - Growth Option - Direct Plan' -> 'qsif Equity Long Short Fund (Direct)'"""
    low = api_name.lower()
    plan = "Direct" if "direct" in low else ("Regular" if "regular" in low else "")
    base = api_name.split(" - ")[0].strip()
    return f"{base} ({plan})" if plan else base


def write_readme(done):
    lines = [
        "# SIF funds vs Nifty 50", "",
        f"Daily (last {N_DAYS} sessions) and monthly (last {N_MONTHS} months) % change as bars, with",
        "cumulative return as lines, for each fund against Nifty 50.",
        "Updated automatically by GitHub Actions on weekday mornings.", "",
    ]
    for label, code, has_daily, has_monthly in done:
        s = f"sif_{slug(code)}"
        lines += [f"## {label}", ""]
        if has_monthly:
            lines += [f"### Monthly, last {N_MONTHS} months", f"![{label} monthly](charts/{s}_monthly.png)", ""]
        if has_daily:
            lines += [f"### Daily, last {N_DAYS} sessions", f"![{label} daily](charts/{s}.png)", ""]
    lines += [
        "- Fund NAVs: free Charlie API (`/v1/sif/hnav/{code}`)",
        "- Nifty 50 closes: yfinance (`^NSEI`)",
        "- Data tables: the `.csv` files in [`charts/`](charts/)",
        "- Add or change funds: edit `SCHEMES` at the top of `sif_vs_nifty.py`",
        "- New funds show fewer months until they have enough history",
        "- This file is regenerated on every run", "",
        "Only dates present in both series are used, so each bar compares the same period.",
        "For education and research, not investment advice.", "",
    ]
    (OUT_DIR.parent / "README.md").write_text("\n".join(lines))


def write_index(done):
    """Static web page (index.html) with every chart, for GitHub Pages."""
    import html
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc)
    v = now.strftime("%Y%m%d%H%M")  # cache-buster so browsers fetch the fresh images
    nav = " ".join(f'<a href="#f{slug(c)}">{html.escape(l)}</a>' for l, c, _, _ in done)
    cards = []
    for label, code, has_daily, has_monthly in done:
        s_ = f"sif_{slug(code)}"
        imgs = ""
        if has_monthly:
            imgs += (f'<h3>Monthly, last {N_MONTHS} months</h3>'
                     f'<img src="charts/{s_}_monthly.png?v={v}" alt="{html.escape(label)} monthly" loading="lazy">')
        if has_daily:
            imgs += (f'<h3>Daily, last {N_DAYS} sessions</h3>'
                     f'<img src="charts/{s_}.png?v={v}" alt="{html.escape(label)} daily" loading="lazy">')
        cards.append(f'<section id="f{slug(code)}"><h2>{html.escape(label)}</h2>{imgs}</section>')
    page = f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>SIF vs Nifty</title>
<style>
:root{{--bg:#f6f8fa;--card:#fff;--fg:#1f2328;--muted:#656d76;--line:#d0d7de;--link:#0969da}}
@media (prefers-color-scheme:dark){{:root{{--bg:#0d1117;--card:#161b22;--fg:#e6edf3;--muted:#8b949e;--line:#30363d;--link:#58a6ff}}}}
body{{margin:0;padding:0 16px 40px;background:var(--bg);color:var(--fg);font:16px/1.5 system-ui,sans-serif}}
main{{max-width:1100px;margin:0 auto}}
h1{{margin:24px 0 4px}} .sub{{color:var(--muted);margin:0 0 16px}}
nav{{display:flex;flex-wrap:wrap;gap:8px;margin:0 0 20px}}
nav a{{padding:6px 12px;border:1px solid var(--line);border-radius:999px;color:var(--link);text-decoration:none;background:var(--card)}}
section{{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:8px 16px 16px;margin:0 0 20px}}
h3{{color:var(--muted);font-size:14px;font-weight:600;margin:16px 0 6px}}
img{{width:100%;height:auto;border-radius:8px;background:#fff}}
footer{{color:var(--muted);font-size:13px}}
</style></head><body><main>
<h1>SIF funds vs Nifty 50</h1>
<p class="sub">Daily and monthly % change (bars) with cumulative return (lines). Updated {now:%d %b %Y %H:%M} UTC.</p>
<nav>{nav}</nav>
{"".join(cards)}
<footer>Fund NAVs: Charlie API. Nifty 50: Yahoo Finance. For education and research, not investment advice.</footer>
</main></body></html>"""
    (OUT_DIR.parent / "index.html").write_text(page)


def run_one(builder, sif, nifty, label, name, kind):
    """Build + save one chart. Returns True if produced, False if skipped (too little data)."""
    try:
        table, base, bar_labels, note = builder(sif, nifty)
    except NotEnoughData as e:
        print(f"   skipped {kind} chart for {label}: {e}")
        return False
    table.round(4).to_csv(OUT_DIR / f"{name}.csv", index_label="date")
    plot(table, base, bar_labels, label, OUT_DIR / f"{name}.png", kind, note)
    print(f"\n== {label} ({kind}) ==")
    print(table.round(2).to_string())
    return True


if __name__ == "__main__":
    OUT_DIR.mkdir(exist_ok=True)
    try:
        nifty = nifty_closes()
    except Exception as e:
        print(f"Failed to fetch Nifty: {type(e).__name__}: {e}")
        sys.exit(1)

    failures, done = [], []
    for code in SCHEMES:
        code = str(code)
        try:
            sif, api_name = sif_navs(code)
            label = clean_name(api_name)
            base = f"sif_{slug(code)}"
            d = run_one(build_daily, sif, nifty, label, base, "daily")
            m = run_one(build_monthly, sif, nifty, label, f"{base}_monthly", "monthly")
            if d or m:
                done.append((label, code, d, m))
        except Exception as e:
            failures.append(code)
            print(f"\n!! code {code} failed: {type(e).__name__}: {e}", file=sys.stderr)

    if done:
        write_readme(done)
        write_index(done)
    print(f"\nCharts saved in: {OUT_DIR}")
    if failures:
        print(f"Failed codes: {', '.join(failures)}", file=sys.stderr)
        sys.exit(1)
