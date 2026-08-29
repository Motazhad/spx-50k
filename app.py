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


def get_price_action():
    """
    Simple 15m SPX price-action confirmation.
    Uses the latest Yahoo ^GSPC intraday candles (same delay as the dashboard).
    """
    try:
        t = yf.Ticker(PRICE_SYMBOL)
        hist = t.history(period="5d", interval="15m", auto_adjust=False, prepost=False)
        if hist is None or hist.empty or len(hist) < 25:
            return {
                "bias": "NEUTRAL", "score": 50, "label": "PRICE ACTION غير كافي",
                "reason": "لا توجد شموع 15 دقيقة كافية.", "ema20": None,
                "session_open": None, "support": None, "resistance": None
            }

        h = hist.dropna(subset=["Close"]).copy()
        close = float(h["Close"].iloc[-1])
        open_ = float(h["Open"].iloc[-1])
        high = float(h["High"].iloc[-1])
        low = float(h["Low"].iloc[-1])

        ema20 = float(h["Close"].ewm(span=20, adjust=False).mean().iloc[-1])

        # Latest trading day/session open
        idx_dates = h.index.date
        latest_day = idx_dates[-1]
        day_mask = [d == latest_day for d in idx_dates]
        day = h.loc[day_mask]
        session_open = float(day["Open"].iloc[0]) if not day.empty else None

        # Levels from candles BEFORE the current candle, so the current candle
        # can break/reject them instead of redefining them.
        prior = h.iloc[:-1]
        recent = prior.tail(8)
        support = float(recent["Low"].min()) if not recent.empty else None
        resistance = float(recent["High"].max()) if not recent.empty else None

        prev_close = float(h["Close"].iloc[-2])
        last3 = h["Close"].tail(4).pct_change().dropna()
        momentum = float(last3.sum()) if len(last3) else 0.0

        bull = 0
        bear = 0
        reasons_bull = []
        reasons_bear = []

        if close > ema20:
            bull += 25; reasons_bull.append("فوق EMA20")
        elif close < ema20:
            bear += 25; reasons_bear.append("تحت EMA20")

        if session_open is not None:
            if close > session_open:
                bull += 20; reasons_bull.append("فوق افتتاح الجلسة")
            elif close < session_open:
                bear += 20; reasons_bear.append("تحت افتتاح الجلسة")

        if close > prev_close:
            bull += 10
        elif close < prev_close:
            bear += 10

        if momentum > 0:
            bull += 15; reasons_bull.append("زخم 15m صاعد")
        elif momentum < 0:
            bear += 15; reasons_bear.append("زخم 15m هابط")

        tol = close * 0.0006  # ~0.06%

        event = "NONE"

        if resistance is not None and close > resistance:
            bull += 30
            event = "BREAKOUT"
            reasons_bull.insert(0, "اختراق مقاومة")
        elif resistance is not None and high >= resistance - tol and close < resistance and close < open_:
            bear += 25
            event = "RESISTANCE_REJECTION"
            reasons_bear.insert(0, "رفض مقاومة")

        if support is not None and close < support:
            bear += 30
            event = "BREAKDOWN"
            reasons_bear.insert(0, "كسر دعم")
        elif support is not None and low <= support + tol and close > support and close > open_:
            bull += 25
            event = "SUPPORT_REJECTION"
            reasons_bull.insert(0, "ارتداد من دعم")

        total = bull + bear
        score = round((bull / total) * 100) if total else 50

        if bull >= bear + 20:
            bias = "BULLISH"
            label = "🟢 CALL PRICE CONFIRMATION"
            reason = " · ".join(reasons_bull[:3]) or "السعر يميل للصعود"
        elif bear >= bull + 20:
            bias = "BEARISH"
            label = "🔴 PUT PRICE CONFIRMATION"
            reason = " · ".join(reasons_bear[:3]) or "السعر يميل للهبوط"
        else:
            bias = "NEUTRAL"
            label = "🟡 PRICE ACTION MIXED"
            reason = "السعر غير حاسم حاليًا"

        return {
            "bias": bias,
            "score": score,
            "label": label,
            "reason": reason,
            "event": event,
            "ema20": round(ema20, 2),
            "session_open": round(session_open, 2) if session_open is not None else None,
            "support": round(support, 2) if support is not None else None,
            "resistance": round(resistance, 2) if resistance is not None else None,
        }
    except Exception as e:
        return {
            "bias": "NEUTRAL", "score": 50, "label": "PRICE ACTION غير متاح",
            "reason": str(e), "event": "NONE", "ema20": None,
            "session_open": None, "support": None, "resistance": None
        }


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/dashboard")
def dashboard():
    now_ny = datetime.now(NY)

    try:
        price, change, change_pct = get_spx_price()
        price_action = get_price_action()

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
                "price_action": price_action,
                "flow": {"bias": "NEUTRAL", "call_volume": 0, "put_volume": 0, "conflict": False, "message": "لا توجد عقود 0DTE اليوم."},
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

        top_call_volume = sum(x["volume"] for x in top5 if x["side"] == "CALL")
        top_put_volume = sum(x["volume"] for x in top5 if x["side"] == "PUT")

        if top_call_volume > top_put_volume * 1.10:
            flow_bias = "CALL"
        elif top_put_volume > top_call_volume * 1.10:
            flow_bias = "PUT"
        else:
            flow_bias = "MIXED"

        pa_bias = price_action.get("bias", "NEUTRAL")
        conflict = (
            (flow_bias == "CALL" and pa_bias == "BEARISH") or
            (flow_bias == "PUT" and pa_bias == "BULLISH")
        )

        if conflict and flow_bias == "CALL":
            flow_message = "⚠️ لا تغرك قوة الكول: السعر يؤكد هبوطًا."
        elif conflict and flow_bias == "PUT":
            flow_message = "⚠️ لا تغرك قوة البوت: السعر يؤكد صعودًا."
        elif flow_bias == "CALL" and pa_bias == "BULLISH":
            flow_message = "✅ الكول متوافق مع حركة السعر."
        elif flow_bias == "PUT" and pa_bias == "BEARISH":
            flow_message = "✅ البوت متوافق مع حركة السعر."
        else:
            flow_message = "🟡 لا يوجد توافق واضح بين السيولة والسعر."

        flow = {
            "bias": flow_bias,
            "call_volume": top_call_volume,
            "put_volume": top_put_volume,
            "conflict": conflict,
            "message": flow_message
        }

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
            "price_action": price_action,
            "flow": flow,
            "market_time": now_ny.isoformat(),
            "message": None
        })

    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
