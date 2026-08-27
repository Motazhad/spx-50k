from datetime import datetime
from zoneinfo import ZoneInfo

import yfinance as yf
from flask import Flask, jsonify, render_template

app = Flask(__name__)

SYMBOL = "^SPX"
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


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def dashboard():
    now_ny = datetime.now(NY)
    try:
        ticker = yf.Ticker(SYMBOL)

        price = None
        change = None
        change_pct = None
        try:
            fi = ticker.fast_info
            price = safe_num(fi.get("last_price"))
            prev_close = safe_num(fi.get("previous_close"))
            if price is not None and prev_close:
                change = price - prev_close
                change_pct = (change / prev_close) * 100
        except Exception:
            pass

        expirations = list(ticker.options or [])
        today_str = now_ny.date().isoformat()

        if today_str not in expirations:
            return jsonify({
                "ok": True,
                "spx_price": price,
                "change": change,
                "change_pct": change_pct,
                "expiration": None,
                "calls": [],
                "puts": [],
                "market_time": now_ny.isoformat(),
                "message": "لا يوجد انتهاء SPX 0DTE متاح لتاريخ نيويورك الحالي."
            })

        chain = ticker.option_chain(today_str)

        def process(df, side):
            out = []
            if df is None or df.empty:
                return out

            for _, row in df.iterrows():
                vol = safe_num(row.get("volume"))
                if vol is None or vol < MIN_VOLUME:
                    continue

                last = safe_num(row.get("lastPrice"))
                bid = safe_num(row.get("bid"))
                ask = safe_num(row.get("ask"))
                mid = None
                if bid is not None and ask is not None and bid >= 0 and ask >= 0:
                    mid = round((bid + ask) / 2, 2)

                out.append({
                    "side": side,
                    "contract": row.get("contractSymbol"),
                    "strike": safe_num(row.get("strike")),
                    "price": last if last is not None else mid,
                    "last": last,
                    "bid": bid,
                    "ask": ask,
                    "volume": int(vol),
                    "open_interest": int(safe_num(row.get("openInterest")) or 0),
                })

            return sorted(out, key=lambda x: x["volume"], reverse=True)

        calls = process(chain.calls, "CALL")
        puts = process(chain.puts, "PUT")

        return jsonify({
            "ok": True,
            "spx_price": price,
            "change": change,
            "change_pct": change_pct,
            "expiration": today_str,
            "calls": calls,
            "puts": puts,
            "market_time": now_ny.isoformat(),
            "message": None,
        })

    except Exception as e:
        return jsonify({
            "ok": False,
            "error": str(e),
            "market_time": now_ny.isoformat(),
        }), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000, debug=False)
