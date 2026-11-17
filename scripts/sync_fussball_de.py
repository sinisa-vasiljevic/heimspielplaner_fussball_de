#!/usr/bin/env python3
import asyncio
import hashlib
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import unquote, urljoin

from playwright.async_api import async_playwright

ROOT = Path(__file__).resolve().parents[1]
CFG = json.loads((ROOT / "sync_config.json").read_text(encoding="utf-8"))
OUT = ROOT / "spiele-live.json"

DATE_RE = re.compile(r"(?:(?:Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*,?\s*)?(\d{1,2})\.(\d{1,2})\.(\d{2,4}).*?([0-2]?\d:[0-5]\d)", re.I)
INFO_RE = re.compile(r"\b(ME|FS|PO|TU)\s*\|\s*(\d{6,})")
TIME_RE = re.compile(r"(?<!\d)([0-2]?\d:[0-5]\d)(?!\d)")
EXCLUDED_TYPES = {str(x).upper() for x in CFG.get("excludeCompetitionTypes", ["TU"])}

PITCH_RE = re.compile(
    r"\b(Kunstrasenplatz(?:\s*\d+)?|Naturrasenplatz(?:\s*\d+)?|"
    r"Hybridrasenplatz(?:\s*\d+)?|Rasenplatz(?:\s*\d+)?|"
    r"Hartplatz(?:\s*\d+)?|Nebenplatz(?:\s*\d+)?|"
    r"Hauptplatz(?:\s*\d+)?|Platz\s*\d+)\b",
    re.I,
)


def clean(value):
    return re.sub(
        r"\s+",
        " ",
        str(value)
        .replace("\xa0", " ")
        .replace("\u200b", "")
        .replace("\u200c", "")
        .replace("\u200d", "")
        .replace("\ufeff", ""),
    ).strip()


def normalize(value):
    value = clean(value).lower()
    for old, new in {"ä": "ae", "ö": "oe", "ü": "ue", "ß": "ss"}.items():
        value = value.replace(old, new)
    return re.sub(r"[^a-z0-9]+", " ", value).strip()


def surface_from(value):
    value = clean(value).lower()
    if "kunstrasen" in value:
        return "kunstrasen"
    if "hybridrasen" in value:
        return "hybridrasen"
    if "hartplatz" in value:
        return "hartplatz"
    if re.search(r"\b(?:naturrasen|rasenplatz|rasen)\b", value):
        return "rasen"
    return "unbekannt"


def plain_url(value):
    """Entfernt HTML-Link-Markup und liefert ausschließlich die echte URL."""
    value = html.unescape(str(value or "")).replace("\\/", "/")
    href = re.search(r'href=["\'](https?://[^"\']+)', value, re.I)
    if href:
        return href.group(1).split("#")[0].split("?")[0]
    direct = re.search(r"https?://[^\s<>\"']+", value, re.I)
    if direct:
        return direct.group(0).split("#")[0].split("?")[0]
    return clean(value)


def extract_match_urls(raw):
    if not raw:
        return []
    raw = html.unescape(unquote(str(raw))).replace("\\/", "/")
    patterns = [
        r"https?://www\.fussball\.de/spiel/[^\"'<>\s]+/-/spiel/[A-Z0-9]+",
        r"/spiel/[^\"'<>\s]+/-/spiel/[A-Z0-9]+",
    ]
    out = []
    for pattern in patterns:
        for hit in re.findall(pattern, raw, re.I):
            hit = urljoin("https://www.fussball.de/", hit)
            hit = plain_url(hit)
            if hit not in out:
                out.append(hit)
    return out


def match_detail_url(game, urls):
    home = set(normalize(game.get("homeTeam", "")).split()) - {"i", "ii", "iii", "fussball"}
    away = set(normalize(game.get("awayTeam", "")).split()) - {"i", "ii", "iii", "fussball"}
    ranked = []
    for url in urls:
        url = plain_url(url)
        slug = normalize(url.split("/-/spiel/")[0].rsplit("/spiel/", 1)[-1])
        tokens = set(slug.split())
        score = len(home & tokens) + len(away & tokens)
        home_ok = len(home & tokens) >= min(2, max(1, len(home)))
        away_ok = len(away & tokens) >= min(2, max(1, len(away)))
        if home_ok and away_ok:
            ranked.append((score, url))
    ranked.sort(reverse=True)
    return ranked[0][1] if ranked and (len(ranked) == 1 or ranked[0][0] > ranked[1][0]) else ""


def parse_detail(text):
    """
    Liest den Platz direkt aus jeder sichtbaren Zeile.

    FUSSBALL.DE zeigt ihn beispielsweise so:
    'Kunstrasenplatz, Heilbronn Frankenstadion Kunstrasen, Badstr. 100, 74072 Heilbronn'
    Ein eigener Abschnitt 'ORT' ist dafür nicht erforderlich.
    """
    raw_lines = [clean(x) for x in str(text or "").splitlines() if clean(x)]

    for line in raw_lines:
        hit = PITCH_RE.search(line)
        if hit:
            pitch = clean(hit.group(1))
            remainder = clean(line[hit.end():].lstrip(" ,:-"))
            venue = remainder.split(",")[0].strip() if remainder else ""
            return venue, pitch, surface_from(pitch + " " + venue)

    # Fallback für Seiten, die nur den Belag ohne das Wort "Platz" ausgeben.
    for line in raw_lines:
        hit = re.search(r"\b(Kunstrasen|Naturrasen|Hybridrasen)\b", line, re.I)
        if hit:
            pitch = clean(hit.group(1) + "platz")
            return clean(line), pitch, surface_from(pitch + " " + line)

    return "", "", "unbekannt"


def extract_venue(lines, row_index):
    stop = min(len(lines), row_index + 18)
    block = lines[row_index + 3:stop]
    for pos, value in enumerate(block):
        if DATE_RE.search(value) or (pos > 0 and value == ":"):
            break
        direct = re.search(r"(?:spielstätte|spielstaette|spielort|austragungsort)\s*:?\s*(.+)$", value, re.I)
        if direct and clean(direct.group(1)):
            return clean(direct.group(1))
        if re.fullmatch(r"(?:spielstätte|spielstaette|spielort|austragungsort)\s*: ?", value, re.I):
            if pos + 1 < len(block):
                return clean(block[pos + 1])
    for value in block:
        if re.search(r"\b(?:stadion|sportplatz|sportgelände|sportgelaende|rasenplatz|kunstrasenplatz|arena|leingarten)\b", value, re.I):
            return clean(value)
    return ""


def is_local_venue(venue):
    if not venue:
        return True
    needles = [clean(x).lower() for x in CFG.get("localVenueNeedles", [CFG.get("venueDefault", "Frankenstadion")]) if clean(x)]
    low = clean(venue).lower()
    return any(needle in low for needle in needles)


def parse_games(text, key, cfg):
    lines = [clean(x) for x in text.splitlines() if clean(x)]
    try:
        start = lines.index("MANNSCHAFTSSPIELPLAN")
    except ValueError:
        start = 0
    try:
        end = lines.index("Legende", start + 1)
    except ValueError:
        end = len(lines)
    lines = lines[start:end]
    club_needle = "sgv heilbronn-freiberg" if cfg["club"] == "sgv" else "vfr heilbronn"
    games, seen = [], set()
    current_date = current_time = current_type = current_no = None
    i = 0
    while i < len(lines):
        line = lines[i]
        dm = DATE_RE.search(line)
        if dm:
            d, m, y, tm = dm.groups()
            y = "20" + y if len(y) == 2 else y
            current_date = f"{y}-{int(m):02d}-{int(d):02d}"
            current_time = tm.zfill(5)
        elif current_date:
            mt = TIME_RE.search(line)
            if mt:
                current_time = mt.group(1).zfill(5)
        info = INFO_RE.search(line)
        if info:
            current_type, current_no = info.groups()
        if i + 2 < len(lines) and lines[i + 1] == ":" and current_date and current_time:
            home, away = lines[i], lines[i + 2]
            tail = "\n".join(lines[i:min(len(lines), i + 18)])
            ctype = (current_type or "").upper()
            is_home = club_needle in home.lower()
            is_away = club_needle in away.lower()
            actual_venue = extract_venue(lines, i)
            is_relocated = is_home and bool(actual_venue) and not is_local_venue(actual_venue)
            if (is_home or is_away) and ctype not in EXCLUDED_TYPES:
                stable = cfg["teamId"] + "|" + current_no if current_no else "|".join([cfg["teamId"], home.lower(), away.lower(), CFG["season"]])
                gid = "fd-" + hashlib.sha1(stable.encode()).hexdigest()[:20]
                if gid not in seen:
                    seen.add(gid)
                    games.append({
                        "id": gid, "teamId": key, "externalTeamId": cfg["teamId"], "club": cfg["club"], "label": cfg["label"],
                        "date": current_date, "time": current_time, "homeTeam": home, "awayTeam": away,
                        "locationType": "relocated" if is_relocated else ("home" if is_home else "away"),
                        "opponent": away if is_home else home,
                        "venue": actual_venue or (CFG.get("venueDefault", "Frankenstadion") if is_home else home),
                        "pitch": "", "surface": "unbekannt", "venueDetail": "", "detailUrl": "", "detailStatus": "nicht_geladen",
                        "source": "FUSSBALL.DE", "status": "abgesetzt" if re.search(r"Absetzung|abgesetzt", tail, re.I) else "angesetzt",
                        "gameNo": current_no or "", "competitionType": current_type or "",
                    })
            current_time = current_type = current_no = None
            i += 2
        i += 1
    return games


async def accept_cookies(page):
    for name in ["Alle akzeptieren", "Akzeptieren", "Zustimmen"]:
        try:
            await page.get_by_role("button", name=re.compile(name, re.I)).click(timeout=1500)
            await page.wait_for_timeout(1200)
            break
        except Exception:
            pass


async def load(page, cfg):
    captured = []
    async def capture(response):
        try:
            if "fussball.de" not in response.url:
                return
            ctype = (response.headers.get("content-type") or "").lower()
            if not any(x in ctype for x in ("json", "html", "text", "javascript")):
                return
            body = await response.text()
            if len(body) < 5_000_000:
                captured.append(body)
        except Exception:
            pass
    page.on("response", capture)
    try:
        await page.goto(cfg["url"], wait_until="domcontentloaded", timeout=90000)
        await page.wait_for_timeout(7000)
        await accept_cookies(page)
        for _ in range(8):
            await page.mouse.wheel(0, 1500)
            await page.wait_for_timeout(450)
        body = await page.locator("body").inner_text()
        html_source = await page.content()
        attrs = await page.locator("*").evaluate_all("""els => els.flatMap(e => Array.from(e.attributes || []).map(a => a.value)).filter(v => v && (/spiel/i.test(v) || /match/i.test(v)))""")
        return body, extract_match_urls("\n".join([html_source] + captured + attrs))
    finally:
        page.remove_listener("response", capture)


async def enrich(context, game, semaphore):
    if game.get("locationType") != "home":
        game["detailStatus"] = "nicht_erforderlich"
        return
    game["detailUrl"] = plain_url(game.get("detailUrl"))
    if not game["detailUrl"]:
        game["detailStatus"] = "link_fehlt"
        return
    async with semaphore:
        page = await context.new_page()
        try:
            await page.goto(game["detailUrl"], wait_until="domcontentloaded", timeout=90000)
            await page.wait_for_timeout(7000)
            await accept_cookies(page)
            header = page.locator("body")
            body_text = await header.inner_text()
            venue, pitch, surface = parse_detail(body_text)
            game.update({
                "venueDetail": venue,
                "pitch": pitch,
                "surface": surface,
                "detailStatus": "geladen" if pitch else "platz_nicht_gefunden",
            })
        except Exception as exc:
            game["detailStatus"] = "fehler"
            game["detailError"] = clean(exc)
        finally:
            await page.close()


async def main():
    games, warnings, counts, old = [], [], {}, {}
    if OUT.exists():
        try:
            old = json.loads(OUT.read_text(encoding="utf-8"))
        except Exception:
            pass
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(locale="de-DE", user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36")
        page = await context.new_page()
        for key, cfg in CFG["teams"].items():
            try:
                text, urls = await load(page, cfg)
                found = parse_games(text, key, cfg)
                for game in found:
                    game["detailUrl"] = match_detail_url(game, urls)
                active = [g for g in found if g["status"] != "abgesetzt"]
                games.extend(active)
                counts[key] = len(active)
                home = [g for g in active if g["locationType"] == "home"]
                linked = [g for g in home if g["detailUrl"]]
                print(key, cfg["teamId"], len(active), "Detail-Links", len(linked), "/", len(home), "Kandidaten", len(urls))
                if len(linked) < len(home):
                    warnings.append(f"{key}: Detail-Link für {len(linked)} von {len(home)} Heimspielen gefunden")
            except Exception as exc:
                counts[key] = 0
                warnings.append(f"{key}: {clean(exc)}")
        sem = asyncio.Semaphore(3)
        await asyncio.gather(*(enrich(context, g, sem) for g in games))
        await page.close()
        await browser.close()

    games = sorted({g["id"]: g for g in games}.values(), key=lambda g: (g["date"], g["time"], g["teamId"]))
    oldmap = {g.get("id"): g for g in old.get("games", []) if g.get("id")}
    for game in games:
        previous = oldmap.get(game["id"])
        if previous and game.get("detailStatus") != "geladen":
            for field in ("pitch", "surface", "venueDetail", "detailUrl"):
                if not game.get(field) or game.get(field) == "unbekannt":
                    game[field] = previous.get(field, game.get(field))
            if game.get("pitch"):
                game["detailStatus"] = "altbestand_beibehalten"

    if not games and old.get("games"):
        raise SystemExit("Abruf ergab 0 Spiele; gültige JSON bleibt erhalten. " + "; ".join(warnings))

    home = [g for g in games if g["locationType"] == "home"]
    with_pitch = [g for g in home if g.get("pitch")]
    missing = [g for g in home if not g.get("pitch")]
    if missing:
        warnings.append("Keine Platzinformation für " + str(len(missing)) + " Heimspiele: " + ", ".join(f"{g['teamId']} {g['date']} {g['time']}" for g in missing[:10]))

    OUT.write_text(json.dumps({
        "schema": 5,
        "updatedAt": datetime.now(timezone.utc).isoformat(),
        "source": "FUSSBALL.DE",
        "counts": counts,
        "detailCounts": {"homeGames": len(home), "homeGamesWithPitch": len(with_pitch), "homeGamesWithoutPitch": len(missing)},
        "games": games,
        "warnings": warnings,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("Gesamt:", len(games), "Heimspiele mit Platz:", len(with_pitch), "Warnungen:", warnings)


if __name__ == "__main__":
    asyncio.run(main())
