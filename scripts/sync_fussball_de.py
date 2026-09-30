#!/usr/bin/env python3
import asyncio, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'sync_config.json').read_text(encoding='utf-8'))
OUT=ROOT/'spiele-live.json'
DATE_RE=re.compile(r'(?:(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*,?\s*)?(\d{1,2})\.(\d{1,2})\.(\d{2,4}).{0,40}?([0-2]?\d:[0-5]\d)',re.I)
LABEL={'u19':'U19','u17':'U17','u16':'U16','u15':'U15','u14':'U14','u13':'U13','u12':'U12','u11':'U11','sgv':'Herren'}
def team_id(s):
 s=' '.join(s.split())
 if re.search(r'\bA-Junioren\b|\bU\s*19\b',s,re.I): return 'u19'
 if re.search(r'\bB-Junioren\b|\bU\s*(?:16|17)\b',s,re.I): return 'u16' if re.search(r'\b(?:II|2\.|U\s*16)\b',s,re.I) else 'u17'
 if re.search(r'\bC-Junioren\b|\bU\s*(?:14|15)\b',s,re.I): return 'u14' if re.search(r'\b(?:II|2\.|U\s*14)\b',s,re.I) else 'u15'
 if re.search(r'\bD-Junioren\b|\bU\s*(?:12|13)\b',s,re.I): return 'u12' if re.search(r'\b(?:II|2\.|U\s*12)\b',s,re.I) else 'u13'
 if re.search(r'\bE-Junioren\b|\bU\s*11\b',s,re.I): return 'u11'
 return None
def parse(text,club,homes):
 lines=[' '.join(x.split()) for x in text.replace('\xa0',' ').splitlines() if x.strip()]; out=[]; seen=set()
 for i,line in enumerate(lines):
  dm=DATE_RE.search(line)
  if not dm: continue
  d,m,y,t=dm.groups(); y='20'+y if len(y)==2 else y; date=f'{y}-{int(m):02d}-{int(d):02d}'; time=t.zfill(5)
  block='\n'.join(lines[max(0,i-6):min(len(lines),i+14)]); pair=None
  for c in lines[i:min(len(lines),i+14)]:
   p=re.split(r'\s+:\s+|\s+-\s+',c,maxsplit=1)
   if len(p)==2 and any(h.lower() in p[0].lower() for h in homes): pair=(p[0].strip(),p[1].strip()); break
  if not pair: continue
  home,away=pair; tid='sgv' if club=='sgv' else team_id(block+' '+home)
  if not tid: continue
  no=(re.search(r'\b(?:FS|ME|PO)\s*\|\s*(\d{6,})',block) or [None,''])[1]
  gid='fd-'+hashlib.sha1('|'.join([club,no,date,time,home.lower(),away.lower()]).encode()).hexdigest()[:20]
  if gid in seen: continue
  seen.add(gid); status='abgesetzt' if re.search(r'Absetzung|abgesetzt',block,re.I) else 'angesetzt'
  out.append({'id':gid,'teamId':tid,'club':club,'label':LABEL[tid],'date':date,'time':time,'opponent':away,'venue':CFG['venueDefault'],'source':'FUSSBALL.DE','status':status,'gameNo':no})
 return out
async def body(page,url,club=False):
 await page.goto(url,wait_until='domcontentloaded',timeout=90000); await page.wait_for_timeout(6000)
 for name in ['Alle akzeptieren','Akzeptieren','Zustimmen']:
  try: await page.get_by_role('button',name=re.compile(name,re.I)).click(timeout=1000); break
  except Exception: pass
 if club:
  for name in ['Vereinsspielplan','Spielplan','Spiele']:
   try: await page.get_by_text(name,exact=False).first.click(timeout=2500); await page.wait_for_timeout(3500); break
   except Exception: pass
 return await page.locator('body').inner_text()
async def main():
 games=[]; warnings=[]
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True); page=await browser.new_page(locale='de-DE',user_agent='Mozilla/5.0 Chrome/124 Safari/537.36')
  for key,isclub in [('vfr',True),('sgv',False)]:
   try:
    c=CFG[key]; games+=parse(await body(page,c.get('url') or c['teamUrl'],isclub),key,c['homeNames'])
   except Exception as e: warnings.append(f'{key.upper()}: {e}')
  await browser.close()
 games=sorted({g['id']:g for g in games if g['status']!='abgesetzt'}.values(),key=lambda g:(g['date'],g['time'],g['teamId']))
 old={}
 if OUT.exists():
  try: old=json.loads(OUT.read_text(encoding='utf-8'))
  except Exception: pass
 if not games and old.get('games'): raise SystemExit('0 Spiele; vorhandene JSON bleibt erhalten. '+'; '.join(warnings))
 OUT.write_text(json.dumps({'schema':1,'updatedAt':datetime.now(timezone.utc).isoformat(),'source':'FUSSBALL.DE','games':games,'warnings':warnings},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print(f'{len(games)} Spiele geschrieben; {len(warnings)} Warnungen')
if __name__=='__main__': asyncio.run(main())
