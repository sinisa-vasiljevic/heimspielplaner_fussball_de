#!/usr/bin/env python3
import asyncio
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / 'sync_config.json').read_text(encoding='utf-8'))
OUT = ROOT / 'spiele-live.json'

DATE_RE = re.compile(r'(?:(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*,?\s*)?(\d{1,2})\.(\d{1,2})\.(\d{2,4}).*?([0-2]?\d:[0-5]\d)', re.I)
INFO_RE = re.compile(r'\b(ME|FS|PO|TU)\s*\|\s*(\d{6,})')
TIME_RE = re.compile(r'(?<!\d)([0-2]?\d:[0-5]\d)(?!\d)')
EXCLUDED_TYPES = {str(x).upper() for x in CFG.get('excludeCompetitionTypes', ['TU'])}
DETAIL_CONCURRENCY = 3


def clean(value):
    return re.sub(r'\s+', ' ', str(value).replace('\xa0', ' ').replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').replace('\ufeff', '')).strip()


def normalize(value):
    value = clean(value).lower()
    for old, new in {'ä': 'ae', 'ö': 'oe', 'ü': 'ue', 'ß': 'ss'}.items():
        value = value.replace(old, new)
    return re.sub(r'\s+', ' ', re.sub(r'[^a-z0-9]+', ' ', value)).strip()


def extract_venue(lines, row_index):
    stop = min(len(lines), row_index + 18)
    block = lines[row_index + 3:stop]
    for pos, value in enumerate(block):
        if DATE_RE.search(value) or (pos > 0 and value == ':'):
            break
        direct = re.search(r'(?:spielstätte|spielstaette|spielort|austragungsort)\s*:?\s*(.+)$', value, re.I)
        if direct and clean(direct.group(1)):
            return clean(direct.group(1))
        if re.fullmatch(r'(?:spielstätte|spielstaette|spielort|austragungsort)\s*:?', value, re.I) and pos + 1 < len(block):
            return clean(block[pos + 1])
    for value in block:
        if re.search(r'\b(?:stadion|sportplatz|sportgelände|sportgelaende|rasenplatz|kunstrasenplatz|arena|leingarten)\b', value.lower()):
            return clean(value)
    return ''


def is_local_venue(venue):
    if not venue:
        return True
    needles = [clean(x).lower() for x in CFG.get('localVenueNeedles', [CFG.get('venueDefault', 'Frankenstadion')]) if clean(x)]
    low = clean(venue).lower()
    return any(needle in low for needle in needles)


def surface_from(*values):
    text = ' '.join(clean(v).lower() for v in values if v)
    if 'kunstrasen' in text:
        return 'kunstrasen'
    if 'hybridrasen' in text:
        return 'hybridrasen'
    if 'hartplatz' in text:
        return 'hartplatz'
    if re.search(r'\b(?:naturrasen|rasenplatz|rasen)\b', text):
        return 'rasen'
    return 'unbekannt'


def parse_games(text, key, cfg):
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    try:
        start = lines.index('MANNSCHAFTSSPIELPLAN')
    except ValueError:
        start = 0
    try:
        end = lines.index('Legende', start + 1)
    except ValueError:
        end = len(lines)
    lines = lines[start:end]
    club_needle = 'sgv heilbronn-freiberg' if cfg['club'] == 'sgv' else 'vfr heilbronn'
    games, seen = [], set()
    current_date = current_time = current_type = current_no = None
    i = 0
    while i < len(lines):
        line = lines[i]
        dm = DATE_RE.search(line)
        if dm:
            d, m, y, tm = dm.groups()
            y = '20' + y if len(y) == 2 else y
            current_date = f'{y}-{int(m):02d}-{int(d):02d}'
            current_time = tm.zfill(5)
        elif current_date:
            mt = TIME_RE.search(line)
            if mt:
                current_time = mt.group(1).zfill(5)
        info = INFO_RE.search(line)
        if info:
            current_type, current_no = info.groups()
        if i + 2 < len(lines) and lines[i + 1] == ':' and current_date and current_time:
            home, away = lines[i], lines[i + 2]
            tail = '\n'.join(lines[i:min(len(lines), i + 18)])
            ctype = (current_type or '').upper()
            is_home = club_needle in home.lower()
            is_away = club_needle in away.lower()
            actual_venue = extract_venue(lines, i)
            is_relocated = is_home and bool(actual_venue) and not is_local_venue(actual_venue)
            if (is_home or is_away) and ctype not in EXCLUDED_TYPES:
                stable = (cfg['teamId'] + '|' + current_no) if current_no else '|'.join([cfg['teamId'], home.lower(), away.lower(), CFG['season']])
                gid = 'fd-' + hashlib.sha1(stable.encode()).hexdigest()[:20]
                if gid not in seen:
                    seen.add(gid)
                    games.append({
                        'id': gid, 'teamId': key, 'externalTeamId': cfg['teamId'], 'club': cfg['club'], 'label': cfg['label'],
                        'date': current_date, 'time': current_time, 'homeTeam': home, 'awayTeam': away,
                        'locationType': 'relocated' if is_relocated else ('home' if is_home else 'away'),
                        'opponent': away if is_home else home,
                        'venue': actual_venue or (CFG.get('venueDefault', 'Frankenstadion') if is_home else home),
                        'pitch': '', 'surface': 'unbekannt', 'venueDetail': '', 'detailUrl': '', 'detailStatus': 'nicht_geladen',
                        'source': 'FUSSBALL.DE',
                        'status': 'abgesetzt' if re.search(r'Absetzung|abgesetzt', tail, re.I) else 'angesetzt',
                        'gameNo': current_no or '', 'competitionType': current_type or ''
                    })
            current_time = current_type = current_no = None
            i += 2
        i += 1
    return games


async def accept_cookies(page):
    for name in ['Alle akzeptieren', 'Akzeptieren', 'Zustimmen']:
        try:
            await page.get_by_role('button', name=re.compile(name, re.I)).click(timeout=1500)
            await page.wait_for_timeout(1200)
            break
        except Exception:
            pass


async def load_team_page(page, cfg):
    await page.goto(cfg['url'], wait_until='domcontentloaded', timeout=90000)
    await page.wait_for_timeout(7000)
    await accept_cookies(page)
    for _ in range(8):
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(450)
    text = await page.locator('body').inner_text()
    links = await page.locator('a[href*="/spiel/"]').evaluate_all("""els => els.map(a => { const contexts=[]; let n=a; for(let i=0;n&&i<7;i++,n=n.parentElement){ const t=(n.innerText||n.textContent||'').trim(); if(t&&!contexts.includes(t)) contexts.push(t); } return {href:a.href||a.getAttribute('href')||'', text:(a.innerText||a.textContent||''), contexts}; })""")
    unique = {}
    for item in links:
        href = clean(item.get('href', ''))
        if href and '/spiel/' in href:
            href = urljoin('https://www.fussball.de/', href)
            contexts = [clean(x) for x in item.get('contexts', []) if clean(x)]
            unique[href] = {'href': href, 'text': clean(item.get('text', '')), 'context': '\n'.join(contexts)}
    return text, list(unique.values())


def match_link(game, links):
    game_no = clean(game.get('gameNo', ''))
    if game_no:
        exact = [x['href'] for x in links if game_no in (x['text'] + ' ' + x['context'])]
        if len(exact) == 1:
            return exact[0]
    home, away = normalize(game.get('homeTeam')), normalize(game.get('awayTeam'))
    candidates = []
    for item in links:
        context = normalize(item['text'] + ' ' + item['context'])
        if home and away and home in context and away in context:
            candidates.append(item['href'])
    return candidates[0] if len(candidates) == 1 else ''


def parse_detail(text):
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    start = -1
    for i, value in enumerate(lines):
        if normalize(value).rstrip(':') in {'ort', 'spielort', 'spielstaette', 'austragungsort'}:
            start = i
            break
    if start < 0:
        return '', '', 'unbekannt'
    stop_words = {'schiedsrichter', 'spieldetails', 'spielinfos', 'tabelle', 'liveticker', 'aufstellung', 'aufstellungen', 'statistik', 'ticker', 'wettbewerb', 'staffel'}
    block = []
    for value in lines[start + 1:start + 15]:
        if normalize(value).rstrip(':') in stop_words:
            break
        block.append(value)
    patterns = [r'\bkunstrasenplatz\b', r'\bnaturrasenplatz\b', r'\brasenplatz\b', r'\bhybridrasenplatz\b', r'\bhartplatz\b', r'\bhauptplatz\b', r'\bnebenplatz\b', r'\bplatz\s*\d+\b']
    pitch = next((v for v in reversed(block) if any(re.search(p, v, re.I) for p in patterns)), '')
    venue_detail = next((v for v in block if v != pitch and not re.search(r'\b\d{5}\b', v) and not (re.search(r'\d', v) and re.search(r'\b(?:straße|strasse|str\.|weg|allee)\b', v, re.I))), '')
    return venue_detail, pitch, surface_from(pitch, venue_detail)


async def enrich_game(context, game, semaphore):
    if game.get('locationType') != 'home' or not game.get('detailUrl'):
        game['detailStatus'] = 'nicht_erforderlich' if game.get('locationType') != 'home' else 'link_fehlt'
        return
    async with semaphore:
        page = await context.new_page()
        try:
            await page.goto(game['detailUrl'], wait_until='domcontentloaded', timeout=90000)
            await page.wait_for_timeout(5000)
            await accept_cookies(page)
            venue_detail, pitch, surface = parse_detail(await page.locator('body').inner_text())
            game.update({'venueDetail': venue_detail, 'pitch': pitch, 'surface': surface, 'detailStatus': 'geladen' if pitch else 'platz_nicht_gefunden'})
        except Exception as exc:
            game['detailStatus'] = 'fehler'
            game['detailError'] = clean(exc)
        finally:
            await page.close()


def retain_old_details(games, old):
    old_by_id = {g.get('id'): g for g in old.get('games', []) if g.get('id')}
    for game in games:
        previous = old_by_id.get(game.get('id'))
        if not previous or game.get('detailStatus') == 'geladen':
            continue
        for field, default in [('pitch', ''), ('surface', 'unbekannt'), ('venueDetail', ''), ('detailUrl', '')]:
            if game.get(field) in ('', default) and previous.get(field):
                game[field] = previous[field]
        if game.get('pitch'):
            game['detailStatus'] = 'altbestand_beibehalten'


async def main():
    games, warnings, counts = [], [], {}
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding='utf-8'))
        except Exception:
            pass
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale='de-DE', user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36')
        page = await context.new_page()
        for key, cfg in CFG['teams'].items():
            try:
                text, links = await load_team_page(page, cfg)
                found = parse_games(text, key, cfg)
                for game in found:
                    game['detailUrl'] = match_link(game, links)
                active = [g for g in found if g['status'] != 'abgesetzt']
                games.extend(active)
                counts[key] = len(active)
                home = [g for g in active if g['locationType'] == 'home']
                linked = [g for g in home if g.get('detailUrl')]
                if len(linked) != len(home):
                    warnings.append(f'{key}: Detail-Link für {len(linked)} von {len(home)} Heimspielen gefunden')
                print(key, cfg['teamId'], len(active), 'Detail-Links', len(linked), '/', len(home))
            except Exception as exc:
                counts[key] = 0
                warnings.append(f'{key}: {clean(exc)}')
        semaphore = asyncio.Semaphore(DETAIL_CONCURRENCY)
        await asyncio.gather(*(enrich_game(context, game, semaphore) for game in games))
        await page.close()
        await browser.close()
    games = sorted({g['id']: g for g in games}.values(), key=lambda g: (g['date'], g['time'], g['teamId']))
    retain_old_details(games, old)
    if not games and old.get('games'):
        raise SystemExit('Abruf ergab 0 Spiele; gültige JSON bleibt erhalten. ' + '; '.join(warnings))
    home = [g for g in games if g.get('locationType') == 'home']
    with_pitch = [g for g in home if g.get('pitch')]
    missing = [g for g in home if not g.get('pitch')]
    if missing:
        warnings.append('Keine Platzinformation für ' + str(len(missing)) + ' Heimspiele: ' + ', '.join(f"{g['teamId']} {g['date']} {g['time']}" for g in missing[:10]))
    result = {
        'schema': 5,
        'updatedAt': datetime.now(timezone.utc).isoformat(),
        'source': 'FUSSBALL.DE',
        'counts': counts,
        'detailCounts': {'homeGames': len(home), 'homeGamesWithPitch': len(with_pitch), 'homeGamesWithoutPitch': len(missing)},
        'games': games,
        'warnings': warnings
    }
    OUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Gesamt:', len(games), 'Heimspiele mit Platz:', len(with_pitch), 'Warnungen:', warnings)


if __name__ == '__main__':
    asyncio.run(main())
