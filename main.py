def check_cmd():
 global offset
 try:
  d=gj(f"https://api.telegram.org/bot{BOT}/getUpdates?offset={offset}&timeout=5")
  if d and 'result' in d:
   for upd in d['result']:
    offset=upd['update_id']+1
    msg=upd.get('message',{}).get('text','').lower()
    cid=str(upd.get('message',{}).get('chat',{}).get('id',''))
    if cid!=CHAT: continue
    p=price(); f=get_real_flows(); s=levels()
    ist=pytz.timezone('Asia/Kolkata'); now=datetime.now(ist)
    total_score=(1 if f['cvd']>0 else -1)+f['etf_score']+f['flow_score']
    bias="BULLISH 🟢" if total_score>=1 else "BEARISH 🔴" if total_score<=-1 else "NEUTRAL ⚪"
    
    if '/test' in msg:
     tg(f"✅ V41 MASTERPIECE LIVE!\nPrice ${p:.2f}\nPDH ${s['pdh']:.2f} PDL ${s['pdl']:.2f}\nCVD: {f['cvd_txt']}\n24h: {f.get('price_change',0):.2f}%\nBias: {bias}\n\nCommands:\n/bias /data /levels /entry /signal")
    
    elif '/bias' in msg or '/data' in msg:
     tg(f"📊 REAL DATA - {now.strftime('%H:%M:%S IST')}\n\nPrice ${p:.2f} ({f.get('price_change',0):+.2f}% 24h)\nCVD: {f['cvd_txt']}\nFunding: {f['fund']:.4f}% OI: {f['oi_txt']}\nETF: {f['etf']}\nOn-chain: {f['onchain']}\nScore: {total_score}/3 = {bias}\n\nPDH ${s['pdh']:.2f} PDL ${s['pdl']:.2f}\nTDH ${s['tdh']:.2f} TDL ${s['tdl']:.2f}")
    
    elif '/levels' in msg:
     tg(f"📈 LEVELS - {now.strftime('%H:%M:%S IST')}\n\nPDH ${s['pdh']:.2f}\nPDL ${s['pdl']:.2f}\nTDH ${s['tdh']:.2f}\nTDL ${s['tdl']:.2f}\nPrice ${p:.2f}\n\nDistance:\nTo PDH: ${s['pdh']-p:+.2f}\nTo PDL: ${s['pdl']-p:+.2f}")
    
    elif '/entry' in msg or '/signal' in msg:
     if total_score>=1: # Bullish
      tg(f"🎯 {bias} ENTRY - {now.strftime('%H:%M:%S IST')}\n\nPrice ${p:.2f}\nCVD {f['cvd_txt']} Score {total_score}\n\n🟢 LONG SETUP\nEntry ${p:.2f}\nStop ${s['pdl']-2:.2f} ({p-(s['pdl']-2):.2f}$ risk)\nT1 ${p+12:.2f} (+12)\nT2 ${p+28:.2f} (+28)\nT3 ${p+55:.2f} (+55)\nRR 1:2.5\n\nBias: {bias} = LONG preferred")
     elif total_score<=-1: # Bearish
      tg(f"🎯 {bias} ENTRY - {now.strftime('%H:%M:%S IST')}\n\nPrice ${p:.2f}\nCVD {f['cvd_txt']} Score {total_score}\n\n🔴 SHORT SETUP\nEntry ${p:.2f}\nStop ${s['pdh']+6:.2f} ({s['pdh']+6-p:.2f}$ risk)\nT1 ${p-12:.2f} (-12)\nT2 ${p-28:.2f} (-28)\nT3 ${p-55:.2f} (-55) → $2380 target\nRR 1:2.5\n\nBias: {bias} = SHORT preferred\n⚠️ Your 3:30 bearish case = This SHORT!")
     else:
      tg(f"⚪ NEUTRAL - {now.strftime('%H:%M:%S IST')}\nPrice ${p:.2f} CVD {f['cvd_txt']} Score {total_score}\nWait for breakout PDH ${s['pdh']:.2f} or breakdown PDL ${s['pdl']:.2f}")
 except Exception as e: print(f"cmd err {e}")
