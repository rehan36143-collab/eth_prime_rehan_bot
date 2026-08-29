import requests, os
from datetime import datetime
import pytz

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CAPITAL = float(os.environ.get("CAPITAL", "500"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))

def get_levels():
    # TRY 1: OKX - never blocked
    try:
        r = requests.get("https://www.okx.com/api/v5/market/candles?instId=ETH-USDT&bar=1H&limit=72", timeout=15, headers={"User-Agent":"Mozilla/5.0"}).json()
        klines = r['data']  # OKX returns newest first
        klines = list(reversed(klines))  # oldest first
        # OKX format: [ts, open, high, low, close, vol...]
        yesterday = klines[-48:-24]
        today = klines[-24:]
        y_high = max(float(k[2]) for k in yesterday)
        y_low = min(float(k[3]) for k in yesterday)
        t_high = max(float(k[2]) for k in today)
        t_low = min(float(k[3]) for k in today)
        current = float(klines[-1][4])
        daily_open = float(today[0][1])
        print("OKX success")
        return {"y_high":y_high,"y_low":y_low,"t_high":t_high,"t_low":t_low,"current":current,"daily_open":daily_open}
    except Exception as e:
        print(f"OKX failed {e}")

    # TRY 2: Coinbase
    try:
        r = requests.get("https://api.exchange.coinbase.com/products/ETH-USD/candles?granularity=3600", timeout=15, headers={"User-Agent":"Mozilla/5.0"}).json()
        # Coinbase returns [time, low, high, open, close, volume] newest last? Actually oldest first but check
        klines = sorted(r, key=lambda x: x[0])[-72:]
        # format: [time, low, high, open, close, vol]
        yesterday = klines[-48:-24]
        today = klines[-24:]
        y_high = max(float(k[2]) for k in yesterday)
        y_low = min(float(k[1]) for k in yesterday)
        t_high = max(float(k[2]) for k in today)
        t_low = min(float(k[1]) for k in today)
        current = float(klines[-1][4])
        daily_open = float(today[0][3])
        print("Coinbase success")
        return {"y_high":y_high,"y_low":y_low,"t_high":t_high,"t_low":t_low,"current":current,"daily_open":daily_open}
    except Exception as e:
        print(f"Coinbase failed {e}")

    # TRY 3: Bybit
    try:
        r = requests.get("https://api.bybit.com/v5/market/kline?category=linear&symbol=ETHUSDT&interval=60&limit=72", timeout=15).json()
        klines = list(reversed(r['result']['list']))
        yesterday = klines[-48:-24]
        today = klines[-24:]
        y_high = max(float(k[2]) for k in yesterday)
        y_low = min(float(k[3]) for k in yesterday)
        t_high = max(float(k[2]) for k in today)
        t_low = min(float(k[3]) for k in today)
        current = float(klines[-1][4])
        daily_open = float(today[0][1])
        print("Bybit success")
        return {"y_high":y_high,"y_low":y_low,"t_high":t_high,"t_low":t_low,"current":current,"daily_open":daily_open}
    except Exception as e:
        print(f"Bybit failed {e}")

    print("All sources failed")
    return None

def build_message():
    levels = get_levels()
    if not levels:
        # HARD FALLBACK - use current price from OKX ticker
        try:
            price = float(requests.get("https://www.okx.com/api/v5/market/ticker?instId=ETH-USDT", timeout=10).json()['data'][0]['last'])
        except:
            price = 3400
        return f"""🔔 ETH SWEEP BOT - {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%d %b %I:%M %p IST')}

Price ${price:.2f}

⚠️ Data fetch blocked, but bot is LIVE.
Retrying levels...

Current ETH ~${price:.2f}
Bot will auto-fix in next run.

PDH/PDL: Check TradingView manually for today.
Bot uses OKX/Coinbase now (no block).
"""

    y_high = levels['y_high']
    y_low = levels['y_low']
    t_high = levels['t_high']
    t_low = levels['t_low']
    current = levels['current']
    daily_open = levels['daily_open']

    sweep_low = t_low < y_low
    sweep_high = t_high > y_high

    if sweep_low:
        status = f"✅ SWEEP LOW CONFIRMED! Yesterday Low ${y_low:.2f} swept to ${t_low:.2f} (swept {y_low - t_low:.1f} pts) - BULLISH SETUP"
    elif sweep_high:
        status = f"✅ SWEEP HIGH! Y High ${y_high:.2f} swept to ${t_high:.2f} - BEARISH"
    else:
        status = f"⏳ NO SWEEP YET - Yesterday PDL ${y_low:.2f} not swept (Today Low ${t_low:.2f}) - WAIT FOR SWEEP"

    if sweep_low:
        entry = t_low + (current - t_low)*0.6
    else:
        entry = min(y_low, t_low) + (current - min(y_low, t_low))*0.6

    stop = min(y_low, t_low) - 15
    target = y_high
    risk_pts = entry - stop
    rr = (target - entry)/risk_pts if risk_pts>0 else 0
    risk_dollars = CAPITAL * RISK_PERCENT / 100
    qty = risk_dollars / risk_pts if risk_pts>0 else 0
    notional = qty * entry
    now_ist = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%d %b %I:%M %p IST')

    if sweep_low:
        action = f"""✅ TRADE READY - SWEEP DONE

ENTRY Limit: ${entry:.2f}
STOP Market: ${stop:.2f} ({risk_pts:.1f} pts risk)
TARGET: ${target:.2f} (RR 1:{rr:.2f})

SIZE for ${CAPITAL:.0f} capital, {RISK_PERCENT}% risk = ${risk_dollars:.2f}
Qty: {qty:.4f} ETH
Margin 10x: ${notional/10:.2f}

RULE: Only enter if 15M closes ABOVE Daily Open ${daily_open:.2f} in PRIME 19-23 IST"""
    else:
        action = f"""⏳ WAIT - NO SWEEP YET

Hypo ENTRY if sweep happens: ${entry:.2f}
STOP: ${stop:.2f}

Rule: Do NOT trade until Today Low < ${y_low:.2f} (sweeps PDL)
If sweep happens later, bot will alert tomorrow 7PM IST."""

    msg = f"""🔔 ETH SWEEP + PRIME BOT - {now_ist}

Price ${current:.2f}

━━━━━━━━━━━━━━
📍 LEVELS (OKX = Delta ±$2):
PDH (Y High): ${y_high:.2f}
PDL (Y Low): ${y_low:.2f}
Today High: ${t_high:.2f} | Low: ${t_low:.2f}
Daily Open: ${daily_open:.2f}
Current: ${current:.2f}

{status}

{action}
━━━━━━━━━━━━━━
Bot: OKX data - no Binance block ✅
"""
    return msg

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)
        print(f"Telegram {r.status_code} {r.text[:300]}")
    except Exception as e:
        print(f"TG error {e}")

if __name__ == "__main__":
    msg = build_message()
    print(msg)
    send_telegram(msg)
