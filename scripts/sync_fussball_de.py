#!/usr/bin/env python3
import asyncio, hashlib, json, re
from datetime import datetime, timezone
from pathlib import Path
from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / 'sync_config.json').read_text(encoding='utf-8'))
OUT = ROOT / 'spiele-live.json'
DEBUG = ROOT / 'debug-fussballde'
DEBUG.mkdir(exist_ok=True)
DATE_RE = re.compile(r'(?:(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*,?\s*)?(\d{1,2})\.(\d{1,2})\.(\d{2,4}).{0,60}?([0-2]?\d:[0-5]\d)', re.I)


def clean(value):
    return re.sub(r'\s+', ' ', str(value).replace('\xa0', ' ').replace('\u200b', '').replace('\u200c', '').replace('\u200d', '').replace('\ufeff', '')).strip()


def parse_games(text, key, cfg):
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    homes = [clean(x).lower() for x in cfg['homeNames']]
    out, seen = [], set()
    for i, line in enumerate(lines):
        dm = DATE_RE.search(line)
        if not dm:
            continue
        d, m, y, tm = dm.groups()
        y = '20' + y if len(y) == 2 else y
        date, tm = f'{y}-{int(m):02d}-{int(d):02d}', tm.zfill(5)
        block_lines = lines[max(0, i - 10):min(len(lines), i + 24)]
        block = '\n'.join(block_lines)
        pair = None
        # Form 1: Heim : Gast oder Heim - Gast in einer Zeile
        for candidate in block_lines:
            parts = re.split(r'\s+:\s+|\s+-\s+', candidate, maxsplit=1)
            if len(parts) == 2 and any(h in clean(parts[0]).lower() for h in homes):
                pair = (clean(parts[0]), clean(parts[1]))
                break
        # Form 2: Heim / Doppelpunkt / Gast in getrennten Zeilen
        if not pair:
            for j in range(1, len(block_lines) - 1):
                if block_lines[j] in (':', '-', '–', '—') and any(h in block_lines[j-1].lower() for h in homes):
                    pair = (block_lines[j-1], block_lines[j+1])
                    break
        if not pair:
            continue
        home, away = pair
        nm = re.search(r'\b(?:FS|ME|PO)\s*\|\s*(\d{6,})', block)
        game_no = nm.group(1) if nm else ''
        stable = (cfg['teamId'] + '|' + game_no) if game_no else '|'.join([cfg['teamId'], home.lower(), away.lower(), CFG['season']])
        gid = 'fd-' + hashlib.sha1(stable.encode()).hexdigest()[:20]
        if gid in seen:
            continue
        seen.add(gid)
        status = 'abgesetzt' if re.search(r'Absetzung|abgesetzt', block, re.I) else 'angesetzt'
        out.append({
            'id': gid, 'teamId': key, 'externalTeamId': cfg['teamId'],
            'club': cfg['club'], 'label': cfg['label'], 'date': date,
            'time': tm, 'opponent': away, 'venue': CFG.get('venueDefault', 'Frankenstadion'),
            'source': 'FUSSBALL.DE', 'status': status, 'gameNo': game_no
        })
    return out


async def load(page, key, cfg):
    await page.goto(cfg['url'], wait_until='domcontentloaded', timeout=90000)
    await page.wait_for_timeout(7000)
    for name in ['Alle akzeptieren', 'Akzeptieren', 'Zustimmen']:
        try:
            await page.get_by_role('button', name=re.compile(name, re.I)).click(timeout=1500)
            await page.wait_for_timeout(1500)
            break
        except Exception:
            pass
    for _ in range(8):
        await page.mouse.wheel(0, 1500)
        await page.wait_for_timeout(500)
    text = await page.locator('body').inner_text()
    (DEBUG / f'{key}.txt').write_text(text, encoding='utf-8')
    await page.screenshot(path=str(DEBUG / f'{key}.png'), full_page=True)
    return text


async def main():
    games, warnings, counts = [], [], {}
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page(locale='de-DE', user_agent='Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36')
        for key, cfg in CFG['teams'].items():
            try:
                text = await load(page, key, cfg)
                found = parse_games(text, key, cfg)
                games.extend(found)
                counts[key] = len(found)
                print(f'{key} {cfg["teamId"]} {len(found)}')
            except Exception as exc:
                counts[key] = 0
                warnings.append(f'{key}: {exc}')
        await browser.close()

    games = sorted({g['id']: g for g in games if g['status'] != 'abgesetzt'}.values(), key=lambda g: (g['date'], g['time'], g['teamId']))
    old = {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding='utf-8'))
        except Exception:
            pass
    if not games and old.get('games'):
        raise SystemExit('Abruf ergab 0 Spiele; gültige JSON bleibt erhalten. ' + '; '.join(warnings))
    OUT.write_text(json.dumps({'schema': 2, 'updatedAt': datetime.now(timezone.utc).isoformat(), 'source': 'FUSSBALL.DE', 'counts': counts, 'games': games, 'warnings': warnings}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print('Gesamt:', len(games), 'Warnungen:', warnings)


if __name__ == '__main__':
    asyncio.run(main())
