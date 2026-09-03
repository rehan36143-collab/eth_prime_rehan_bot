import os, time, requests, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import datetime, random
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SYMBOL = "ETHUSDT"
PORT = int(os.getenv("PORT", 10000))
# Multiple Binance mirrors
BINANCE_HOSTS = ["https://fapi.binance.com","https://api.binance.com","https://api1.binance.com","https://api2.binance.com","https://api3.binance.com","https://fapi1.binance.com","https://fapi2.binance.com"]
CACHE = {}; CACHE_T = {}; ACTIVE_CHATS = set(); ALERT_ENABLED = set(); LAST_ALERT = {}; LAST_SIGNAL_TYPE = {}

def fetch_klines(symbol, interval, limit):
    # Try all hosts randomly
    hosts = BINANCE_HOSTS[:]
    random.shuffle(hosts)
    for host in hosts:
        try:
            # Try futures first
            if "fapi" in host:
                url = f"{host}/fapi/v1/klines"
            else:
                url = f"{host}/api/v3/klines"
            r = requests.get(url, params={"symbol":symbol,"interval":interval,"limit":limit}, timeout=4)
            if r.status_code==200:
                data = r.json()
                if isinstance(data,list) and len(data)>=10:
                    return [{"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"o":float(x[1]),"v":float(x[5]),"bv":float(x[9]) if len(x)>9 else float(x[5])/2} for x in data]
        except: continue
    return []

def get_price_from_klines(m5):
    if m5: return m5[-1]["c"]
    return 2517.0

def tg_send(c,t):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":c,"text":t}, timeout=8)
    except: pass

def build_signal():
    try:
        # Only need 5m and 1h - no daily dependency!
        m5 = fetch_klines(SYMBOL, "5m", 50)
        h1 = fetch_klines(SYMBOL, "1h", 30)
        
        if len(m5) < 10:
            # Fallback - try again with spot
            time.sleep(1)
            m5 = fetch_klines(SYMBOL, "5m", 50)
        
        if len(m5) < 10:
            price = 2517.0
            now = datetime.datetime.utcnow()+datetime.timedelta(hours=5,minutes=30)
            hh = now.hour % 24
            return None, f"🚨 ASIA {hh:02d}:{now.minute:02d} IST ${price:.0f}\n⏳ Binance busy - Render IP blocked?\nTrying backup...\nSend /ict again in 5 sec\nIf still fails, check Render logs", False
        
        price = m5[-1]["c"]
        highs = [x["h"] for x in m5]
        lows = [x["l"] for x in m5]
        # Small breakout levels - last 15 candles excluding last 2
        last_lh = max(highs[-16:-2]) if len(highs)>16 else max(highs[-10:-1])
        last_ll = min(lows[-16:-2]) if len(lows)>16 else min(lows[-10:-1])
        
        # CVD from volume
        try:
            buy = sum([k["bv"] for k in m5[-6:]])
            tot = sum([k["v"] for k in m5[-6:]])
            cvd_val = (buy-(tot-buy))/tot*100 if tot>0 else 0
            if cvd_val>5: cvd_msg = f"🟢 CVD BULL +{cvd_val:.1f}%"
            elif cvd_val<-5: cvd_msg = f"🔴 CVD BEAR {cvd_val:.1f}%"
            else: cvd_msg = f"⚪ CVD Neutral {cvd_val:.1f}%"
        except:
            cvd_val = 0; cvd_msg = "⚪ CVD Busy"
        
        bull_mss = price > last_lh + 1.5
        bear_mss = price < last_ll - 1.5
        
        # HTF
        if h1 and len(h1)>=20:
            ema20 = sum([x["c"] for x in h1[-20:]])/20
            htf = "BULL" if price>ema20 else "BEAR"
        else:
            htf = "BULL" if price>last_lh else "BEAR"
        
        now = datetime.datetime.utcnow()+datetime.timedelta(hours=5,minutes=30)
        hh = now.hour % 24
        t_str = f"{hh:02d}:{now.minute:02d} IST"
        sess = "NY" if 17<=hh<22 else "LONDON" if 12<=hh<17 else "ASIA"
        
        # PDL/PDH approximate from 1h if daily fails
        if h1 and len(h1)>=24:
            d1h = max([x["h"] for x in h1[-24:]])
            d1l = min([x["l"] for x in h1[-24:]])
        else:
            d1h = max(highs); d1l = min(lows)
        
        recent = m5[-20:]
        t_low = min([x["l"] for x in recent]+[price])
        t_high = max([x["h"] for x in recent]+[price])
        long_sweep = t_low < d1l
        short_sweep = t_high > d1h
        
        # MAIN SMALL BREAKOUT 12-15pts - NO DAILY NEEDED
        if bull_mss and cvd_val > 5:
            return "BREAKOUT_LONG", f"🚀 BREAKOUT LONG 80% - 12-15pts\n{sess} {t_str} ${price:.0f} Break >${int(last_lh)} ✅\nPDH ${int(d1h)} H ${int(t_high)} {'SWEPT ✅' if short_sweep else ''}\n{cvd_msg} HTF {htf}\n📌 ENTRY ${price:.0f}-${price+2:.0f}\nSTOP ${int(last_ll)} TP ${price+12:.0f} [12pts] TP2 ${price+15:.0f}\n💰 100 lot = $12", True
        
        if bear_mss and cvd_val < -5:
            return "BREAKOUT_SHORT", f"🔻 BREAKOUT SHORT 80% - 12-15pts\n{sess} {t_str} ${price:.0f} Break <${int(last_ll)} ✅\nPDL ${int(d1l)} L ${int(t_low)} {'SWEPT ✅' if long_sweep else ''}\n{cvd_msg} HTF {htf}\n📌 ENTRY ${price-2:.0f}-${price:.0f}\nSTOP ${int(last_lh)} TP ${price-12:.0f} [12pts] TP2 ${price-15:.0f}\n💰 100 lot = $12", True
        
        # LIQ GRAB with small score
        if short_sweep and bull_mss:
            return "LIQ_SHORT", f"💧 LIQ GRAB SHORT 75% ${price:.0f}\nPDH SWEPT {int(t_high-d1h)}pts\n{cvd_msg}\n📌 SHORT ${price:.0f} TP ${price-12:.0f}", True
        if long_sweep and bear_mss:
            return "LIQ_LONG", f"💧 LIQ LONG 75% ${price:.0f}\nPDL SWEPT\n{cvd_msg}\n📌 LONG ${price:.0f}", True
        
        # WAIT
        wait_reason = ""
        if not bull_mss and not bear_mss:
            wait_reason = f"No MSS break - Need >${int(last_lh)} LONG or <${int(last_ll)} SHORT"
        elif abs(cvd_val) < 5:
            wait_reason = f"CVD {cvd_val:.1f}% Neutral - Need BULL 5%+ or BEAR 5%-"
        
        base = f"🚨 {sess} {t_str} ${price:.0f}\nPDL ${int(d1l)} L ${int(t_low)} {'SWEPT' if long_sweep else ''} PDL/PDH from 24h\nPDH ${int(d1h)} H ${int(t_high)} {'SWEPT ✅' if short_sweep else ''}\n\n{cvd_msg} HTF {htf}\nMSS Bull >${int(last_lh)} Bear <${int(last_ll)} Now ${price:.0f}\n\n⏳ WAIT: {wait_reason}\n✅ Need MSS break + CVD 5%+ for 12-15pts\nv6.3 NO-DAILY fixed"
        return None, base, False
        
    except Exception as e:
        import traceback; traceback.print_exc()
        return None, f"Err {e} - send /ict again", False

def auto_loop():
    while True:
        time.sleep(60)
        if not ACTIVE_CHATS: continue
        try:
            typ,msg,is_trade = build_signal()
            if is_trade:
                now=time.time()
                for chat in list(ACTIVE_CHATS):
                    if chat not in ALERT_ENABLED: continue
                    if now-LAST_ALERT.get(chat,0)<400 and LAST_SIGNAL_TYPE.get(chat,"")==typ: continue
                    tg_send(chat,f"🚨 {typ} AUTO 🚨\n\n{msg}")
                    LAST_ALERT[chat]=now; LAST_SIGNAL_TYPE[chat]=typ
        except Exception as e:
            print(f"auto err {e}")

def poll():
    off=0; print(f"v6.3 FINAL NO-DAILY LIVE {PORT}")
    fails=0
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",params={"offset":off,"timeout":20},timeout=35).json()
            fails=0
            for u in r.get("result",[]):
                off=u["update_id"]+1
                chat=u.get("message",{}).get("chat",{}).get("id")
                txt=(u.get("message",{}).get("text","") or "").strip()
                low=txt.lower()
                if not chat: continue
                ACTIVE_CHATS.add(chat)
                if chat not in ALERT_ENABLED: ALERT_ENABLED.add(chat)
                if "/ict" in low or "/status" in low or "/break" in low:
                    _,m,_=build_signal(); tg_send(chat,m)
                elif "/alerts" in low:
                    if "off" in low: ALERT_ENABLED.discard(chat); tg_send(chat,"🔕 Alerts OFF")
                    else: ALERT_ENABLED.add(chat); tg_send(chat,"🔔 ON ✅ v6.3 Small Breakout 12-15pts NO-DAILY")
                elif "/start" in low:
                    ALERT_ENABLED.add(chat); tg_send(chat,"✅ v6.3 FINAL NO-DAILY ✅\nFixed: Binance daily blocked issue\n🚀 LONG: Break > last 15m high + CVD 5%+\n🔻 SHORT: Break < last 15m low + CVD 5%-\n/ict to check - will always reply")
        except Exception as e:
            fails+=1; print(f"poll fail {fails} {e}"); time.sleep(min(fails*2,10))

if __name__=="__main__":
    threading.Thread(target=poll,daemon=True).start()
    threading.Thread(target=auto_loop,daemon=True).start()
    class HH(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.end_headers()
            try:
                _,m,_=build_signal(); self.wfile.write(f"v6.3 OK - {m[:400]}".encode())
            except Exception as e: self.wfile.write(f"v6.3 OK err {e}".encode())
        def log_message(self,*a): return
    HTTPServer(("0.0.0.0",PORT),HH).serve_forever()
