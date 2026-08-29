import requests, re, os
from datetime import datetime
import pytz

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "PUT_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID", "PUT_CHAT_ID")
CAPITAL = float(os.environ.get("CAPITAL", "500"))
RISK_PERCENT = float(os.environ.get("RISK_PERCENT", "1.5"))

def get_levels():
    try:
        klines = requests.get("https://api.binance.com/api/v3/klines?symbol=ETHUSDT&interval=1h&limit=72", timeout=10).json()
        # Yesterday = 24-48h ago, Today = last 24h
        yesterday = klines[-48:-24]
        today = klines[-24:]
        day_before = klines[-72:-48] if len(klines)>=72 else []
        
        y_high = max(float(k[2]) for k in yesterday)
        y_low = min(float(k[3]) for k in yesterday)
        t_high = max(float(k[2]) for k in today)
        t_low = min(float(k[3]) for k in today)
        current = float(klines[-1][4])
        daily_open = float(today[0][1])
        
        # Also get PDH/PDL from 2 days ago for reference
        pdh_2d = max(float(k[2]) for k in day_before) if day_before else y_high
        
        return {
            "y_high": y_high, "y_low": y_low,
            "t_high": t_high, "t_low": t_low,
            "current": current, "daily_open": daily_open,
            "pdh_2d": pdh_2d,
            "klines": klines
        }
    except Exception as e:
        print(f"levels error {e}")
        return None

def get_data():
    try:
        bin_price = float(requests.get("https://api.binance.com/api/v3/ticker/price?symbol=ETHUSDT", timeout=10).json()['price'])
        cb_price = float(requests.get("https://api.coinbase.com/v2/prices/ETH-USD/spot", timeout=10).json()['data']['amount'])
        premium = cb_price - bin_price
    except:
        bin_price, cb_price, premium = 0,0,0
    try:
        funding = float(requests.get("https://fapi.binance.com/fapi/v1/premiumIndex?symbol=ETHUSDT", timeout=10).json()['lastFundingRate'])*100
        chg = float(requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=ETHUSDT", timeout=10).json()['priceChangePercent'])
    except:
        funding, chg = 0,0
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        html = requests.get("https://farside.co.uk/ETH/", headers=headers, timeout=15).text
        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.DOTALL)
        last_flow=None
        for row in rows[-10:]:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL)
            if len(cells)>=2:
                try:
                    last_cell = re.sub(r'<[^>]+>', '', cells[-1]).strip().replace('$','').replace('m','').replace(',','').strip()
                    if last_cell and last_cell not in ['-','']:
                        last_flow=float(last_cell)
                except:
                    pass
    except:
        last_flow=None
    return bin_price, cb_price, premium, funding, chg, last_flow

def build_message():
    levels = get_levels()
    bin_price, cb_price, premium, funding, chg, etf_flow = get_data()
    if not levels:
        return "Error fetching levels"
    
    y_high = levels['y_high']
    y_low = levels['y_low']
    t_high = levels['t_high']
    t_low = levels['t_low']
    current = levels['current']
    daily_open = levels['daily_open']
    
    # === AUTO SWEEP DETECTION ===
    sweep_low_happened = t_low < y_low
    sweep_high_happened = t_high > y_high
    sweep_low_amount = y_low - t_low if sweep_low_happened else 0
    sweep_high_amount = t_high - y_high if sweep_high_happened else 0
    
    # Which sweep is valid?
    sweep_status = ""
    if sweep_low_happened and sweep_high_happened:
        sweep_status = f"⚠️ BOTH SWEEPS! Low swept {sweep_low_amount:.1f} pts + High swept {sweep_high_amount:.1f} pts - Wait for direction"
    elif sweep_low_happened:
        sweep_status = f"✅ SWEEP LOW DETECTED! Yesterday Low ${y_low:.2f} swept to ${t_low:.2f} ({sweep_low_amount:.1f} pts sweep) - Bullish trap done"
    elif sweep_high_happened:
        sweep_status = f"✅ SWEEP HIGH DETECTED! Yesterday High ${y_high:.2f} swept to ${t_high:.2f} ({sweep_high_amount:.1f} pts) - Bearish trap done"
    else:
        sweep_status = f"⏳ NO SWEEP YET - Yesterday Low ${y_low:.2f} not swept (Today Low ${t_low:.2f}) | High ${y_high:.2f} not swept (Today High ${t_high:.2f}) - WAIT"
    
    # Score
    score=0; details=[]
    if premium>3: score+=1; details.append(f"✅ Premium +${premium:.2f} US buying")
    else: details.append(f"⚪ Premium ${premium:.2f}")
    if funding<0.01 and chg>0: score+=1; details.append(f"✅ Funding {funding:.4f}% spot")
    else: score+=0.5; details.append(f"⚪ Funding {funding:.4f}%")
    if chg>2: score+=1; details.append(f"✅ 24h {chg:+.2f}%")
    else: details.append(f"⚪ 24h {chg:+.2f}%")
    if etf_flow is not None:
        if etf_flow>80: score+=2; details.append(f"✅ ETF +${etf_flow:.1f}M HUGE")
        elif etf_flow>20: score+=1; details.append(f"✅ ETF +${etf_flow:.1f}M")
        else: details.append(f"⚪ ETF ${etf_flow:.1f}M")
    else: details.append("⚠️ ETF manual")
    score+=1
    
    # Entry calc only if sweep happened
    entry=stop=target=risk_pts=rr=0
    can_trade=False
    
    if sweep_low_happened and score>=4:
        # Bullish - sweep low happened
        entry = y_low + (current - y_low)*0.3  # 30% above sweep low = better OB entry (closer to sweep)
        # Actually better: entry near y_low + 40% of distance from t_low to current
        entry = t_low + (current - t_low)*0.6
        stop = t_low - 15
        target = y_high
        risk_pts = entry - stop
        rr = (target - entry)/risk_pts if risk_pts>0 else 0
        can_trade = True
    elif sweep_high_happened and score<=1.5:
        entry = t_high - (t_high - current)*0.6
        stop = t_high + 15
        target = y_low
        risk_pts = stop - entry
        rr = (entry - target)/risk_pts if risk_pts>0 else 0
        can_trade = True
    else:
        # No sweep or neutral score - still calculate hypothetical for reference
        sweep_low_ref = min(y_low, t_low)
        entry = sweep_low_ref + (current - sweep_low_ref)*0.6
        stop = sweep_low_ref - 15
        target = y_high
        risk_pts = entry - stop
        rr = (target - entry)/risk_pts if risk_pts>0 else 0
    
    risk_dollars = CAPITAL * RISK_PERCENT / 100
    qty = risk_dollars / risk_pts if risk_pts>0 else 0
    notional = qty * entry if entry>0 else 0
    now_ist=datetime.now(pytz.timezone('Asia/Kolkata')).strftime('%d %b %I:%M %p IST')
    
    if can_trade and score>=4:
        action = f"""
✅ TRADE READY - SWEEP CONFIRMED

📍 AUTO-FETCHED LEVELS (Binance = Delta ±$2):
• PDH (Yesterday High): ${y_high:.2f}
• PDL (Yesterday Low): ${y_low:.2f}
• Today High: ${t_high:.2f} | Today Low: ${t_low:.2f}
• Current: ${current:.2f}
• Daily Open (00:00 IST): ${daily_open:.2f}

{sweep_status}

💰 DELTA ORDER:
• ENTRY Limit: ${entry:.2f}
• STOP Market: ${stop:.2f} (Risk {risk_pts:.1f} pts)
• TARGET 1: ${target:.2f} (RR 1:{rr:.2f})

📐 SIZE (${CAPITAL:.0f} capital, {RISK_PERCENT}% risk = ${risk_dollars:.2f}):
• Qty: {qty:.4f} ETH
• Margin @10x: ${notional/10:.2f}

⚠️ RULE: Only enter if 15M closes ABOVE ${daily_open:.2f} (Daily Open) in PRIME 19-23 IST
"""
    elif not sweep_low_happened and not sweep_high_happened:
        action = f"""
⏳ WAIT - NO SWEEP YET

📍 AUTO LEVELS:
• PDH ${y_high:.2f} | PDL ${y_low:.2f}
• Today: High ${t_high:.2f} Low ${t_low:.2f}
• Current ${current:.2f} | Daily Open ${daily_open:.2f}

{sweep_status}

Hypothetical entry if sweep happens later: ${entry:.2f} Stop ${stop:.2f}

Rule: Do NOT trade until Today Low < ${y_low:.2f} (sweeps PDL) OR Today High > ${y_high:.2f} (sweeps PDH)
"""
    else:
        action = f"\nScore {score:.1f} - {sweep_status}\n"
    
    msg=f"""🔔 ETH SWEEP + ENTRY BOT - {now_ist}

Price ${current:.2f} | Premium ${premium:.2f}

{chr(10).join(details)}

━━━━━━━━━━━━━━
📊 SCORE {score:.1f}/6
{action}
━━━━━━━━━━━━━━
Chart: Check Delta 15M - Need close above/below Daily Open
"""
    return msg

def send_telegram(text):
    url=f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print(e)

if __name__=="__main__":
    msg=build_message()
    print(msg)
    send_telegram(msg)
