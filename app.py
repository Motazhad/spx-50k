from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf
from flask import Flask, jsonify, render_template

app = Flask(__name__)

# Yahoo uses ^GSPC reliably for the S&P 500 index quote.
PRICE_SYMBOL = "^GSPC"
# Keep ^SPX for the option chain because it is already returning the SPX chain in this project.
OPTIONS_SYMBOL = "^SPX"
MIN_VOLUME = 50000
NY = ZoneInfo("America/New_York")


def safe_num(v):
    try:
        if v is None:
            return None
        if hasattr(v, "item"):
            v = v.item()
        if v != v:
            return None
        return float(v)
    except Exception:
        return None


def get_spx_price():
    """Get the latest available S&P 500 index price with fallbacks."""
    t = yf.Ticker(PRICE_SYMBOL)

    # 1) fast_info
    try:
        fi = t.fast_info
        price = safe_num(fi.get("last_price"))
        prev = safe_num(fi.get("previous_close"))
        if price is not None:
            change = price - prev if prev else None
            change_pct = (change / prev) * 100 if change is not None and prev else None
            return price, change, change_pct
    except Exception:
        pass

    # 2) intraday history fallback
    try:
        hist = t.history(period="1d", interval="1m", auto_adjust=False, prepost=False)
        if hist is not None and not hist.empty:
            price = safe_num(hist["Close"].dropna().iloc[-1])
            prev = None
            try:
                daily = t.history(period="5d", interval="1d", auto_adjust=False)
                closes = daily["Close"].dropna()
                if len(closes) >= 2:
                    prev = safe_num(closes.iloc[-2])
            except Exception:
                pass
            change = price - prev if price is not None and prev else None
            change_pct = (change / prev) * 100 if change is not None and prev else None
            return price, change, change_pct
    except Exception:
        pass

    return None, None, None


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def dashboard():
    now_ny = datetime.now(NY)

    try:
        price, change, change_pct = get_spx_price()

        ticker = yf.Ticker(OPTIONS_SYMBOL)
        expirations = list(ticker.options or [])
        today = now_ny.date().isoformat()

        if today not in expirations:
            return jsonify({
                "ok": True,
                "spx_price": price,
                "change": change,
                "change_pct": change_pct,
                "expiration": None,
                "calls": [],
                "puts": [],
                "top5": [],
                "top5_calls": 0,
                "top5_puts": 0,
                "market_time": now_ny.isoformat(),
                "message": "لا يوجد انتهاء SPX 0DTE متاح اليوم."
            })

        chain = ticker.option_chain(today)

        def process(df, side):
            out = []
            if df is None or df.empty:
                return out

            for _, row in df.iterrows():
                vol = safe_num(row.get("volume"))
                vol = int(vol) if vol is not None else 0

                last = safe_num(row.get("lastPrice"))
                bid = safe_num(row.get("bid"))
                ask = safe_num(row.get("ask"))

                mid = None
                if bid is not None and ask is not None:
                    mid = round((bid + ask) / 2, 2)

                out.append({
                    "side": side,
                    "strike": safe_num(row.get("strike")),
                    "price": last if last is not None else mid,
                    "volume": vol,
                    "open_interest": int(safe_num(row.get("openInterest")) or 0),
                })

            return sorted(out, key=lambda x: x["volume"], reverse=True)

        # Full CALL/PUT lists: no 50K filter.
        calls = process(chain.calls, "CALL")[:10]
        puts = process(chain.puts, "PUT")[:10]

        # Strongest 5 only: contracts with volume >= 50K.
        eligible_top = [x for x in (calls + puts) if x["volume"] >= MIN_VOLUME]
        top5 = sorted(eligible_top, key=lambda x: x["volume"], reverse=True)[:5]
        top5_calls = sum(1 for x in top5 if x["side"] == "CALL")
        top5_puts = sum(1 for x in top5 if x["side"] == "PUT")

        return jsonify({
            "ok": True,
            "spx_price": price,
            "change": change,
            "change_pct": change_pct,
            "expiration": today,
            "calls": calls,
            "puts": puts,
            "top5": top5,
            "top5_calls": top5_calls,
            "top5_puts": top5_puts,
            "market_time": now_ny.isoformat(),
            "message": None
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
