#!/usr/bin/env python3
import asyncio, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'sync_config.json').read_text(encoding='utf-8'))
OUT=ROOT/'spiele-live.json'
DATE_RE=re.compile(r'(?:(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*,?\s*)?(\d{1,2})\.(\d{1,2})\.(\d{2,4}).{0,50}?([0-2]?\d:[0-5]\d)',re.I)
def parse_games(text,key,cfg):
 lines=[' '.join(x.split()) for x in text.replace('\xa0',' ').splitlines() if x.strip()]; out=[]; seen=set()
 for i,line in enumerate(lines):
  dm=DATE_RE.search(line)
  if not dm: continue
  d,m,y,tm=dm.groups(); y='20'+y if len(y)==2 else y; date=f'{y}-{int(m):02d}-{int(d):02d}'; tm=tm.zfill(5)
  block='\n'.join(lines[max(0,i-8):min(len(lines),i+18)]); pair=None
  for candidate in lines[i:min(len(lines),i+18)]:
   parts=re.split(r'\s+:\s+|\s+-\s+',candidate,maxsplit=1)
   if len(parts)==2 and any(h.lower() in parts[0].lower() for h in cfg['homeNames']): pair=(parts[0].strip(),parts[1].strip()); break
  if not pair: continue
  home,away=pair; nm=re.search(r'\b(?:FS|ME|PO)\s*\|\s*(\d{6,})',block); no=nm.group(1) if nm else ''
  stable=(cfg['teamId']+'|'+no) if no else '|'.join([cfg['teamId'],home.lower(),away.lower(),CFG['season']])
  gid='fd-'+hashlib.sha1(stable.encode()).hexdigest()[:20]
  if gid in seen: continue
  seen.add(gid); status='abgesetzt' if re.search(r'Absetzung|abgesetzt',block,re.I) else 'angesetzt'
  out.append({'id':gid,'teamId':key,'externalTeamId':cfg['teamId'],'club':cfg['club'],'label':cfg['label'],'date':date,'time':tm,'opponent':away,'venue':CFG.get('venueDefault','Frankenstadion'),'source':'FUSSBALL.DE','status':status,'gameNo':no})
 return out
async def load(page,url):
 await page.goto(url,wait_until='domcontentloaded',timeout=90000); await page.wait_for_timeout(6000)
 for name in ['Alle akzeptieren','Akzeptieren','Zustimmen']:
  try: await page.get_by_role('button',name=re.compile(name,re.I)).click(timeout=1200); await page.wait_for_timeout(1200); break
  except Exception: pass
 for _ in range(6): await page.mouse.wheel(0,1400); await page.wait_for_timeout(450)
 return await page.locator('body').inner_text()
async def main():
 games=[]; warnings=[]; counts={}
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True); page=await browser.new_page(locale='de-DE',user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36')
  for key,cfg in CFG['teams'].items():
   try:
    found=parse_games(await load(page,cfg['url']),key,cfg); games.extend(found); counts[key]=len(found); print(f'{key}: {len(found)} Heimspiele')
   except Exception as exc: counts[key]=0; warnings.append(f'{key}: {exc}')
  await browser.close()
 games=sorted({g['id']:g for g in games if g['status']!='abgesetzt'}.values(),key=lambda g:(g['date'],g['time'],g['teamId']))
 old={}
 if OUT.exists():
  try: old=json.loads(OUT.read_text(encoding='utf-8'))
  except Exception: pass
 if not games and old.get('games'): raise SystemExit('Abruf ergab 0 Spiele; gültige JSON bleibt erhalten. '+'; '.join(warnings))
 OUT.write_text(json.dumps({'schema':2,'updatedAt':datetime.now(timezone.utc).isoformat(),'source':'FUSSBALL.DE','counts':counts,'games':games,'warnings':warnings},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('Gesamt:',len(games),'Counts:',counts,'Warnungen:',warnings)
if __name__=='__main__': asyncio.run(main())
