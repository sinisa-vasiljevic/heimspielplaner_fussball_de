#!/usr/bin/env python3
import asyncio, hashlib, json, re
from urllib.parse import urljoin, unquote
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright
ROOT=Path(__file__).resolve().parents[1]
CFG=json.loads((ROOT/'sync_config.json').read_text(encoding='utf-8'))
OUT=ROOT/'spiele-live.json'
DATE_RE=re.compile(r'(?:(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*,?\s*)?(\d{1,2})\.(\d{1,2})\.(\d{2,4}).*?([0-2]?\d:[0-5]\d)',re.I)
INFO_RE=re.compile(r'\b(ME|FS|PO|TU)\s*\|\s*(\d{6,})')
TIME_RE=re.compile(r'(?<!\d)([0-2]?\d:[0-5]\d)(?!\d)')
EXCLUDED_TYPES={str(x).upper() for x in CFG.get('excludeCompetitionTypes',['TU'])}
def clean(value): return re.sub(r'\s+',' ',str(value).replace('\xa0',' ').replace('\u200b','').replace('\u200c','').replace('\u200d','').replace('\ufeff','')).strip()
def extract_venue(lines, row_index):
    # FUSSBALL.DE writes the ground either as "Spielstätte: ..." or on a
    # following line. Search only inside the current match block.
    stop = min(len(lines), row_index + 18)
    block = lines[row_index + 3:stop]
    for pos, value in enumerate(block):
        low = value.lower()
        if DATE_RE.search(value) or (pos > 0 and value == ':'):
            break
        direct = re.search(r'(?:spielstätte|spielstaette|spielort|austragungsort)\s*:?\s*(.+)$', value, re.I)
        if direct and clean(direct.group(1)):
            return clean(direct.group(1))
        if re.fullmatch(r'(?:spielstätte|spielstaette|spielort|austragungsort)\s*:?', value, re.I):
            if pos + 1 < len(block):
                return clean(block[pos + 1])
    # Fallback for common ground/stadium/address lines.
    for value in block:
        low = value.lower()
        if re.search(r'\b(?:stadion|sportplatz|sportgelände|sportgelaende|rasenplatz|kunstrasenplatz|arena|leingarten)\b', low):
            return clean(value)
    return ''

def is_local_venue(venue):
    if not venue:
        return True
    needles = [clean(x).lower() for x in CFG.get('localVenueNeedles', [CFG.get('venueDefault', 'Frankenstadion')]) if clean(x)]
    low = clean(venue).lower()
    return any(needle in low for needle in needles)


def normalize(value):
    value=clean(value).lower()
    for old,new in {'ä':'ae','ö':'oe','ü':'ue','ß':'ss'}.items(): value=value.replace(old,new)
    return re.sub(r'[^a-z0-9]+',' ',value).strip()

def surface_from(value):
    value=clean(value).lower()
    if 'kunstrasen' in value:return 'kunstrasen'
    if 'hybridrasen' in value:return 'hybridrasen'
    if 'hartplatz' in value:return 'hartplatz'
    if re.search(r'\b(?:naturrasen|rasenplatz|rasen)\b',value):return 'rasen'
    return 'unbekannt'

def extract_match_urls(raw):
    if not raw:return []
    raw=unquote(str(raw)).replace('\\/','/')
    patterns=[
      r'https?://www\.fussball\.de/spiel/[^"\'<>\s]+/-/spiel/[A-Z0-9]+',
      r'/spiel/[^"\'<>\s]+/-/spiel/[A-Z0-9]+'
    ]
    out=[]
    for pattern in patterns:
      for hit in re.findall(pattern,raw,re.I):
        hit=hit.split('#')[0].split('?')[0].rstrip('\\,;)}]')
        hit=urljoin('https://www.fussball.de/',hit)
        if hit not in out:out.append(hit)
    return out

def match_detail_url(game,urls):
    home=set(normalize(game.get('homeTeam','')).split())-{'i','ii','iii','fussball'}
    away=set(normalize(game.get('awayTeam','')).split())-{'i','ii','iii','fussball'}
    ranked=[]
    for url in urls:
      slug=normalize(url.split('/-/spiel/')[0].rsplit('/spiel/',1)[-1])
      tokens=set(slug.split())
      score=len(home & tokens)+len(away & tokens)
      home_ok=len(home & tokens)>=min(2,max(1,len(home)))
      away_ok=len(away & tokens)>=min(2,max(1,len(away)))
      if home_ok and away_ok:ranked.append((score,url))
    ranked.sort(reverse=True)
    return ranked[0][1] if ranked and (len(ranked)==1 or ranked[0][0]>ranked[1][0]) else ''

def parse_detail(text):
    lines=[clean(x) for x in text.splitlines() if clean(x)]
    start=next((i for i,x in enumerate(lines) if normalize(x).rstrip(':') in {'ort','spielort','spielstaette','austragungsort'}),-1)
    if start<0:return '','','unbekannt'
    stops={'schiedsrichter','spieldetails','spielinfos','tabelle','liveticker','aufstellung','aufstellungen','statistik','ticker','wettbewerb','staffel'}
    block=[]
    for value in lines[start+1:start+15]:
      if normalize(value).rstrip(':') in stops:break
      block.append(value)
    patterns=[r'\bkunstrasenplatz\b',r'\bnaturrasenplatz\b',r'\brasenplatz\b',r'\bhybridrasenplatz\b',r'\bhartplatz\b',r'\bhauptplatz\b',r'\bnebenplatz(?:\s*\d+)?\b',r'\bplatz\s*\d+\b']
    pitch=next((v for v in reversed(block) if any(re.search(p,v,re.I) for p in patterns)),'')
    venue=next((v for v in block if v!=pitch and not re.search(r'\b\d{5}\b',v) and not (re.search(r'\d',v) and re.search(r'\b(?:straße|strasse|str\.|weg|allee)\b',v,re.I))),'')
    return venue,pitch,surface_from(pitch+' '+venue)

def parse_games(text,key,cfg):
 lines=[clean(x) for x in text.splitlines() if clean(x)]
 try:start=lines.index('MANNSCHAFTSSPIELPLAN')
 except ValueError:start=0
 try:end=lines.index('Legende',start+1)
 except ValueError:end=len(lines)
 lines=lines[start:end];club_needle='sgv heilbronn-freiberg' if cfg['club']=='sgv' else 'vfr heilbronn';games=[];seen=set();current_date=current_time=current_type=current_no=None;i=0
 while i<len(lines):
  line=lines[i];dm=DATE_RE.search(line)
  if dm:
   d,m,y,tm=dm.groups();y='20'+y if len(y)==2 else y;current_date=f'{y}-{int(m):02d}-{int(d):02d}';current_time=tm.zfill(5)
  elif current_date:
   mt=TIME_RE.search(line)
   if mt:current_time=mt.group(1).zfill(5)
  info=INFO_RE.search(line)
  if info:current_type,current_no=info.groups()
  if i+2<len(lines) and lines[i+1]==':' and current_date and current_time:
   home,away=lines[i],lines[i+2];tail='\n'.join(lines[i:min(len(lines),i+18)]);ctype=(current_type or '').upper();is_home=club_needle in home.lower();is_away=club_needle in away.lower();actual_venue=extract_venue(lines,i);is_relocated=is_home and bool(actual_venue) and not is_local_venue(actual_venue)
   if (is_home or is_away) and ctype not in EXCLUDED_TYPES:
    stable=(cfg['teamId']+'|'+current_no) if current_no else '|'.join([cfg['teamId'],home.lower(),away.lower(),CFG['season']]);gid='fd-'+hashlib.sha1(stable.encode()).hexdigest()[:20]
    if gid not in seen:
     seen.add(gid);games.append({'id':gid,'teamId':key,'externalTeamId':cfg['teamId'],'club':cfg['club'],'label':cfg['label'],'date':current_date,'time':current_time,'homeTeam':home,'awayTeam':away,'locationType':'relocated' if is_relocated else ('home' if is_home else 'away'),'opponent':away if is_home else home,'venue':actual_venue or (CFG.get('venueDefault','Frankenstadion') if is_home else home),'pitch':'','surface':'unbekannt','venueDetail':'','detailUrl':'','detailStatus':'nicht_geladen','source':'FUSSBALL.DE','status':'abgesetzt' if re.search(r'Absetzung|abgesetzt',tail,re.I) else 'angesetzt','gameNo':current_no or '','competitionType':current_type or ''})
   current_time=current_type=current_no=None;i+=2
  i+=1
 return games
async def accept_cookies(page):
 for name in ['Alle akzeptieren','Akzeptieren','Zustimmen']:
  try:await page.get_by_role('button',name=re.compile(name,re.I)).click(timeout=1500);await page.wait_for_timeout(1200);break
  except Exception:pass

async def load(page,cfg):
 captured=[]
 async def capture(response):
  try:
   if 'fussball.de' not in response.url:return
   ctype=(response.headers.get('content-type') or '').lower()
   if not any(x in ctype for x in ('json','html','text','javascript')):return
   body=await response.text()
   if len(body)<5000000:captured.append(body)
  except Exception:pass
 page.on('response',capture)
 try:
  await page.goto(cfg['url'],wait_until='domcontentloaded',timeout=90000);await page.wait_for_timeout(7000)
  await accept_cookies(page)
  for _ in range(8):await page.mouse.wheel(0,1500);await page.wait_for_timeout(450)
  body=await page.locator('body').inner_text()
  html=await page.content()
  attrs=await page.locator('*').evaluate_all("""els=>els.flatMap(e=>Array.from(e.attributes||[]).map(a=>a.value)).filter(v=>v&&(/spiel/i.test(v)||/match/i.test(v)))""")
  raw='\n'.join([html]+captured+attrs)
  return body,extract_match_urls(raw)
 finally:
  page.remove_listener('response',capture)

async def enrich(context,game,semaphore):
 if game.get('locationType')!='home':game['detailStatus']='nicht_erforderlich';return
 if not game.get('detailUrl'):game['detailStatus']='link_fehlt';return
 async with semaphore:
  page=await context.new_page()
  try:
   await page.goto(game['detailUrl'],wait_until='domcontentloaded',timeout=90000);await page.wait_for_timeout(5000);await accept_cookies(page)
   venue,pitch,surface=parse_detail(await page.locator('body').inner_text())
   game.update({'venueDetail':venue,'pitch':pitch,'surface':surface,'detailStatus':'geladen' if pitch else 'platz_nicht_gefunden'})
  except Exception as exc:game['detailStatus']='fehler';game['detailError']=clean(exc)
  finally:await page.close()

async def main():
 games=[];warnings=[];counts={};old={}
 if OUT.exists():
  try:old=json.loads(OUT.read_text(encoding='utf-8'))
  except Exception:pass
 async with async_playwright() as p:
  browser=await p.chromium.launch(headless=True);context=await browser.new_context(locale='de-DE',user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36');page=await context.new_page()
  for key,cfg in CFG['teams'].items():
   try:
    text,urls=await load(page,cfg);found=parse_games(text,key,cfg)
    for game in found:game['detailUrl']=match_detail_url(game,urls)
    active=[g for g in found if g['status']!='abgesetzt'];games.extend(active);counts[key]=len(active)
    home=[g for g in active if g['locationType']=='home'];linked=[g for g in home if g['detailUrl']]
    print(key,cfg['teamId'],len(active),'Detail-Links',len(linked),'/',len(home),'Kandidaten',len(urls))
    if len(linked)<len(home):warnings.append(f'{key}: Detail-Link für {len(linked)} von {len(home)} Heimspielen gefunden')
   except Exception as exc:counts[key]=0;warnings.append(f'{key}: {clean(exc)}')
  sem=asyncio.Semaphore(3);await asyncio.gather(*(enrich(context,g,sem) for g in games));await page.close();await browser.close()
 games=sorted({g['id']:g for g in games}.values(),key=lambda g:(g['date'],g['time'],g['teamId']))
 oldmap={g.get('id'):g for g in old.get('games',[]) if g.get('id')}
 for g in games:
  prev=oldmap.get(g['id'])
  if prev and g.get('detailStatus')!='geladen':
   for field in ('pitch','surface','venueDetail','detailUrl'):
    if not g.get(field) or g.get(field)=='unbekannt':g[field]=prev.get(field,g.get(field))
   if g.get('pitch'):g['detailStatus']='altbestand_beibehalten'
 if not games and old.get('games'):raise SystemExit('Abruf ergab 0 Spiele; gültige JSON bleibt erhalten. '+'; '.join(warnings))
 home=[g for g in games if g['locationType']=='home'];withpitch=[g for g in home if g.get('pitch')];missing=[g for g in home if not g.get('pitch')]
 if missing:warnings.append('Keine Platzinformation für '+str(len(missing))+' Heimspiele: '+', '.join(f"{g['teamId']} {g['date']} {g['time']}" for g in missing[:10]))
 OUT.write_text(json.dumps({'schema':5,'updatedAt':datetime.now(timezone.utc).isoformat(),'source':'FUSSBALL.DE','counts':counts,'detailCounts':{'homeGames':len(home),'homeGamesWithPitch':len(withpitch),'homeGamesWithoutPitch':len(missing)},'games':games,'warnings':warnings},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
 print('Gesamt:',len(games),'Heimspiele mit Platz:',len(withpitch),'Warnungen:',warnings)
if __name__=='__main__':asyncio.run(main())
