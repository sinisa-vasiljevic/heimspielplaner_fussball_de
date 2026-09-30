#!/usr/bin/env python3
import asyncio, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / 'sync_config.json').read_text(encoding='utf-8'))
OUT = ROOT / 'spiele-live.json'
DATE_RE = re.compile(r'(?:(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*,?\s*)?(\d{1,2})\.(\d{1,2})\.(\d{2,4}).*?([0-2]?\d:[0-5]\d)', re.I)
INFO_RE = re.compile(r'\b(ME|FS|PO|TU)\s*\|\s*(\d{6,})')
TIME_RE = re.compile(r'(?<!\d)([0-2]?\d:[0-5]\d)(?!\d)')
EXCLUDED_TYPES = {str(x).upper() for x in CFG.get('excludeCompetitionTypes', ['TU'])}


def clean(value):
    return re.sub(r'\s+', ' ', str(value)
                  .replace('\xa0', ' ')
                  .replace('\u200b', '')
                  .replace('\u200c', '')
                  .replace('\u200d', '')
                  .replace('\ufeff', '')).strip()


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
            time_match = TIME_RE.search(line)
            if time_match:
                current_time = time_match.group(1).zfill(5)
        info = INFO_RE.search(line)
        if info:
            current_type, current_no = info.groups()
        if i + 2 < len(lines) and lines[i + 1] == ':' and current_date and current_time:
            home, away = lines[i], lines[i + 2]
            tail = '\n'.join(lines[i:min(len(lines), i + 7)])
            competition_type = (current_type or '').upper()
            # TU = Turnier. Die zuerst genannte Mannschaft ist dort nicht automatisch
            # Gastgeber am eigenen Platz. Solche Einträge dürfen den Heimspielplan,
            # Verkauf, freie Slots, Kollisionen und Kabinen nicht belegen.
            if club_needle in home.lower() and competition_type not in EXCLUDED_TYPES:
                stable = (cfg['teamId'] + '|' + current_no) if current_no else '|'.join([cfg['teamId'], home.lower(), away.lower(), CFG['season']])
                gid = 'fd-' + hashlib.sha1(stable.encode()).hexdigest()[:20]
                if gid not in seen:
                    seen.add(gid)
                    games.append({
                        'id': gid,
                        'teamId': key,
                        'externalTeamId': cfg['teamId'],
                        'club': cfg['club'],
                        'label': cfg['label'],
                        'date': current_date,
                        'time': current_time,
                        'opponent': away,
                        'venue': CFG.get('venueDefault', 'Frankenstadion'),
                        'source': 'FUSSBALL.DE',
                        'status': 'abgesetzt' if re.search(r'Absetzung|abgesetzt', tail, re.I) else 'angesetzt',
                        'gameNo': current_no or '',
                        'competitionType': current_type or ''
                    })
            # Match-specific values must not leak into the next row.
            current_time = None
            current_type = None
            current_no = None
            i += 2
        i += 1
    return games


async def load(page, cfg):
    await page.goto(cfg['url'], wait_until='domcontentloaded', timeout=90000)
    await page.wait_for_timeout(7000)
    for name in ['Alle akzeptieren', 'Akzeptieren', 'Zustimmen']:
        try:
            await page.get_by_role('button', name=re.compile(name, re.I)).click(timeout=1500)
            await page.wait_for_timeout(1200)
            break
        except Exception:
            pass
    for _ in range(8):
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(450)
    return await page.locator('body').inner_text()


async def main():
    games, warnings, counts = [], [], {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale='de-DE', user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36')
        for key, cfg in CFG['teams'].items():
            try:
                found = parse_games(await load(page, cfg), key, cfg)
                active = [g for g in found if g['status'] != 'abgesetzt']
                games.extend(active)
                counts[key] = len(active)
                print(f'{key} {cfg["teamId"]} {len(active)}')
            except Exception as exc:
                counts[key] = 0
                warnings.append(f'{key}: {exc}')
        await browser.close()
    games = sorted({g['id']: g for g in games}.values(), key=lambda g: (g['date'], g['time'], g['teamId']))
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding='utf-8'))
        except Exception:
            pass
    if not games and old.get('games'):
        raise SystemExit('Abruf ergab 0 Spiele; gültige JSON bleibt erhalten. ' + '; '.join(warnings))
    OUT.write_text(json.dumps({
        'schema': 3,
        'updatedAt': datetime.now(timezone.utc).isoformat(),
        'source': 'FUSSBALL.DE',
        'counts': counts,
        'games': games,
        'warnings': warnings
    }, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Gesamt:', len(games), 'Warnungen:', warnings)


if __name__ == '__main__':
    asyncio.run(main())
