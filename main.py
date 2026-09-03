import os, time, requests, threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import datetime
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
SYMBOL = "ETHUSDT"
PORT = int(os.getenv("PORT", 10000))
ENDPOINTS = ["https://fapi.binance.com","https://api.binance.com","https://api1.binance.com"]
CACHE = {}; CACHE_T = {}; ACTIVE_CHATS = set(); ALERT_ENABLED = set(); LAST_ALERT = {}; LAST_SIGNAL_TYPE = {}

def fetch(p_f,p_s,par,ttl=15):
    k=p_f+str(par); n=time.time()
    if k in CACHE and n-CACHE_T.get(k,0)<ttl: return CACHE[k]
    for b in ENDPOINTS:
        try:
            u=f"{b}{p_f}" if "fapi" in b else f"{b}{p_s}"
            r=requests.get(u,params=par,timeout=6)
            if r.status_code==200 and r.json(): CACHE[k]=r.json(); CACHE_T[k]=n; return r.json()
        except: continue
    return CACHE.get(k,{})

def tg_send(c,t):
    try: requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage", json={"chat_id":c,"text":t}, timeout=12)
    except: pass

def get_price():
    d=fetch("/fapi/v1/ticker/price","/api/v3/ticker/price",{"symbol":SYMBOL},8)
    try: return float(d['price']) if isinstance(d,dict) and 'price' in d else 2500.0
    except: return 2500.0

def get_funding():
    try:
        d=fetch("/fapi/v1/premiumIndex","/api/v3/ticker/price",{"symbol":SYMBOL},60)
        return float(d.get('lastFundingRate',0))*100 if isinstance(d,dict) else 0.005
    except: return 0.005

def get_klines(interval,limit=60):
    d=fetch("/fapi/v1/klines","/api/v3/klines",{"symbol":SYMBOL,"interval":interval,"limit":limit},30)
    try:
        if isinstance(d,list) and len(d)>2:
            return [{"h":float(x[2]),"l":float(x[3]),"c":float(x[4]),"o":float(x[1]),"v":float(x[5]),"bv":float(x[9]) if len(x)>9 else float(x[5])/2} for x in d]
    except: pass
    return []

def check_cvd():
    try:
        klines=get_klines("5m",15)
        if not klines: return "CVD Neutral",0
        buy=sum([k["bv"] for k in klines[-8:]]); tot=sum([k["v"] for k in klines[-8:]]); sell=tot-buy; pct=(buy-sell)/tot*100 if tot>0 else 0
        if pct>5: return f"🟢 CVD BULL +{pct:.1f}%", pct
        elif pct<-5: return f"🔴 CVD BEAR {pct:.1f}%", pct
        else: return f"⚪ CVD Neutral {pct:.1f}%", pct
    except: return "CVD Busy",0

def check_etf():
    try:
        f=get_funding()
        if f<0.02: return f"🟢 ETF Bullish Funding {f:.4f}% spot buying",1
        elif f>0.08: return f"🔴 ETF Bearish Funding {f:.4f}%",-1
        return f"⚪ ETF Neutral {f:.4f}%",0
    except: return "ETF Busy",0

def check_liq():
    try:
        depth={}
        for b in ENDPOINTS:
            try:
                r=requests.get(f"{b}/fapi/v1/depth",params={"symbol":SYMBOL,"limit":20},timeout=4)
                if r.status_code==200: depth=r.json(); break
            except: continue
        if not depth or 'bids' not in depth: return False,"⚪ OB busy",0,0,"NONE"
        bids=depth['bids'][:20]; asks=depth['asks'][:20]; price=get_price()
        b_near=a_near=0
        for p,q in bids:
            if abs(float(p)-price)<=12: b_near+=float(q)
        for p,q in asks:
            if abs(float(p)-price)<=12: a_near+=float(q)
        if a_near>b_near*1.3: return True,f"🔴 BEAR Ask {a_near:.0f} > Bid {b_near:.0f}",a_near,b_near,"BEAR"
        if b_near>a_near*1.3: return True,f"🟢 BULL Bid {b_near:.0f} > Ask {a_near:.0f}",a_near,b_near,"BULL"
        return False,f"⚪ Balanced Ask {a_near:.0f} Bid {b_near:.0f}",a_near,b_near,"NONE"
    except: return False,"OB err",0,0,"NONE"

def build_signal():
    try:
        price=get_price(); daily=get_klines("1d",5); h1=get_klines("1h",40); m5=get_klines("5m",60); funding=get_funding()
        if len(daily)<3 or len(m5)<20: return None,"⏳ Loading Binance...",False
        d1h=daily[-2]["h"]; d1l=daily[-2]["l"]
        recent=m5[-25:]; t_low=min([x["l"] for x in recent]+[price]); t_high=max([x["h"] for x in recent]+[price])
        long_sweep=t_low<d1l; short_sweep=t_high>d1h; s_long=d1l-t_low if long_sweep else 0; s_short=t_high-d1h if short_sweep else 0
        highs=[x["h"] for x in m5]; lows=[x["l"] for x in m5]
        last_lh=max(highs[-20:-3]) if len(highs)>20 else price+5; last_ll=min(lows[-20:-3]) if len(lows)>20 else price-5
        bull_mss=price>last_lh; bear_mss=price<last_ll
        ema20=sum([x["c"] for x in h1[-20:]])/20 if len(h1)>=20 else price
        htf="BULL" if price>ema20 else "BEAR"
        grab_ready,ob_msg,ask_v,bid_v,grab_dir=check_liq(); cvd_msg,cvd_val=check_cvd(); etf_msg,etf_val=check_etf()
        now=datetime.datetime.utcnow()+datetime.timedelta(hours=5,minutes=30); sess="NY" if 17<=now.hour<21 else "LONDON" if 12<=now.hour<16 else "ASIA"; t_str=now.strftime("%I:%M %p IST")
        all_info=f"{ob_msg}\n{cvd_msg}\n{etf_msg}"
        bear_score=(1 if grab_dir=="BEAR" else 0)+(1 if cvd_val<-5 else 0)+(0.5 if etf_val<0 else 0)
        bull_score=(1 if grab_dir=="BULL" else 0)+(1 if cvd_val>5 else 0)+(0.5 if etf_val>0 else 0)

        # 1. SMALL BREAKOUT LONG - PDH swept or 5m high break + CVD BULL 5%+ = 12-15pts
        if bull_mss and cvd_val>5:
            return "BREAKOUT_LONG",f"🚀 BREAKOUT LONG 75% - 12-15pts\n{sess} {t_str} ${price:.0f}\nPDH ${d1h:.0f} H ${t_high:.0f} {'SWEPT ✅' if short_sweep else f'Break >${int(last_lh)} ✅'}\nMSS Bull ${price:.0f}>${int(last_lh)} ✅\n{all_info}\nScore BULL {bull_score}/2.5 HTF {htf}\n📌 ENTRY ${price:.0f}-${price+2:.0f} SL ${int(last_ll)} TP ${price+12:.0f} [12pts] TP2 ${price+15:.0f}\n💰 100 lot = $12",True

        # 2. SMALL BREAKOUT SHORT - PDL swept or 5m low break + CVD BEAR -5% = 12-15pts
        if bear_mss and cvd_val<-5:
            return "BREAKOUT_SHORT",f"🔻 BREAKOUT SHORT 75% - 12-15pts\n{sess} {t_str} ${price:.0f}\nPDL ${d1l:.0f} L ${t_low:.0f} {'SWEPT ✅' if long_sweep else f'Break <${int(last_ll)} ✅'}\nMSS Bear ${price:.0f}<${int(last_ll)} ✅\n{all_info}\nScore BEAR {bear_score}/2.5 HTF {htf}\n📌 ENTRY ${price-2:.0f}-${price:.0f} SL ${int(last_lh)} TP ${price-12:.0f} [12pts] TP2 ${price-15:.0f}\n💰 100 lot = $12",True

        # 3. LIQ GRAB with lower threshold 5%
        if short_sweep and bear_mss and bear_score>=1.5:
            return "LIQ_SHORT",f"💧 LIQ GRAB SHORT 80% - 12-15pts\n{sess} {t_str} ${price:.0f} PDH SWEPT +{int(s_short)}\n{all_info}\n📌 ${price-2:.0f}-${price:.0f} SL ${t_high+6:.0f} TP ${price-12:.0f}",True
        if long_sweep and bull_mss and bull_score>=1.5:
            return "LIQ_LONG",f"💧 LIQ GRAB LONG 80%\n{sess} {t_str} ${price:.0f} PDL SWEPT -{int(s_long)}\n{all_info}\n📌 ${price:.0f}-${price+2:.0f} SL ${t_low-6:.0f} TP ${price+12:.0f}",True

        # 4. TURTLE SOUP
        if long_sweep and bull_mss:
            return "TURTLE_LONG",f"🐢 TURTLE LONG 75%\n{sess} {t_str} ${price:.0f} PDL SWEPT\n{all_info}\n📌 ENTRY ${int(last_ll+3)}",True
        if short_sweep and bear_mss:
            return "TURTLE_SHORT",f"🐢 TURTLE SHORT 75%\n{sess} {t_str} ${price:.0f} PDH SWEPT\n{all_info}\n📌 ENTRY ${int(last_lh-3)}",True

        base=f"🚨 {sess} {t_str} ${price:.0f}\nPDL ${int(d1l)} L ${int(t_low)} {'SWEPT ✅' if long_sweep else ''}\nPDH ${int(d1h)} H ${int(t_high)} {'SWEPT ✅' if short_sweep else ''}\n\n{all_info}\nScore BEAR {bear_score} BULL {bull_score} Need 1.5+ for Breakout\nMSS Bull >${int(last_lh)} Bear <${int(last_ll)} Now ${price:.0f}\n\n✅ Breakout Long: Bull MSS + CVD BULL 5%+ = 12-15pts\n✅ Breakout Short: Bear MSS + CVD BEAR 5%- = 12-15pts\nWait for MSS break + CVD"
        return None,base,False
    except Exception as e:
        import traceback; traceback.print_exc(); return None,f"Err {e}",False

def auto_loop():
    while True:
        time.sleep(65)
        if not ACTIVE_CHATS: continue
        try:
            typ,msg,is_trade=build_signal()
            if is_trade:
                now=time.time()
                for chat in list(ACTIVE_CHATS):
                    if chat not in ALERT_ENABLED: continue
                    if now-LAST_ALERT.get(chat,0)<600 and LAST_SIGNAL_TYPE.get(chat,"")==typ: continue
                    tg_send(chat,f"🚨 {typ} AUTO 🚨\n\n{msg}"); LAST_ALERT[chat]=now; LAST_SIGNAL_TYPE[chat]=typ
        except Exception as e: print(e)

def poll():
    off=0; print(f"FINAL v61 live {PORT}")
    while True:
        try:
            r=requests.get(f"https://api.telegram.org/bot{TOKEN}/getUpdates",params={"offset":off,"timeout":25},timeout=35).json()
            for u in r.get("result",[]):
                off=u["update_id"]+1; chat=u.get("message",{}).get("chat",{}).get("id"); txt=(u.get("message",{}).get("text","") or "").lower().strip()
                if not chat: continue
                ACTIVE_CHATS.add(chat)
                if chat not in ALERT_ENABLED: ALERT_ENABLED.add(chat)
                if "/ict" in txt or "/break" in txt or "/liq" in txt:
                    _,m,_=build_signal(); tg_send(chat,m)
                elif "/alerts" in txt:
                    if "off" in txt: ALERT_ENABLED.discard(chat); tg_send(chat,"🔕 OFF")
                    else: ALERT_ENABLED.add(chat); tg_send(chat,"🔔 ON ✅ Small Breakout 12-15pts")
                elif "/status" in txt:
                    _,m,_=build_signal(); tg_send(chat,m[:3800])
                elif "/start" in txt:
                    ALERT_ENABLED.add(chat); tg_send(chat,"FINAL v6.1 ✅ Small Breakout 12-15pts\n🚀 LONG: Break > last 5m high + CVD BULL 5%+\n🔻 SHORT: Break < last 5m low + CVD BEAR 5%-\n/ict to check\n100 lot = $12 per 12pts")
        except Exception as e: print(f"poll err {e}"); time.sleep(3)

if __name__=="__main__":
    threading.Thread(target=poll,daemon=True).start(); threading.Thread(target=auto_loop,daemon=True).start()
    class HH(BaseHTTPRequestHandler):
        def do_GET(self): self.send_response(200); self.end_headers(); self.wfile.write(b"FINAL v6.1 SMALL BREAKOUT LIVE")
        def log_message(self,*a): return
    HTTPServer(("0.0.0.0",PORT),HH).serve_forever()
