import os
import sys
import time
import datetime as dt
from zoneinfo import ZoneInfo

import requests
import pandas as pd
import nsepython
from PIL import Image, ImageDraw, ImageFont

IST = ZoneInfo("Asia/Kolkata")
MODE = sys.argv[1].lower() if len(sys.argv) > 1 else "open"
LABEL = "OPENING SNAPSHOT" if MODE == "open" else "CLOSING SNAPSHOT"
OUT_OVERVIEW = "nifty_dashboard_overview.png"
OUT_STOCKS = "nifty_dashboard_constituents.png"

# Official NSE constituent list. This is downloaded at run time so index
# reviews do not leave the dashboard using an outdated hardcoded list.
NIFTY50_CSV_URL = "https://nsearchives.nseindia.com/content/indices/ind_nifty50list.csv"
NSE_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0 Safari/537.36",
    "Accept": "text/csv,*/*",
    "Referer": "https://www.nseindia.com/",
}

INDEX_NAMES = [
    "NIFTY 50", "NIFTY NEXT 50", "NIFTY 100", "NIFTY 200", "NIFTY 500",
    "NIFTY MIDCAP 100", "NIFTY SMALLCAP 100", "NIFTY BANK",
    "NIFTY FINANCIAL SERVICES", "NIFTY IT", "NIFTY AUTO",
    "NIFTY PHARMA", "NIFTY FMCG", "NIFTY METAL", "NIFTY REALTY",
    "INDIA VIX",
]


def font(size, bold=False):
    path = (
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
        if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
    )
    if os.path.exists(path):
        return ImageFont.truetype(path, size)
    return ImageFont.load_default()


def fmt(value, decimals=2):
    try:
        if value is None or pd.isna(value):
            return "N/A"
        return f"{float(value):,.{decimals}f}"
    except (ValueError, TypeError):
        return "N/A"


def fetch_official_nifty50_symbols():
    print("Downloading the official NSE Nifty 50 constituent list...", flush=True)
    response = requests.get(NIFTY50_CSV_URL, headers=NSE_HEADERS, timeout=(10, 20))
    response.raise_for_status()

    from io import BytesIO
    df = pd.read_csv(BytesIO(response.content))
    if "Symbol" not in df.columns:
        raise RuntimeError(
            f"Official NSE CSV has no 'Symbol' column. Columns received: {df.columns.tolist()}"
        )

    symbols = (
        df["Symbol"].dropna().astype(str).str.strip().tolist()
    )
    # Preserve source order, while removing accidental duplicates.
    symbols = list(dict.fromkeys(symbol for symbol in symbols if symbol))

    if len(symbols) != 50:
        raise RuntimeError(
            f"Expected exactly 50 official Nifty 50 constituents; received {len(symbols)}."
        )

    print(f"Official constituent list loaded: {len(symbols)} symbols.", flush=True)
    return symbols


def fetch_indices():
    rows = []
    for name in INDEX_NAMES:
        try:
            result = nsepython.nse_get_index_quote(name)
            if isinstance(result, dict) and result.get("last") is not None:
                last = float(result["last"])
                change = result.get("percentChange")
                points = result.get("variation")
                rows.append({
                    "name": name,
                    "last": last,
                    "change": float(change) if change is not None else None,
                    "points": float(points) if points is not None else None,
                    "updated": result.get("previousDay", ""),
                })
            else:
                rows.append({
                    "name": name, "last": None, "change": None,
                    "points": None, "updated": ""
                })
        except Exception as exc:
            print(f"Index unavailable: {name}: {exc}", flush=True)
            rows.append({
                "name": name, "last": None, "change": None,
                "points": None, "updated": ""
            })
        time.sleep(0.2)
    return rows


def _number(value):
    try:
        if value is None or pd.isna(value):
            return None
        number = float(value)
        return number if number > 0 else None
    except (ValueError, TypeError):
        return None


def _extract_quote_from_nse_quote(symbol, result):
    """Normalize the older nse_quote() response into the dashboard format."""
    if not isinstance(result, dict):
        raise ValueError("Fallback quote response was not a dictionary")

    equity_rows = result.get("equityResponse") or []
    if not equity_rows or not isinstance(equity_rows[0], dict):
        raise ValueError("Fallback response has no equityResponse data")

    equity = equity_rows[0]
    order_book = equity.get("orderBook") or {}
    metadata = equity.get("metaData") or {}

    last = _number(order_book.get("lastPrice"))
    previous = _number(metadata.get("previousClose"))
    if last is None or previous is None:
        raise ValueError(
            f"Fallback response has invalid prices (last={last}, previous={previous})"
        )

    change = metadata.get("pChange")
    try:
        change = float(change) if change is not None else None
    except (ValueError, TypeError):
        change = None
    if change is None:
        change = ((last - previous) / previous) * 100.0

    return {
        "symbol": symbol,
        "last": last,
        "previous": previous,
        "change": change,
        "updated": metadata.get("lastUpdateTime") or result.get("timestamp", ""),
    }


def fetch_one_stock(symbol):
    """Try the NSE MCP quote endpoint, then fall back to nse_quote()."""
    last_error = None

    # Primary provider: NSE MCP quote endpoint.
    for attempt in range(2):
        try:
            result = nsepython.nse_mcp_cm_get_stock_quote(symbol)
            if not isinstance(result, dict):
                raise ValueError("Quote response was not a dictionary")

            stock = result.get("stock", result)
            if not isinstance(stock, dict):
                raise ValueError("Quote response did not contain stock data")

            returned_symbol = str(stock.get("symbol", symbol)).strip()
            if returned_symbol and returned_symbol != symbol:
                raise ValueError(f"Requested {symbol}, received {returned_symbol}")

            last = _number(stock.get("lastTradedPrice"))
            previous = _number(stock.get("preClosePrice"))
            change = stock.get("perChange")
            if last is None or previous is None:
                raise ValueError(
                    f"Missing/invalid price fields (last={last}, previous={previous})"
                )

            try:
                change = float(change) if change is not None else None
            except (ValueError, TypeError):
                change = None
            if change is None:
                change = ((last - previous) / previous) * 100.0

            return {
                "symbol": symbol,
                "last": last,
                "previous": previous,
                "change": change,
                "updated": stock.get("latestTimestamp") or result.get("updatedAt", ""),
            }
        except Exception as exc:
            last_error = exc
            print(
                f"Primary quote failed for {symbol} (attempt {attempt + 1}/2): {exc}",
                flush=True,
            )
            if attempt == 0:
                time.sleep(1)

    # Fallback provider: the older nse_quote() API uses a different response shape.
    try:
        print(f"Trying fallback nse_quote() for {symbol}...", flush=True)
        fallback = nsepython.nse_quote(symbol)
        return _extract_quote_from_nse_quote(symbol, fallback)
    except Exception as exc:
        last_error = exc
        print(f"Fallback quote failed for {symbol}: {exc}", flush=True)

    print(f"Quote unavailable for {symbol}: {last_error}", flush=True)
    return {
        "symbol": symbol,
        "last": None,
        "previous": None,
        "change": None,
        "updated": "",
    }


def fetch_stocks():
    symbols = fetch_official_nifty50_symbols()
    stocks = []

    for number, symbol in enumerate(symbols, start=1):
        print(f"Fetching stock {number}/50: {symbol}", flush=True)
        stocks.append(fetch_one_stock(symbol))
        # Keep the request rate modest to reduce the chance of rate limiting.
        time.sleep(0.25)

    missing = [stock["symbol"] for stock in stocks if stock["change"] is None]
    if missing:
        raise RuntimeError(
            f"Could not retrieve valid quotes for {len(missing)} of 50 Nifty 50 stocks: "
            f"{', '.join(missing)}. Dashboard was not sent to avoid showing an incomplete list."
        )

    if len(stocks) != 50 or len({s["symbol"] for s in stocks}) != 50:
        raise RuntimeError("Constituent validation failed; expected 50 unique stock quotes.")

    return sorted(stocks, key=lambda item: item["symbol"])


def _draw_header(draw, width, title, subtitle, now):
    white = "#f8fafc"
    muted = "#a8b3c7"
    draw.text((48, 30), title, font=font(38, True), fill=white)
    draw.text((50, 86), subtitle, font=font(20, True), fill="#7dd3fc")
    draw.text(
        (50, 122),
        f"{LABEL}  •  {now.strftime('%d %b %Y')}  •  Retrieved {now.strftime('%H:%M:%S IST')}",
        font=font(17), fill=muted,
    )
    draw.text(
        (50, 151),
        "Official NSE constituent list • NSEPython quotes • retrieval time may differ from exchange update time",
        font=font(13), fill=muted,
    )


def _breadth(stocks):
    valid = [s for s in stocks if s["change"] is not None]
    return {
        "valid": valid,
        "adv": sum(s["change"] > 0 for s in valid),
        "dec": sum(s["change"] < 0 for s in valid),
        "unch": sum(s["change"] == 0 for s in valid),
        "m2": sum(abs(s["change"]) >= 2 for s in valid),
        "m3": sum(abs(s["change"]) >= 3 for s in valid),
        "m5": sum(abs(s["change"]) >= 5 for s in valid),
    }


def create_images(indices, stocks, now):
    """Create two Telegram-friendly sheets: market overview and constituents."""
    width, height = 1600, 1900
    bg = "#08111f"
    panel = "#111e30"
    panel2 = "#15243a"
    white = "#f8fafc"
    muted = "#a8b3c7"
    green = "#35d07f"
    red = "#ff6878"
    amber = "#fbbf24"
    blue = "#38bdf8"
    border = "#2a3b52"

    summary = _breadth(stocks)
    adv, dec, unchanged = summary["adv"], summary["dec"], summary["unch"]
    total = max(adv + dec + unchanged, 1)

    # SHEET 1 — market overview and graphical advance/decline breadth.
    img = Image.new("RGB", (width, height), bg)
    d = ImageDraw.Draw(img)
    _draw_header(d, width, "NIFTY MARKET PULSE", "SHEET 1  /  MARKET OVERVIEW & BREADTH", now)

    # Advance / decline headline cards.
    cards = [
        ("ADVANCERS", adv, green),
        ("DECLINERS", dec, red),
        ("UNCHANGED", unchanged, amber),
        ("VALID QUOTES", f"{len(summary['valid'])}/50", blue),
    ]
    x0, y0, gap, cw, ch = 50, 205, 18, 355, 125
    for i, (label, value, color) in enumerate(cards):
        x = x0 + i * (cw + gap)
        d.rounded_rectangle((x, y0, x + cw, y0 + ch), radius=18, fill=panel, outline=border, width=2)
        d.rounded_rectangle((x, y0, x + 10, y0 + ch), radius=5, fill=color)
        d.text((x + 28, y0 + 19), label, font=font(18, True), fill=muted)
        d.text((x + 28, y0 + 51), str(value), font=font(42, True), fill=color)

    # Horizontal proportional breadth bar.
    bx, by, bw, bh = 65, 375, 1470, 45
    d.text((65, 340), "ADVANCE / DECLINE RATIO", font=font(22, True), fill=white)
    d.rounded_rectangle((bx, by, bx + bw, by + bh), radius=14, fill=panel2)
    usable = bw
    widths = [round(usable * adv / total), round(usable * dec / total)]
    widths.append(usable - widths[0] - widths[1])
    cursor = bx
    for val, segw, color in zip([adv, dec, unchanged], widths, [green, red, amber]):
        if segw > 0:
            d.rectangle((cursor, by, cursor + segw, by + bh), fill=color)
            cursor += segw
    # Legend and ratio.
    legend_y = 438
    legend = [(green, f"Advancers {adv} ({adv/total*100:.0f}%)"),
              (red, f"Decliners {dec} ({dec/total*100:.0f}%)"),
              (amber, f"Unchanged {unchanged} ({unchanged/total*100:.0f}%)")]
    lx = 65
    for color, text in legend:
        d.ellipse((lx, legend_y + 4, lx + 18, legend_y + 22), fill=color)
        d.text((lx + 28, legend_y), text, font=font(17, True), fill=white)
        lx += 480
    ratio = f"A/D ratio  {adv / dec:.2f}" if dec else ("A/D ratio  N/A" if adv == 0 else "A/D ratio  ∞")
    d.text((65, 480), ratio, font=font(18, True), fill=blue)

    # Movers distribution.
    d.text((50, 535), "MARKET MOVERS", font=font(24, True), fill=white)
    d.text((50, 570), "Number of Nifty 50 stocks moving beyond each threshold", font=font(16), fill=muted)
    movers = [("±2% or more", summary["m2"]), ("±3% or more", summary["m3"]), ("±5% or more", summary["m5"])]
    max_mover = max([v for _, v in movers] + [1])
    for i, (label, value) in enumerate(movers):
        yy = 615 + i * 66
        d.text((65, yy), label, font=font(18, True), fill=white)
        d.rounded_rectangle((330, yy + 2, 1320, yy + 31), radius=10, fill=panel2)
        barw = int(990 * value / max_mover)
        if barw:
            d.rounded_rectangle((330, yy + 2, 330 + barw, yy + 31), radius=10, fill=blue if i == 0 else (amber if i == 1 else red))
        d.text((1350, yy - 2), str(value), font=font(22, True), fill=white)

    # Index tiles, 4 columns x 4 rows.
    d.text((50, 835), "INDEX BOARD", font=font(24, True), fill=white)
    tile_w, tile_h, xgap, ygap = 360, 115, 20, 16
    for i, row in enumerate(indices[:16]):
        col, r = i % 4, i // 4
        x = 50 + col * (tile_w + xgap)
        y = 880 + r * (tile_h + ygap)
        d.rounded_rectangle((x, y, x + tile_w, y + tile_h), radius=14, fill=panel, outline=border, width=2)
        d.text((x + 18, y + 13), row["name"][:27], font=font(16, True), fill=muted)
        d.text((x + 18, y + 42), fmt(row["last"]), font=font(28, True), fill=white)
        chg = row["change"]
        color = muted if chg is None or chg == 0 else (green if chg > 0 else red)
        change_text = "N/A" if chg is None else f"{chg:+.2f}%"
        points_text = "" if row.get("points") is None else f"  ({row['points']:+,.2f} pts)"
        d.text((x + 18, y + 80), change_text + points_text, font=font(15, True), fill=color)

    d.text((50, 1410), "READING THE MARKET", font=font(20, True), fill=white)
    d.rounded_rectangle((50, 1450, 1550, 1580), radius=16, fill=panel, outline=border, width=2)
    if adv > dec:
        breadth_text = "Positive breadth: more constituents advanced than declined."
        breadth_color = green
    elif dec > adv:
        breadth_text = "Negative breadth: more constituents declined than advanced."
        breadth_color = red
    else:
        breadth_text = "Balanced breadth: advancers and decliners are equal."
        breadth_color = amber
    d.text((75, 1475), breadth_text, font=font(22, True), fill=breadth_color)
    d.text((75, 1520), f"Threshold counts can overlap. Valid stock quotes: {len(summary['valid'])}/50.", font=font(17), fill=muted)
    d.text((50, 1635), "Data note: market breadth is calculated from the 50 constituent percentage changes returned by the quote provider.", font=font(14), fill=muted)
    d.text((50, 1662), "For investment decisions, verify the exchange timestamp and official closing values.", font=font(14), fill=muted)
    img.save(OUT_OVERVIEW)

    # SHEET 2 — all constituents, sorted from strongest to weakest, with bars.
    img2 = Image.new("RGB", (width, height), bg)
    d2 = ImageDraw.Draw(img2)
    _draw_header(d2, width, "NIFTY 50 STOCK TRACKER", "SHEET 2  /  ALL CONSTITUENTS RANKED BY DAILY CHANGE", now)
    ordered = sorted(stocks, key=lambda s: (s["change"] is None, -(s["change"] or 0)))
    valid_changes = [abs(s["change"]) for s in ordered if s["change"] is not None]
    max_abs = max(valid_changes + [1.0])
    d2.text((50, 205), "RANK", font=font(15, True), fill=muted)
    d2.text((125, 205), "SYMBOL", font=font(15, True), fill=muted)
    d2.text((400, 205), "LAST PRICE", font=font(15, True), fill=muted)
    d2.text((650, 205), "DAILY CHANGE", font=font(15, True), fill=muted)
    d2.text((1040, 205), "RELATIVE MOVE", font=font(15, True), fill=muted)
    d2.text((1450, 205), "STATUS", font=font(15, True), fill=muted)
    row_y, row_h = 242, 30
    for i, stock in enumerate(ordered):
        yy = row_y + i * row_h
        if i % 2 == 0:
            d2.rounded_rectangle((45, yy - 2, 1555, yy + row_h - 2), radius=5, fill="#101c2d")
        chg = stock["change"]
        color = muted if chg is None or chg == 0 else (green if chg > 0 else red)
        d2.text((58, yy + 3), f"{i+1:02d}", font=font(15, True), fill=muted)
        d2.text((125, yy + 3), stock["symbol"], font=font(16, True), fill=white)
        d2.text((400, yy + 3), fmt(stock["last"]), font=font(16), fill=white)
        d2.text((650, yy + 3), "N/A" if chg is None else f"{chg:+.2f}%", font=font(16, True), fill=color)
        # Centered zero line: green bars right, red bars left.
        center, half = 1230, 150
        d2.line((center, yy + 4, center, yy + 23), fill="#52647c", width=2)
        if chg is not None and chg != 0:
            barw = max(2, int(half * min(abs(chg) / max_abs, 1)))
            if chg > 0:
                d2.rounded_rectangle((center + 3, yy + 5, center + 3 + barw, yy + 22), radius=4, fill=green)
            else:
                d2.rounded_rectangle((center - 3 - barw, yy + 5, center - 3, yy + 22), radius=4, fill=red)
        status = "GAIN" if chg is not None and chg > 0 else ("LOSS" if chg is not None and chg < 0 else "FLAT" if chg == 0 else "N/A")
        d2.text((1450, yy + 4), status, font=font(13, True), fill=color)

    # Top and bottom performers summary panels.
    winners = sorted([s for s in stocks if s["change"] is not None], key=lambda s: s["change"], reverse=True)
    losers = list(reversed(winners))
    box_y = 1795
    d2.rounded_rectangle((50, box_y, 780, box_y + 75), radius=12, fill=panel, outline=border, width=2)
    d2.rounded_rectangle((820, box_y, 1550, box_y + 75), radius=12, fill=panel, outline=border, width=2)
    if winners:
        d2.text((70, box_y + 10), f"TOP GAINER  {winners[0]['symbol']}  {winners[0]['change']:+.2f}%", font=font(19, True), fill=green)
        d2.text((840, box_y + 10), f"TOP LOSER  {losers[0]['symbol']}  {losers[0]['change']:+.2f}%", font=font(19, True), fill=red)
    d2.text((70, box_y + 43), f"Stocks rising: {adv}  •  falling: {dec}  •  unchanged: {unchanged}", font=font(14), fill=muted)
    d2.text((840, box_y + 43), "Bars show relative percentage move; green = gain, red = loss.", font=font(14), fill=muted)
    img2.save(OUT_STOCKS)

    return {
        "advancers": adv, "decliners": dec, "unchanged": unchanged,
        "missing": len(stocks) - len(summary["valid"]),
        "m2": summary["m2"], "m3": summary["m3"], "m5": summary["m5"],
        "top_gainer": max((s for s in stocks if s["change"] is not None), key=lambda s: s["change"], default=None),
        "top_loser": min((s for s in stocks if s["change"] is not None), key=lambda s: s["change"], default=None),
    }

def send_telegram(image_path, caption):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendPhoto"

    with open(image_path, "rb") as photo:
        response = requests.post(
            url,
            data={"chat_id": chat_id, "caption": caption},
            files={"photo": (os.path.basename(image_path), photo, "image/png")},
            timeout=45,
        )

    try:
        result = response.json()
    except ValueError:
        raise RuntimeError(f"Telegram returned a non-JSON response: HTTP {response.status_code}")
    if response.status_code >= 400 or not result.get("ok"):
        raise RuntimeError(f"Telegram send failed for {image_path}: {result}")
    print(f"Dashboard sheet sent to Telegram: {image_path}", flush=True)

def main():
    if MODE not in ("open", "close"):
        raise SystemExit("Mode must be 'open' or 'close'.")

    now = dt.datetime.now(IST)
    print("Snapshot mode:", MODE, flush=True)
    print("Retrieval time:", now.isoformat(), flush=True)

    indices = fetch_indices()
    stocks = fetch_stocks()

    if len(stocks) != 50:
        raise RuntimeError("Insufficient constituent coverage; expected exactly 50 stocks.")

    summary = create_images(indices, stocks, now)
    top_gainer = summary["top_gainer"]
    top_loser = summary["top_loser"]
    caption1 = (
        f"📊 Nifty Market Dashboard — {LABEL} | SHEET 1/2\n"
        f"Generated: {now.strftime('%d %b %Y, %H:%M:%S IST')}\n"
        f"Advance/Decline: {summary['advancers']}/{summary['decliners']} | "
        f"Unchanged: {summary['unchanged']} | Valid quotes: {len(stocks)}/50\n"
        f"Movers: ±2% {summary['m2']} | ±3% {summary['m3']} | ±5% {summary['m5']}\n"
        "Sheet 1: market overview, index board and graphical breadth."
    )
    send_telegram(OUT_OVERVIEW, caption1)
    time.sleep(1)
    caption2 = (
        f"📈 Nifty Market Dashboard — {LABEL} | SHEET 2/2\n"
        f"Generated: {now.strftime('%d %b %Y, %H:%M:%S IST')}\n"
        f"Top gainer: {top_gainer['symbol']} {top_gainer['change']:+.2f}%\n" if top_gainer else
        f"📈 Nifty Market Dashboard — {LABEL} | SHEET 2/2\nGenerated: {now.strftime('%d %b %Y, %H:%M:%S IST')}\n"
    )
    if top_loser:
        caption2 += f"Top loser: {top_loser['symbol']} {top_loser['change']:+.2f}%\n"
    caption2 += "Sheet 2: all 50 constituents ranked by daily change with visual gain/loss bars."
    send_telegram(OUT_STOCKS, caption2)


if __name__ == "__main__":
    main()
