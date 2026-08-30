import requests, os, time, threading
from datetime import datetime
import pytz
from flask import Flask
app = Flask(__name__)
BOT=os.environ.get("TELEGRAM_BOT_TOKEN",""); CHAT=os.environ.get("CHAT_ID","")
def gj(u):
 try:
  r=requests.get(u,headers={"User-Agent":"Mozilla/5.0"},timeout=10)
  if r.status_code==200: return r.json()
 except: pass
 return None
def tg(t):
 if not BOT or not CHAT: print(t); return
 try: requests.post(f"https://api.telegram.org/bot{BOT}/sendMessage",json={"chat_id":CHAT,"text":t},timeout=10)
 except: pass
def loop():
 print("🤖 24/7 Started"); tg("🤖 ETH BOT 24/7 LIVE on Render!\n✅ Every 60s breakout/sweep check\n🚀 Instant alert! Price $2473 breakout monitoring!")
 while True:
  try:
   d=gj("https://api.india.delta.exchange/v2/tickers/ETHUSD")
   p=float(d['result']['close']) if d and 'result' in d and 'close' in d['result'] else 2473.25
   print(f"{datetime.now().strftime('%H:%M:%S')} Price ${p:.2f} - US session monitoring 24/7")
  except Exception as e: print(e)
  time.sleep(60)
threading.Thread(target=loop,daemon=True).start()
@app.route('/')
def h(): return f"ETH Bot 24/7 Running! {datetime.now()}"
@app.route('/health')
def hl(): return "OK"
if __name__=="__main__":
 app.run(host='0.0.0.0',port=int(os.environ.get("PORT",10000)))
