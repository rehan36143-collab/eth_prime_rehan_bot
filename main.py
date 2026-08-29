import requests, re, os
from datetime import datetime
import pytz

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")
CAPITAL = float(os.environ.get("CAPITAL", "500"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))

# Use binance.vision domain - not blocked on GitHub US
BINANCE_BASE = "https://data-api.binance.vision"

def get_levels():
    try:
        url = f"{BINANCE_BASE}/api/v3/klines?symbol=ETHUSDT&interval=1h&limit=72"
        resp = requests.get(url, timeout=15).json()
        if isinstance(resp, dict):
            print(f"Binance error: {resp}")
            # fallback to Bybit
            print("Trying Bybit fallback")
            bybit = requests.get("https://api.bybit.com/v5/market/kline?category=linear&symbol=ETHUSDT&interval=60&limit=72", timeout=15).json()
            klines_raw = bybit['result']['list']  # newest first
            klines_raw = list(reversed(klines_raw))
            # Convert to binance format: [openTime, open, high, low, close...]
            klines = [[0, k[1], k[2], k[3], k[4], 0] for k in klines_raw]
        else:
            klines = resp

        if len(klines) < 48:
            return None
            
        yesterday = klines[-48:-24]
        today = klines[-24:]
        
        y_high = max(float(k[2]) for k in yesterday)
        y_low = min(float(k[3]) for k in yesterday)
        t_high = max(float(k[2]) for k in today)
        t_low = min(float(k[3]) for k in today)
        current = float(klines[-1][4])
        daily_open = float(today[0][1])
        
        return {
            "y_high": y_high, "y_low": y_low,
            "t_high": t_high, "t_low": t_low,
            "current": current, "daily_open": daily_open,
        }
    except Exception as e:
        print(f"levels error {e}")
        import traceback
        traceback.print_exc()
        return None

def get_data():
    try:
        bin_price = float(requests.get(f"{BINANCE_BASE}/api/v3/ticker/price?symbol=ETHUSDT", timeout=10).json()['price'])
        cb_price = float(requests.get("https://api.coinbase.com/v2/prices/ETH-USD/spot", timeout=10).json()['data']['amount'])
        premium = cb_price - bin_price
    except:
        bin_price, cb_price, premium = 0,0,0
    try:
        funding = 0.01
        chg = float(requests.get(f"{BINANCE_BASE}/api/v3/ticker/24hr?symbol=ETHUSDT", timeout=10).json()['priceChangePercent'])
    except:
        funding, chg = 0,0
    return bin_price, cb_price, premium, funding, chg, None

def build_message():
    levels = get_levels()
    bin_price, cb_price, premium, funding, chg, etf_flow = get_data()
    if not levels:
        return f"❌ Error fetching levels - fallback price ${bin_price:.2f} - Will retry"
    
    y_high = levels['y_high']
    y_low = levels['y_low']
    t_high = levels['t_high']
    t_low = levels['t_low']
    current = levels['current']
    daily_open = levels['daily_open']
    
    sweep_low_happened = t_low < y_low
    sweep_high_happened = t_high > y_high
    
    if sweep_low_happened:
        sweep_status = f"✅ SWEEP LOW! Y Low ${y_low:.2f} -> Today Low ${t_low:.2f} ({y_low - t_low:.1f} pts) - Bullish trap done"
    elif sweep_high_happened:
        sweep_status = f"✅ SWEEP HIGH! Y High ${y_high:.2f} -> ${t_high:.2f} - Bearish"
    else:
        sweep_status = f"⏳ NO SWEEP YET - PDL ${y_low:.2f} not swept (Today Low ${t_low:.2f}) - WAIT"
    
    score=3
    entry = min(y_low, t_low) + (current - min(y_low, t_low))*0.6
    if sweep_low_happened:
        entry = t_low + (current - t_low)*0.6
    stop = min(y_low, t_low) - 15
    target = y_high
    risk_pts = entry - stop
    rr = (target - entry)/risk_pts if risk_pts>0 else 0
    risk_dollars = CAPITAL * RISK_PERCENT / 100
    qty = risk_dollars / risk_pts if risk_pts>0 else 0
    notional = qty * entry
    now_ist=datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%d %b %I:%M %p IST')
    
    if sweep_low_happened:
        action = f"\n✅ TRADE READY - SWEEP CONFIRMED\nENTRY Limit ${entry:.2f}\nSTOP ${stop:.2f} ({risk_pts:.1f} pts)\nTARGET ${target:.2f} RR 1:{rr:.2f}\nQty {qty:.4f} ETH | Margin 10x ${notional/10:.2f}\nRule: 15M close above ${daily_open:.2f}"
    else:
        action = f"\n⏳ WAIT - NO SWEEP\nHypo ENTRY ${entry:.2f} STOP ${stop:.2f}\nWait for Today Low < ${y_low:.2f}"
    
    msg=f"""🔔 ETH SWEEP BOT - {now_ist}

Price ${current:.2f} | Premium ${premium:.2f} | 24h {chg:+.1f}%

━━━━━━━━━━━━━━
PDH ${y_high:.2f} | PDL ${y_low:.2f}
Today H ${t_high:.2f} L ${t_low:.2f}
Daily Open ${daily_open:.2f}

{sweep_status}

{action}
━━━━━━━━━━━━━━
Delta: Check 15M
"""
    return msg

def send_telegram(text):
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)
        print(f"Telegram {r.status_code}")
    except Exception as e:
        print(e)

if __name__=="__main__":
    msg=build_message()
    print(msg)
    send_telegram(msg)
