import requests, os
from datetime import datetime
import pytz

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CAPITAL = float(os.environ.get("CAPITAL", "500"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))

def get_levels():
    # TRY CRYPTOCOMPARE - most permissive, never blocks GitHub
    try:
        r = requests.get("https://min-api.cryptocompare.com/data/v2/histohour?fsym=ETH&tsym=USD&limit=72", timeout=15).json()
        data = r['Data']['Data']
        # data: oldest first, each has high, low, open, close
        klines = data
        yesterday = klines[-48:-24]
        today = klines[-24:]
        y_high = max(float(k['high']) for k in yesterday)
        y_low = min(float(k['low']) for k in yesterday)
        t_high = max(float(k['high']) for k in today)
        t_low = min(float(k['low']) for k in today)
        current = float(klines[-1]['close'])
        daily_open = float(today[0]['open'])
        print(f"CryptoCompare success ETH ${current}")
        return {"y_high":y_high,"y_low":y_low,"t_high":t_high,"t_low":t_low,"current":current,"daily_open":daily_open,"source":"CryptoCompare"}
    except Exception as e:
        print(f"CryptoCompare failed {e}")

    # TRY 2: OKX public
    try:
        r = requests.get("https://www.okx.com/api/v5/market/candles?instId=ETH-USDT&bar=1H&limit=72", timeout=12, headers={"User-Agent":"Mozilla/5.0","Accept":"application/json"}).json()
        klines = list(reversed(r['data']))
        yesterday = klines[-48:-24]
        today = klines[-24:]
        y_high = max(float(k[2]) for k in yesterday)
        y_low = min(float(k[3]) for k in yesterday)
        t_high = max(float(k[2]) for k in today)
        t_low = min(float(k[3]) for k in today)
        current = float(klines[-1][4])
        daily_open = float(today[0][1])
        return {"y_high":y_high,"y_low":y_low,"t_high":t_high,"t_low":t_low,"current":current,"daily_open":daily_open,"source":"OKX"}
    except Exception as e:
        print(f"OKX failed {e}")

    # TRY 3: Use coingecko simple price + estimate levels from % (last resort, always works)
    try:
        r = requests.get("https://api.coingecko.com/api/v3/simple/price?ids=ethereum&vs_currencies=usd", timeout=10).json()
        current = float(r['ethereum']['usd'])
        # Estimate yesterday range as ±2% if no candle data
        y_high = current * 1.025
        y_low = current * 0.975
        t_high = current * 1.01
        t_low = current * 0.99
        daily_open = current
        print(f"Coingecko fallback price {current}")
        return {"y_high":y_high,"y_low":y_low,"t_high":t_high,"t_low":t_low,"current":current,"daily_open":daily_open,"source":"Coingecko-Fallback"}
    except Exception as e:
        print(f"All failed {e}")
        return None

def build_message():
    levels = get_levels()
    if not levels:
        # Absolute final fallback - bot still sends message so you know it's alive
        price = 3400
        try:
            price = float(requests.get("https://min-api.cryptocompare.com/data/price?fsym=ETH&tsyms=USD", timeout=10).json()['USD'])
        except:
            pass
        return f"🔔 ETH BOT LIVE - {datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%d %b %I:%M %p IST')}\nPrice ~${price:.2f}\nBot alive but all APIs blocked. Retrying 7PM. Source: CryptoCompare Price"

    y_high = levels['y_high']
    y_low = levels['y_low']
    t_high = levels['t_high']
    t_low = levels['t_low']
    current = levels['current']
    daily_open = levels['daily_open']
    source = levels.get('source','')

    sweep_low = t_low < y_low
    sweep_high = t_high > y_high

    if sweep_low:
        status = f"✅ SWEEP LOW CONFIRMED! Y Low ${y_low:.2f} swept to ${t_low:.2f} ({y_low - t_low:.1f} pts) - BULLISH"
    elif sweep_high:
        status = f"✅ SWEEP HIGH! Y High ${y_high:.2f} swept"
    else:
        status = f"⏳ NO SWEEP YET - PDL ${y_low:.2f} not swept (Today Low ${t_low:.2f}) - WAIT"

    entry = (t_low + (current - t_low)*0.6) if sweep_low else (min(y_low,t_low) + (current - min(y_low,t_low))*0.6)
    stop = min(y_low,t_low) - 15
    target = y_high
    risk_pts = entry - stop
    rr = (target - entry)/risk_pts if risk_pts>0 else 0
    risk_dollars = CAPITAL * RISK_PERCENT / 100
    qty = risk_dollars / risk_pts if risk_pts>0 else 0
    notional = qty * entry
    now_ist = datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%d %b %I:%M %p IST')

    if sweep_low:
        action = f"✅ TRADE READY\nENTRY ${entry:.2f}\nSTOP ${stop:.2f} ({risk_pts:.1f} pts)\nTARGET ${target:.2f} RR 1:{rr:.2f}\nQty {qty:.4f} ETH Margin 10x ${notional/10:.2f}\nRule: 15M close above Open ${daily_open:.2f}"
    else:
        action = f"⏳ WAIT\nHypo ENTRY ${entry:.2f} STOP ${stop:.2f}\nWait for Today Low < ${y_low:.2f}"

    msg = f"""🔔 ETH SWEEP BOT - {now_ist}

Price ${current:.2f} (Src: {source})

━━━━━━━━━━━━━━
PDH ${y_high:.2f} | PDL ${y_low:.2f}
Today H ${t_high:.2f} L ${t_low:.2f}
Open ${daily_open:.2f} | Current ${current:.2f}

{status}

{action}
━━━━━━━━━━━━━━
Delta: Check 15M close
"""
    return msg

def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)
        print(f"TG {r.status_code}")
    except Exception as e:
        print(e)

if __name__ == "__main__":
    m = build_message()
    print(m)
    send_telegram(m)
