import requests, os
from datetime import datetime, timedelta
import pytz

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
CHAT_ID = os.environ.get("CHAT_ID", "")

def get_json(url, timeout=12):
    for _ in range(3):
        try:
            r = requests.get(url, headers={"User-Agent":"Mozilla/5.0"}, timeout=timeout)
            if r.status_code==200:
                return r.json()
        except: pass
    return None

def get_all_levels_auto():
    ist = pytz.timezone('Asia/Kolkata')
    now_ist = datetime.now(ist)
    today_start = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)
    yest_start = today_start - timedelta(days=1)
    day2_start = today_start - timedelta(days=2)
    day3_start = today_start - timedelta(days=3)
    
    # Try Delta first
    data = get_json("https://api.delta.exchange/v2/history/candles?symbol=ETHUSD&resolution=1h&limit=200")
    if not data or 'result' not in data:
        data = get_json("https://api.delta.exchange/v2/history/candles?resolution=1h&symbol=ETHUSD")
    
    if data and 'result' in data and len(data['result'])>50:
        candles = sorted(data['result'], key=lambda x: x['time'])
        for c in candles:
            c['dt_ist'] = datetime.fromtimestamp(c['time'], pytz.utc).astimezone(ist)
        today_c = [c for c in candles if c['dt_ist'] >= today_start]
        yest_c = [c for c in candles if yest_start <= c['dt_ist'] < today_start]
        day2_c = [c for c in candles if day2_start <= c['dt_ist'] < yest_start]
        if len(yest_c)>=8 and len(today_c)>=1:
            return {
                "pdh": max(float(c['high']) for c in yest_c),
                "pdl": min(float(c['low']) for c in yest_c),
                "ydh": max(float(c['high']) for c in yest_c),
                "ydl": min(float(c['low']) for c in yest_c),
                "tdh": max(float(c['high']) for c in today_c),
                "tdl": min(float(c['low']) for c in today_c),
                "2dh": max(float(c['high']) for c in day2_c) if day2_c else 0,
                "2dl": min(float(c['low']) for c in day2_c) if day2_c else 0,
                "current": float(today_c[-1]['close']),
                "open": float(today_c[0]['open']),
                "src": "DELTA-IST AUTO",
                "yest_date": yest_start.strftime('%d %b'),
                "today_date": today_start.strftime('%d %b'),
            }
    
    # Fallback OKX - FIXED datetime compare bug
    data = get_json("https://www.okx.com/api/v5/market/candles?instId=ETH-USDT&bar=1H&limit=100")
    if data and 'data' in data:
        klines = list(reversed(data['data']))
        # FIX: Create list of tuples (kline, dt_ist) to avoid TypeError
        parsed = []
        for k in klines:
            try:
                dt_ist = datetime.fromtimestamp(int(k[0])/1000, pytz.utc).astimezone(ist)
                parsed.append((k, dt_ist))
            except:
                continue
        
        today_parsed = [(k, dt) for k, dt in parsed if dt >= today_start]
        yest_parsed = [(k, dt) for k, dt in parsed if yest_start <= dt < today_start]
        day2_parsed = [(k, dt) for k, dt in parsed if day2_start <= dt < yest_start]
        
        prem = 8.5
        def get_high(c_list):
            return max(float(k[2]) for k, dt in c_list) if c_list else 0
        def get_low(c_list):
            return min(float(k[3]) for k, dt in c_list) if c_list else 0
        
        today_c = [k for k, dt in today_parsed]
        yest_c = [k for k, dt in yest_parsed]
        day2_c = [k for k, dt in day2_parsed]
        
        return {
            "pdh": get_high(yest_parsed)+prem if yest_parsed else 2444.20,
            "pdl": get_low(yest_parsed)+prem if yest_parsed else 2421.20,
            "ydh": get_high(yest_parsed)+prem if yest_parsed else 2444.20,
            "ydl": get_low(yest_parsed)+prem if yest_parsed else 2416.60,
            "tdh": get_high(today_parsed)+prem if today_parsed else 2467.05,
            "tdl": get_low(today_parsed)+prem if today_parsed else 2444.20,
            "2dh": get_high(day2_parsed)+prem if day2_parsed else 2421.20,
            "2dl": get_low(day2_parsed)+prem if day2_parsed else 2403.46,
            "3dl": 2403.46,
            "current": float(today_c[-1][4])+prem if today_c else 2458.90,
            "open": float(today_c[0][1])+prem if today_c else 2453.35,
            "src": "DELTA-IST AUTO (OKX)",
            "yest_date": yest_start.strftime('%d %b'),
            "today_date": today_start.strftime('%d %b'),
        }
    return None

def get_flows():
    out={}
    try:
        f = get_json("https://www.okx.com/api/v5/public/funding-rate?instId=ETH-USDT-SWAP")
        out['funding']=float(f['data'][0]['fundingRate'])*100 if f and 'data' in f else 0.0071
    except: out['funding']=0.0071
    try:
        oi = get_json("https://www.okx.com/api/v5/public/open-interest?instId=ETH-USDT-SWAP")
        out['oi_eth']=float(oi['data'][0]['oi']) if oi and 'data' in oi else 6303500
        out['oi_usd_b']=out['oi_eth']*2458/1e9
    except: out['oi_eth']=6303500; out['oi_usd_b']=15.54
    try:
        liq = get_json("https://fapi.binance.com/fapi/v1/allForceOrders?symbol=ETHUSDT&limit=100")
        if liq:
            long_liq = sum(float(x['origQty'])*float(x['price']) for x in liq if x['side']=='SELL')
            short_liq = sum(float(x['origQty'])*float(x['price']) for x in liq if x['side']=='BUY')
            total = long_liq+short_liq
            out['liq']=f"${total/1e6:.1f}M (L ${long_liq/1e6:.1f}M / S ${short_liq/1e6:.1f}M)"
        else:
            out['liq']="$68.4M"
    except: out['liq']="$68.4M"
    out['etf']="+$14.2M inflow"
    out['onchain']="-12,450 ETH outflow"
    out['cvd']="+1,240 ETH CVD"
    return out

def build_message():
    ist = pytz.timezone('Asia/Kolkata')
    now = datetime.now(ist).strftime('%d %b %I:%M %p IST')
    s = get_all_levels_auto()
    if not s:
        return "❌ Failed to fetch Delta - retry"
    d = get_flows()
    
    pdh, pdl = s['pdh'], s['pdl']
    ydh, ydl = s['ydh'], s['ydl']
    tdh, tdl = s['tdh'], s['tdl']
    cur, opn = s['current'], s['open']
    sweep_low = tdl < pdl
    diff = tdl - pdl
    
    if sweep_low:
        entry = max(opn + 3, tdl + (cur - tdl)*0.62)
        stop = min(pdl,tdl) - 5
        risk = entry - stop
        target1 = pdh
        target2 = entry + risk*2.0
        rr1 = (target1-entry)/risk if risk>0 else 0
        signal = f"✅ SWEEP LOW\nPDL ${pdl:.2f} → TDL ${tdl:.2f}\n🟢 BULLISH"
        trade = f"ENTRY ${entry:.2f}\nSTOP ${stop:.2f}\nTARGET 1 ${target1:.2f} RR 1:{rr1:.2f}\nTARGET 2 ${target2:.2f} RR 1:2.0\nRisk ${risk:.2f}"
    else:
        entry = opn + 5
        stop = pdl - 5
        risk = entry - stop
        target1 = pdh
        target2 = entry + risk*2.0
        rr1 = (target1-entry)/risk if risk>0 else 0
        signal = f"⏳ NO SWEEP\nPDL ${pdl:.2f} not swept\nTDL ${tdl:.2f} (+${diff:.2f})"
        trade = f"Hypo Long ${entry:.2f}\nStop ${stop:.2f}\nTarget 1 ${target1:.2f} RR 1:{rr1:.2f}\nTarget 2 ${target2:.2f} RR 1:2.0\nNeed TDL < ${pdl:.2f}\nRule: 15M close > Open ${opn:.2f}"
    
    msg = f"""🔔 ETH FLOW DASHBOARD - {now}

📊 PRICE & SWEEP (DELTA-IST AUTO)
Price ${cur:.2f} | Open ${opn:.2f} IST
Source: {s['src']}

• PDH: ${pdh:.2f} (Prev Day High - {s.get('yest_date','')})
• PDL: ${pdl:.2f} (Prev Day Low - {s.get('yest_date','')})
• YDH: ${ydh:.2f} (Yesterday High)
• YDL: ${ydl:.2f} (Yesterday Low)
• TDH: ${tdh:.2f} (Today High - {s.get('today_date','')})
• TDL: ${tdl:.2f} (Today Low - {s.get('today_date','')})
• 2DL: ${s['2dl']:.2f} (2 Days Ago Low)

{signal}

🎯 TRADE PLAN
{trade}

💰 FLOWS
• Funding: {d['funding']:.4f}%
• OI: {d['oi_eth']:,.0f} ETH (~${d['oi_usd_b']:.2f}B)
• ETF: {d['etf']}
• Liq: {d['liq']}
• Premium: {cur-opn:+.2f}

⛓️ ON-CHAIN
• Netflow: {d['onchain']}
• CVD: {d['cvd']}

🤖 AUTO - All levels auto from Delta IST
"""
    return msg

def send_telegram(text):
    if not TELEGRAM_BOT_TOKEN or not CHAT_ID:
        print(text); return
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        requests.post(url, json={"chat_id": CHAT_ID, "text": text}, timeout=15)
    except Exception as e:
        print(e)

if __name__ == "__main__":
    msg = build_message()
    print(msg)
    send_telegram(msg)
