from http.server import BaseHTTPRequestHandler
import json
import hashlib
import math
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs, quote

import feedparser
import requests

TIMEOUT      = 8
MAX_PER_SRC  = 30
MAX_AGE_SECS = 14 * 86400

RSS_HEADERS    = {'User-Agent': 'Mozilla/5.0 (compatible; WorldSignalFeed/1.0)'}
REDDIT_HEADERS = {'User-Agent': 'script:WorldSignalFeed:v1.0'}

# Root of the deployed project (one level above api/)
_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

MIME = {
    '.html': 'text/html; charset=utf-8',
    '.css':  'text/css',
    '.js':   'application/javascript',
    '.json': 'application/json',
    '.png':  'image/png',
    '.svg':  'image/svg+xml',
    '.ico':  'image/x-icon',
    '.txt':  'text/plain',
}

SOURCES = [
    # GEO-POLITICAL
    {"name": "Reuters World",    "url": "https://feeds.reuters.com/reuters/worldNews",                            "category": "GEO-POLITICAL", "authority": 10},
    {"name": "BBC World",        "url": "https://feeds.bbci.co.uk/news/world/rss.xml",                           "category": "GEO-POLITICAL", "authority": 9},
    {"name": "Al Jazeera",       "url": "https://www.aljazeera.com/xml/rss/all.xml",                             "category": "GEO-POLITICAL", "authority": 9},
    {"name": "The Wire",         "url": "https://thewire.in/feed",                                               "category": "GEO-POLITICAL", "authority": 8},
    {"name": "The Print",        "url": "https://theprint.in/feed/",                                             "category": "GEO-POLITICAL", "authority": 8},
    {"name": "Foreign Policy",   "url": "https://foreignpolicy.com/feed/",                                       "category": "GEO-POLITICAL", "authority": 9},
    {"name": "The Diplomat",     "url": "https://thediplomat.com/feed/",                                         "category": "GEO-POLITICAL", "authority": 8},
    # SPORTS
    {"name": "ESPN",             "url": "https://www.espn.com/espn/rss/news",                                    "category": "SPORTS",        "authority": 9},
    {"name": "ESPNcricinfo",     "url": "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",            "category": "SPORTS",        "authority": 10},
    {"name": "BBC Sport",        "url": "https://feeds.bbci.co.uk/sport/rss.xml",                                "category": "SPORTS",        "authority": 9},
    {"name": "NDTV Cricket",     "url": "https://sports.ndtv.com/feeds/rss/cricket-news.xml",                   "category": "SPORTS",        "authority": 8},
    {"name": "Goal.com",         "url": "https://www.goal.com/feeds/en/news",                                    "category": "SPORTS",        "authority": 9},
    # TECH
    {"name": "TechCrunch",       "url": "https://techcrunch.com/feed/",                                          "category": "TECH",          "authority": 9},
    {"name": "Ars Technica",     "url": "https://feeds.arstechnica.com/arstechnica/index",                       "category": "TECH",          "authority": 9},
    {"name": "The Verge",        "url": "https://www.theverge.com/rss/index.xml",                                "category": "TECH",          "authority": 9},
    {"name": "Wired",            "url": "https://www.wired.com/feed/rss",                                        "category": "TECH",          "authority": 9},
    {"name": "MIT Tech Review",  "url": "https://www.technologyreview.com/feed/",                                "category": "TECH",          "authority": 10},
    {"name": "VentureBeat",      "url": "https://venturebeat.com/feed/",                                         "category": "TECH",          "authority": 8},
    # FINANCE
    {"name": "Yahoo Finance",    "url": "https://finance.yahoo.com/news/rssindex",                               "category": "FINANCE",       "authority": 8},
    {"name": "Moneycontrol",     "url": "https://www.moneycontrol.com/rss/top.xml",                             "category": "FINANCE",       "authority": 9},
    {"name": "Reuters Business", "url": "https://feeds.reuters.com/reuters/businessNews",                        "category": "FINANCE",       "authority": 10},
    {"name": "MarketWatch",      "url": "https://feeds.marketwatch.com/marketwatch/topstories/",                 "category": "FINANCE",       "authority": 9},
    {"name": "ET Markets",       "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms", "category": "FINANCE",       "authority": 8},
    # SCIENCE
    {"name": "NASA",             "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss",                        "category": "SCIENCE",       "authority": 10},
    {"name": "Science Daily",    "url": "https://www.sciencedaily.com/rss/all.xml",                              "category": "SCIENCE",       "authority": 9},
    {"name": "New Scientist",    "url": "https://www.newscientist.com/feed/home/",                               "category": "SCIENCE",       "authority": 9},
    {"name": "BBC Science",      "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",         "category": "SCIENCE",       "authority": 9},
    {"name": "Phys.org",         "url": "https://phys.org/rss-feed/",                                           "category": "SCIENCE",       "authority": 9},
    # QUIZ
    {"name": "Atlas Obscura",    "url": "https://www.atlasobscura.com/feeds/latest",                             "category": "QUIZ",          "authority": 9},
    {"name": "Smithsonian",      "url": "https://www.smithsonianmag.com/rss/latest_articles/",                   "category": "QUIZ",          "authority": 9},
    {"name": "Big Think",        "url": "https://bigthink.com/feed/",                                            "category": "QUIZ",          "authority": 8},
    # OCEAN
    {"name": "NOAA",             "url": "https://www.noaa.gov/feed/",                                            "category": "OCEAN",         "authority": 10},
    {"name": "Maritime Exec",    "url": "https://maritime-executive.com/rss/",                                   "category": "OCEAN",         "authority": 9},
    # REDDIT
    {"name": "Reddit r/worldnews",       "url": "https://www.reddit.com/r/worldnews/hot.json?limit=25",       "category": "GEO-POLITICAL", "authority": 7, "type": "reddit"},
    {"name": "Reddit r/geopolitics",     "url": "https://www.reddit.com/r/geopolitics/hot.json?limit=25",    "category": "GEO-POLITICAL", "authority": 7, "type": "reddit"},
    {"name": "Reddit r/india",           "url": "https://www.reddit.com/r/india/hot.json?limit=25",          "category": "GEO-POLITICAL", "authority": 6, "type": "reddit"},
    {"name": "Reddit r/Cricket",         "url": "https://www.reddit.com/r/Cricket/hot.json?limit=25",        "category": "SPORTS",        "authority": 7, "type": "reddit"},
    {"name": "Reddit r/soccer",          "url": "https://www.reddit.com/r/soccer/hot.json?limit=25",         "category": "SPORTS",        "authority": 7, "type": "reddit"},
    {"name": "Reddit r/technology",      "url": "https://www.reddit.com/r/technology/hot.json?limit=25",     "category": "TECH",          "authority": 7, "type": "reddit"},
    {"name": "Reddit r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/hot.json?limit=25","category": "TECH",          "authority": 8, "type": "reddit"},
    {"name": "Reddit r/science",         "url": "https://www.reddit.com/r/science/hot.json?limit=25",        "category": "SCIENCE",       "authority": 7, "type": "reddit"},
    {"name": "Reddit r/investing",       "url": "https://www.reddit.com/r/investing/hot.json?limit=25",      "category": "FINANCE",       "authority": 6, "type": "reddit"},
    {"name": "Reddit r/movies",          "url": "https://www.reddit.com/r/movies/hot.json?limit=25",         "category": "ENTERTAINMENT", "authority": 6, "type": "reddit"},
    {"name": "Reddit r/todayilearned",   "url": "https://www.reddit.com/r/todayilearned/hot.json?limit=25",  "category": "QUIZ",          "authority": 7, "type": "reddit"},
]


# ── Helpers ────────────────────────────────────────────────────────────────────

def make_id(url: str) -> str:
    return hashlib.md5(url.encode()).hexdigest()[:12]


def parse_pub(entry) -> datetime:
    try:
        if getattr(entry, 'published_parsed', None):
            return datetime.fromtimestamp(time.mktime(entry.published_parsed))
        if getattr(entry, 'updated_parsed', None):
            return datetime.fromtimestamp(time.mktime(entry.updated_parsed))
    except Exception:
        pass
    return datetime.now()


def compute_score(authority: int, pub_ts: float, now_ts: float) -> float:
    age_hours = (now_ts - pub_ts) / 3600
    if age_hours > 144:
        return 0.0
    return (authority / 10.0) * 0.6 + max(0.0, 1.0 - age_hours / 144) * 0.4


# ── Fetchers ───────────────────────────────────────────────────────────────────

def fetch_rss(source: dict) -> list:
    try:
        r    = requests.get(source['url'], timeout=TIMEOUT, headers=RSS_HEADERS)
        feed = feedparser.parse(r.content)
        now  = time.time()
        out  = []
        for entry in feed.entries[:MAX_PER_SRC]:
            title = (entry.get('title') or '').strip()
            url   = (entry.get('link')  or '').strip()
            if not title or not url or len(title) < 10:
                continue
            for sfx in ('...', '…'):
                if title.endswith(sfx):
                    title = title[:-len(sfx)].rstrip()
            pub = parse_pub(entry)
            if (now - pub.timestamp()) > MAX_AGE_SECS:
                continue
            desc = (entry.get('summary') or entry.get('description') or '').strip()
            if len(desc) > 300:
                desc = desc[:300].rsplit(' ', 1)[0] + '…'
            out.append({
                'id': make_id(url), 'title': title, 'url': url,
                'source': source['name'], 'category': source.get('category', 'WORLD'),
                'authority': source.get('authority', 5),
                'published': pub.isoformat(), 'published_ts': pub.timestamp(),
                'cross_source_count': 1,
                'description': desc,
                'score': compute_score(source.get('authority', 5), pub.timestamp(), now),
            })
        return out
    except Exception:
        return []


def fetch_reddit(source: dict) -> list:
    try:
        r     = requests.get(source['url'], timeout=TIMEOUT, headers=REDDIT_HEADERS)
        posts = r.json()['data']['children']
        now   = time.time()
        out   = []
        for post in posts[:MAX_PER_SRC]:
            p     = post.get('data', {})
            title = p.get('title', '').strip()
            if not title or len(title) < 10:
                continue
            url = (f"https://www.reddit.com{p.get('permalink', '')}"
                   if p.get('is_self', True) else p.get('url', '').strip())
            if not url:
                continue
            upvotes   = max(p.get('score', 0), 0)
            authority = min(10, max(1, int(math.log10(max(upvotes, 2)) * 2.5)))
            pub_ts    = float(p.get('created_utc', now))
            if (now - pub_ts) > MAX_AGE_SECS:
                continue
            out.append({
                'id': make_id(url), 'title': title, 'url': url,
                'source': source['name'], 'category': source.get('category', 'GEO-POLITICAL'),
                'authority': authority,
                'published': datetime.fromtimestamp(pub_ts).isoformat(),
                'published_ts': pub_ts,
                'cross_source_count': min(5, max(1, p.get('num_comments', 0) // 200 + 1)),
                'description': p.get('selftext', '')[:300] or '',
                'score': compute_score(authority, pub_ts, now),
            })
        return out
    except Exception:
        return []


_cache: dict = {'ts': 0.0, 'data': []}
CACHE_TTL = 60  # seconds — re-fetch RSS at most once per minute

def fetch_all_cached() -> list:
    now = time.time()
    if _cache['data'] and (now - _cache['ts']) < CACHE_TTL:
        return _cache['data']
    data = fetch_all()
    _cache['ts'] = now
    _cache['data'] = data
    return data

def fetch_all() -> list:
    seen, out = set(), []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fetch_reddit if s.get('type') == 'reddit' else fetch_rss, s): s
                for s in SOURCES}
        for fut in as_completed(futs, timeout=25):
            try:
                for h in fut.result():
                    if h['id'] not in seen:
                        seen.add(h['id'])
                        out.append(h)
            except Exception:
                pass
    out.sort(key=lambda h: h['published_ts'], reverse=True)
    return out


def search_news(q: str) -> list:
    try:
        url  = f'https://news.google.com/rss/search?q={quote(q)}&hl=en-IN&gl=IN&ceid=IN:en'
        r    = requests.get(url, timeout=TIMEOUT, headers=RSS_HEADERS)
        feed = feedparser.parse(r.content)
        now  = time.time()
        out  = []
        for entry in feed.entries[:20]:
            title = (entry.get('title') or '').strip()
            link  = (entry.get('link')  or '').strip()
            if not title or not link:
                continue
            for sfx in ('...', '…'):
                if title.endswith(sfx):
                    title = title[:-len(sfx)].rstrip()
            pub = parse_pub(entry)
            out.append({
                'id': make_id(link), 'title': title, 'url': link,
                'source': 'Google News', 'category': 'GEO-POLITICAL',
                'authority': 7,
                'published': pub.isoformat(), 'published_ts': pub.timestamp(),
                'cross_source_count': 1,
                'score': compute_score(7, pub.timestamp(), now),
            })
        return out
    except Exception:
        return []


# ── Static file helper ─────────────────────────────────────────────────────────

def serve_file(h, rel_path: str):
    path = os.path.join(_ROOT, rel_path.lstrip('/'))
    if not os.path.isfile(path):
        path = os.path.join(_ROOT, 'index.html')   # SPA fallback
    ext      = os.path.splitext(path)[1].lower()
    mime     = MIME.get(ext, 'application/octet-stream')
    basename = os.path.basename(path)
    # Never cache sw.js or index.html so updates are picked up immediately
    no_cache = basename in ('sw.js', 'index.html')
    try:
        with open(path, 'rb') as f:
            body = f.read()
        h.send_response(200)
        h.send_header('Content-Type',   mime)
        h.send_header('Content-Length', str(len(body)))
        if no_cache:
            h.send_header('Cache-Control', 'no-store')
        else:
            h.send_header('Cache-Control', 'public, max-age=3600')
        h.end_headers()
        h.wfile.write(body)
    except Exception:
        h.send_response(404)
        h.end_headers()


# ── Vercel handler ─────────────────────────────────────────────────────────────

class handler(BaseHTTPRequestHandler):
    def do_OPTIONS(self):
        self.send_response(200)
        self._cors()
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        p      = parsed.path.rstrip('/')

        if p == '/api/headlines':
            q    = (parse_qs(parsed.query).get('q') or [None])[0]
            data = search_news(q) if q else fetch_all_cached()
            body = json.dumps(data, default=str).encode()
            self.send_response(200)
            self.send_header('Content-Type',   'application/json')
            self.send_header('Content-Length', str(len(body)))
            self._cors()
            self.end_headers()
            self.wfile.write(body)
        else:
            serve_file(self, parsed.path if parsed.path != '/' else '/index.html')

    def _cors(self):
        self.send_header('Access-Control-Allow-Origin',  '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')

    def log_message(self, *args):
        pass
