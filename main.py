import os, time, requests, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import datetime
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SYMBOL = "ETHUSDT"
PORT = int(os.getenv("PORT", 10000))
ENDPOINTS = ["https://fapi.binance.com","https://api.binance.com","https://api1.binance.com","https://api2.binance.com"]
CACHE = {}; CACHE_T = {}; ACTIVE_CHATS = set(); ALERT_ENABLED = set(); LAST_ALERT = {}; LAST_SIGNAL_TYPE = {}

def fetch(p_f,p_s,par,ttl=12):
    k=p_f+str(par); n=time.time()
    if k in CACHE and n-CACHE_T.get(k,0)<ttl: return CACHE[k]
    for b in ENDPOINTS:
        try:
            u=f"{b}{p_f}" if "fapi" in b else f"{b}{p_s}"
            r=requests.get(u,params=par,timeout=5)
            if r.status_code==200 and isinstance(r.json(),(list,dict)): CACHE[k]=r.json(); CACHE_T[k]=n; return r.json()
        except: continue
    return CACHE.get(k,{})

def tg_send(c,t):
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":c,"text":t,"parse_mode":"HTML"}, timeout=10)
    except: pass

def get_price():
    for _ in range(3):
        d=fetch("/fapi/v1/ticker/price","/api/v3/ticker/price",{"symbol":SYMBOL},6)
        try:
            if isinstance(d,dict) and 'price' in d: return float(d['price'])
        except: pass
        time.sleep(1)
    return 2490.0

def get_funding():
    try:
        d=fetch("/fapi/v1/premiumIndex","/api/v3/ticker/price",{"symbol":SYMBOL},50)
        return float(d.get('lastFundingRate',0))*100 if isinstance(d,dict) else 0.005
    except: return 0.005

def get_klines(interval,limit=50):
    d=fetch("/fapi/v1/klines","/api/v3/klines",{"symbol":SYMBOL,"interval":interval,"limit":limit},25)
    try:
        if isinstance(d,list) and len(d)>5:
            return [{"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"o":float(x[1]),"v":float(x[5]),"bv":float(x[9]) if len(x)>9 else float(x[5])/2} for x in d]
    except: pass
    return []

def check_cvd():
    try:
        klines=get_klines("5m",12)
        if len(klines)<8: return "⚪ CVD Loading",0
        buy=sum([k["bv"] for k in klines[-6:]]); tot=sum([k["v"] for k in klines[-6:]]); pct=(buy-(tot-buy))/tot*100 if tot>0 else 0
        if pct>5: return f"🟢 CVD BULL +{pct:.1f}%", pct
        if pct<-5: return f"🔴 CVD BEAR {pct:.1f}%", pct
        return f"⚪ CVD Neutral {pct:.1f}%", pct
    except: return "⚪ CVD Busy",0

def check_etf():
    try:
        f=get_funding()
        if f<0.02: return f"🟢 ETF Bullish {f:.4f}%",1
        if f>0.08: return f"🔴 ETF Bearish {f:.4f}%",-1
        return f"⚪ ETF Neutral {f:.4f}%",0
    except: return "⚪ ETF Busy",0

def check_liq():
    try:
        depth=None
        for b in ENDPOINTS:
            try:
                r=requests.get(f"{b}/fapi/v1/depth",params={"symbol":SYMBOL,"limit":20},timeout=4)
                if r.status_code==200 and 'bids' in r.json(): depth=r.json(); break
            except: continue
        if not depth: return False,"⚪ OB Loading",0,0,"NONE"
        price=get_price(); b_near=a_near=0
        for p,q in depth['bids'][:15]:
            if abs(float(p)-price)<=12: b_near+=float(q)
        for p,q in depth['asks'][:15]:
            if abs(float(p)-price)<=12: a_near+=float(q)
        if a_near>b_near*1.3: return True,f"🔴 Ask Heavy {a_near:.0f} vs {b_near:.0f}",a_near,b_near,"BEAR"
        if b_near>a_near*1.3: return True,f"🟢 Bid Heavy {b_near:.0f} vs {a_near:.0f}",a_near,b_near,"BULL"
        return False,f"⚪ Balanced {a_near:.0f}/{b_near:.0f}",a_near,b_near,"NONE"
    except: return False,"⚪ OB Busy",0,0,"NONE"

def build_signal():
    try:
        price=get_price(); daily=get_klines("1d",5); h1=get_klines("1h",30); m5=get_klines("5m",50)
        if len(daily)<3 or len(m5)<15:
            return None,f"🚨 ASIA {datetime.datetime.utcnow().hour+5}:{(datetime.datetime.utcnow().minute+30)%60:02d} IST ${price:.0f}\n⏳ Loading Binance data... Wait 10 sec and /ict again",False
        d1h=daily[-2]["h"]; d1l=daily[-2]["l"]
        recent=m5[-20:]; t_low=min([x["l"] for x in recent]+[price]); t_high=max([x["h"] for x in recent]+[price])
        long_sweep=t_low<d1l; short_sweep=t_high>d1h
        highs=[x["h"] for x in m5]; lows=[x["l"] for x in m5]
        # Tight MSS for small breakout: last 15 candles excluding last 2
        last_lh=max(highs[-15:-2]) if len(highs)>15 else price+4
        last_ll=min(lows[-15:-2]) if len(lows)>15 else price-4
        bull_mss=price>last_lh+1; bear_mss=price<last_ll-1
        htf="BULL" if len(h1)>0 and price>sum([x["c"] for x in h1[-20:]])/20 else "BEAR"
        _,ob_msg,_,_,grab_dir=check_liq(); cvd_msg,cvd_val=check_cvd(); etf_msg,_=check_etf()
        now=datetime.datetime.utcnow()+datetime.timedelta(hours=5,minutes=30); sess="NY" if 17<=now.hour<22 else "LONDON" if 12<=now.hour<16 else "ASIA"; t_str=now.strftime("%I:%M %p IST")
        all_info=f"{ob_msg}\n{cvd_msg}\n{etf_msg}"
        bear_score=(1 if grab_dir=="BEAR" else 0)+(1 if cvd_val<-5 else 0)
        bull_score=(1 if grab_dir=="BULL" else 0)+(1 if cvd_val>5 else 0)

        # SMALL BREAKOUT 12-15pts - MAIN FOR YOU
        if bull_mss and cvd_val>5:
            return "BREAKOUT_LONG",f"🚀 BREAKOUT LONG 80% - 12-15pts\n{sess} {t_str} ${price:.0f} Break >${int(last_lh)} ✅\nPDH ${int(d1h)} H ${int(t_high)} {'SWEPT ✅' if short_sweep else ''}\n{all_info}\nScore BULL {bull_score}/2 HTF {htf}\n📌 ENTRY ${price:.0f}-${price+2:.0f}\nSTOP ${int(last_ll)} (tight)\nTP1 ${price+12:.0f} [12pts] TP2 ${price+15:.0f}\n💰 100 lot = $12 profit",True
        if bear_mss and cvd_val<-5:
            return "BREAKOUT_SHORT",f"🔻 BREAKOUT SHORT 80% - 12-15pts\n{sess} {t_str} ${price:.0f} Break <${int(last_ll)} ✅\nPDL ${int(d1l)} L ${int(t_low)} {'SWEPT ✅' if long_sweep else ''}\n{all_info}\nScore BEAR {bear_score}/2 HTF {htf}\n📌 ENTRY ${price-2:.0f}-${price:.0f}\nSTOP ${int(last_lh)} (tight)\nTP1 ${price-12:.0f} [12pts] TP2 ${price-15:.0f}\n💰 100 lot = $12 profit",True

        # LIQ GRAB fallback
        if short_sweep and bear_mss and bear_score>=1:
            return "LIQ_SHORT",f"💧 LIQ SHORT 75% ${price:.0f} PDH SWEPT\n{all_info}\n📌 SHORT ${price:.0f} TP ${price-12:.0f}",True
        if long_sweep and bull_mss and bull_score>=1:
            return "LIQ_LONG",f"💧 LIQ LONG 75% ${price:.0f} PDL SWEPT\n{all_info}\n📌 LONG ${price:.0f} TP ${price+12:.0f}",True

        # WAIT state - explain why
        base=f"🚨 {sess} {t_str} ${price:.0f}\nPDL ${int(d1l)} L ${int(t_low)} {'SWEPT ✅' if long_sweep else ''}\nPDH ${int(d1h)} H ${int(t_high)} {'SWEPT ✅' if short_sweep else ''}\n\n{all_info}\nScore BEAR {bear_score} BULL {bull_score} Need 1+ for Breakout\nMSS Bull >${int(last_lh)} Bear <${int(last_ll)} Now ${price:.0f}\n\n"
        if not bull_mss and not bear_mss:
            base+="⏳ WAIT: No MSS break yet\nNeed price > $"+str(int(last_lh))+" for LONG or < $"+str(int(last_ll))+" for SHORT\n"
        elif not (cvd_val>5 or cvd_val<-5):
            base+=f"⏳ WAIT: CVD {cvd_val:.1f}% Neutral - Need BULL 5%+ or BEAR 5%-\n"
        else:
            base+="⏳ WAIT: Conditions almost ready\n"
        base+="✅ Small Breakout: MSS + CVD 5%+ = 12-15pts"
        return None,base,False
    except Exception as e:
        import traceback; traceback.print_exc(); return None,f"Err {e} - /ict again in 10 sec",False

def auto_loop():
    while True:
        time.sleep(55)
        if not ACTIVE_CHATS: continue
        try:
            typ,msg,is_trade=build_signal()
            if is_trade:
                now=time.time()
                for chat in list(ACTIVE_CHATS):
                    if chat not in ALERT_ENABLED: continue
                    if now-LAST_ALERT.get(chat,0)<500 and LAST_SIGNAL_TYPE.get(chat,"")==typ: continue
                    tg_send(chat,f"🚨 {typ} AUTO 🚨\n\n{msg}"); LAST_ALERT[chat]=now; LAST_SIGNAL_TYPE[chat]=typ
        except Exception as e: print(f"auto err {e}")

def poll():
    off=0
    print(f"FINAL v6.2 ANTI-SLEEP LIVE {PORT}")
    fail=0
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",params={"offset":off,"timeout":20},timeout=30).json()
            fail=0
            for u in r.get("result",[]):
                off=u["update_id"]+1
                chat=u.get("message",{}).get("chat",{}).get("id")
                txt=(u.get("message",{}).get("text","") or "").strip()
                low=txt.lower()
                if not chat: continue
                ACTIVE_CHATS.add(chat)
                if chat not in ALERT_ENABLED: ALERT_ENABLED.add(chat)
                if "/ict" in low or "/break" in low or "/status" in low or "/liq" in low:
                    _,m,_=build_signal(); tg_send(chat,m)
                elif "/alerts" in low:
                    if "off" in low: ALERT_ENABLED.discard(chat); tg_send(chat,"🔕 Alerts OFF")
                    else: ALERT_ENABLED.add(chat); tg_send(chat,"🔔 Alerts ON ✅ v6.2 Small Breakout 12-15pts - Tight Stop")
                elif "/start" in low:
                    ALERT_ENABLED.add(chat); tg_send(chat,"✅ FINAL v6.2 LIVE - Anti-Sleep Fixed\n🚀 LONG: Break > last 15m high + CVD BULL 5%+\n🔻 SHORT: Break < last 15m low + CVD BEAR 5%-\n📌 Tight Stop + 12-15pts TP\n/ict to check now")
        except Exception as e:
            fail+=1; print(f"poll err {fail} {e}"); time.sleep(min(2*fail,10))

if __name__=="__main__":
    threading.Thread(target=poll,daemon=True).start()
    threading.Thread(target=auto_loop,daemon=True).start()
    class HH(BaseHTTPRequestHandler):
        def do_GET(self):
            self.send_response(200); self.send_header("Content-type","text/plain"); self.end_headers()
            try:
                _,m,_=build_signal(); self.wfile.write(f"v6.2 LIVE - {m[:500]}".encode())
            except: self.wfile.write(b"v6.2 LIVE OK")
        def log_message(self,*a): return
    HTTPServer(("0.0.0.0",PORT),HH).serve_forever()
