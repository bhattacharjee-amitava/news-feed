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

TIMEOUT      = 5
MAX_PER_SRC  = 20
MAX_AGE_SECS = 7 * 86400

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
    # ALWAYS FRESH — Google News aggregates minutes-old headlines
    {"name": "Google News",      "url": "https://news.google.com/rss?hl=en-IN&gl=IN&ceid=IN:en",                 "category": "GEO-POLITICAL", "authority": 10},
    {"name": "Google News World","url": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en&gl=IN", "category": "GEO-POLITICAL", "authority": 10},
    {"name": "Google News Tech", "url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en",  "category": "TECH",          "authority": 10},
    {"name": "Google News Biz",  "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en",   "category": "FINANCE",       "authority": 10},
    {"name": "Google News Sports","url": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en",    "category": "SPORTS",        "authority": 10},
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
    # EXPLORE (was QUIZ)
    {"name": "Atlas Obscura",    "url": "https://www.atlasobscura.com/feeds/latest",                             "category": "EXPLORE",       "authority": 9},
    {"name": "Smithsonian",      "url": "https://www.smithsonianmag.com/rss/latest_articles/",                   "category": "EXPLORE",       "authority": 9},
    {"name": "Big Think",        "url": "https://bigthink.com/feed/",                                            "category": "EXPLORE",       "authority": 8},
    # NATURE (was OCEAN)
    {"name": "NOAA",             "url": "https://www.noaa.gov/feed/",                                            "category": "NATURE",        "authority": 10},
    {"name": "Maritime Exec",    "url": "https://maritime-executive.com/rss/",                                   "category": "NATURE",        "authority": 9},
    # HEALTH
    {"name": "WHO",              "url": "https://www.who.int/rss-feeds/news-english.xml",                        "category": "HEALTH",        "authority": 10},
    {"name": "Medical News Today","url":"https://www.medicalnewstoday.com/rss/news",                             "category": "HEALTH",        "authority": 9},
    {"name": "Healthline",       "url": "https://www.healthline.com/rss/news",                                   "category": "HEALTH",        "authority": 8},
    # POLITICS
    {"name": "Politico",         "url": "https://www.politico.com/rss/politics08.xml",                          "category": "POLITICS",      "authority": 9},
    {"name": "The Hill",         "url": "https://thehill.com/rss/syndicator/19110",                             "category": "POLITICS",      "authority": 8},
    {"name": "The Atlantic",     "url": "https://www.theatlantic.com/feed/all/",                                 "category": "POLITICS",      "authority": 9},
    # INDIA
    {"name": "Times of India",   "url": "https://timesofindia.indiatimes.com/rssfeedstopstories.cms",           "category": "INDIA",         "authority": 9},
    {"name": "The Hindu",        "url": "https://www.thehindu.com/feeder/default.rss",                          "category": "INDIA",         "authority": 9},
    {"name": "Indian Express",   "url": "https://indianexpress.com/feed/",                                      "category": "INDIA",         "authority": 9},
    {"name": "NDTV",             "url": "https://feeds.feedburner.com/ndtvnews-top-stories",                    "category": "INDIA",         "authority": 8},
    {"name": "Hindustan Times",  "url": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",      "category": "INDIA",         "authority": 8},
    # FASHION
    {"name": "Vogue",            "url": "https://www.vogue.com/feed/rss",                                       "category": "FASHION",       "authority": 10},
    {"name": "Harper's Bazaar",  "url": "https://www.harpersbazaar.com/rss/all.xml",                            "category": "FASHION",       "authority": 9},
    {"name": "Elle",             "url": "https://www.elle.com/rss/all.xml",                                     "category": "FASHION",       "authority": 9},
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


# ── Keyword-based category classifier ─────────────────────────────────────────

import re as _re

# Niche categories: fall back to GEO-POLITICAL if no keyword matches.
# Core categories: fall back to source category if no keyword matches.
_NICHE = {'FASHION', 'ENTERTAINMENT', 'EXPLORE', 'NATURE'}

_KW: list[tuple[str, list[str]]] = [
    ('SPORTS',        ['cricket', 'football', 'soccer', 'tennis', 'golf', 'basketball', 'hockey',
                       'rugby', 'olympic', 'olympics', 'ipl', 'fifa', 'wimbledon', 'formula 1',
                       'grand prix', 'tournament', 'championship', 'batsman', 'bowler', 'wicket',
                       'semifinal', 'medal', 'athlete', 'stadium', 'squad', 'innings', 'odi',
                       't20', 'test match', 'world cup', 'jersey', 'referee', 'wicketkeeper',
                       'century', 'hat-trick', 'penalty', 'offside', 'dribble', 'slam dunk',
                       'serve', 'deuce', 'putt', 'birdie', 'bogey', 'touchdowns', 'inning']),
    ('TECH',          ['artificial intelligence', 'chatgpt', 'openai', 'gemini', 'llm',
                       'machine learning', 'robot', 'robotics', 'semiconductor', 'gpu',
                       'nvidia', 'iphone', 'android', 'cybersecurity', 'data breach',
                       'algorithm', 'quantum computing', 'biotech', 'drone', 'smartphone',
                       'silicon valley', 'deep learning', 'neural network', 'tech layoffs',
                       'software engineer', 'cloud computing', 'generative ai', 'microsoft',
                       'apple inc', 'google deepmind', 'anthropic', 'startup funding']),
    ('FINANCE',       ['stock market', 'share price', 'gdp', 'inflation', 'recession',
                       'interest rate', 'central bank', 'rbi', 'federal reserve',
                       'budget deficit', 'earnings report', 'ipo', 'nifty', 'sensex',
                       'nasdaq', 'dow jones', 'crypto', 'bitcoin', 'trade deficit',
                       'tariff', 'merger', 'acquisition', 'quarterly results', 'revenue growth',
                       'net profit', 'market cap', 'hedge fund', 'venture capital',
                       'private equity', 'bond yield', 'forex', 'commodity prices']),
    ('HEALTH',        ['virus', 'vaccine', 'covid', 'cancer', 'disease outbreak', 'epidemic',
                       'pandemic', 'surgery', 'clinical trial', 'mental health', 'obesity',
                       'diabetes', 'heart disease', 'stroke', 'cdc', 'fda', 'medical research',
                       'doctor', 'hospital', 'patient', 'drug approval', 'antibiotic',
                       'nutrition', 'public health', 'health ministry', 'blood pressure',
                       'chemotherapy', 'organ transplant', 'parasite', 'pathogen']),
    ('SCIENCE',       ['nasa', 'space mission', 'planet', 'asteroid', 'comet', 'galaxy',
                       'telescope', 'black hole', 'global warming', 'fossil', 'dinosaur',
                       'genome', 'physics', 'chemistry', 'biologist', 'scientific',
                       'experiment', 'carbon emission', 'renewable energy', 'nuclear fusion',
                       'particle physics', 'evolution', 'spacex', 'rocket launch',
                       'international space station', 'dark matter', 'exoplanet']),
    ('NATURE',        ['ocean', 'marine', 'wildlife', 'coral reef', 'extinction',
                       'biodiversity', 'deforestation', 'conservation', 'national park',
                       'ecosystem', 'flood warning', 'earthquake', 'cyclone', 'hurricane',
                       'wildfire', 'drought', 'endangered species', 'poaching', 'reforestation',
                       'sea level', 'glacier', 'rainforest', 'migratory bird']),
    ('ENTERTAINMENT', ['film festival', 'box office', 'netflix', 'disney', 'amazon prime',
                       'hbo', 'streaming', 'grammy', 'oscar', 'bafta', 'emmy', 'bollywood',
                       'hollywood', 'music album', 'concert tour', 'celebrity', 'box office',
                       'film review', 'movie release', 'tv series', 'season finale',
                       'music video', 'stand-up', 'sitcom', 'blockbuster', 'trailer']),
    ('FASHION',       ['fashion week', 'runway', 'couture', 'fashion designer', 'vogue',
                       'clothing brand', 'fashion show', 'fashion trend', 'luxury fashion',
                       'gucci', 'prada', 'louis vuitton', 'chanel', 'dior',
                       'sustainable fashion', 'streetwear', 'fashion industry']),
    ('INDIA',         ['india', 'delhi', 'mumbai', 'bengal', 'kolkata', 'gujarat', 'rajasthan',
                       'kashmir', 'punjab', 'bihar', 'odisha', 'kerala', 'tamil nadu', 'andhra',
                       'telangana', 'assam', 'narendra modi', 'bjp', 'aap', 'tmc',
                       'lok sabha', 'rajya sabha', 'bcci', 'supreme court of india',
                       'indian army', 'indian economy', 'indian railway']),
    ('POLITICS',      ['election', 'president', 'prime minister', 'senate', 'parliament',
                       'democrat', 'republican', 'trump', 'biden', 'ballot', 'campaign',
                       'cabinet minister', 'diplomat', 'sanctions', 'nato', 'united nations',
                       'g7', 'g20', 'ceasefire', 'coup', 'referendum', 'legislation',
                       'foreign policy', 'geopolitics', 'political party', 'civil war']),
    ('EXPLORE',       ['ancient civilization', 'archaeology', 'mythology', 'philosophy',
                       'unexplained', 'hidden history', 'lost city', 'fascinating fact',
                       'did you know', 'trivia', 'cultural heritage', 'anthropology',
                       'linguistic', 'folk tradition', 'exploration', 'adventurer']),
]

def classify_category(title: str, source_category: str) -> str:
    """Classify by whole-word keyword match; niche categories fall back to GEO-POLITICAL."""
    t = title.lower()
    for cat, keywords in _KW:
        for kw in keywords:
            # Use word-boundary matching to avoid substring false positives
            if _re.search(r'\b' + _re.escape(kw) + r'\b', t):
                return cat
    # No keyword matched: niche sources default to world, core sources keep their category
    return 'GEO-POLITICAL' if source_category in _NICHE else source_category


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
            src_cat = source.get('category', 'GEO-POLITICAL')
            out.append({
                'id': make_id(url), 'title': title, 'url': url,
                'source': source['name'], 'category': classify_category(title, src_cat),
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
            src_cat = source.get('category', 'GEO-POLITICAL')
            out.append({
                'id': make_id(url), 'title': title, 'url': url,
                'source': source['name'], 'category': classify_category(title, src_cat),
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


BN_SOURCES = [
    {"name": "BBC Bangla",       "url": "https://feeds.bbci.co.uk/bengali/rss.xml",                         "category": "GEO-POLITICAL", "authority": 10},
    {"name": "Prothom Alo",      "url": "https://www.prothomalo.com/feed/",                                  "category": "GEO-POLITICAL", "authority": 9},
    {"name": "Anandabazar",      "url": "https://www.anandabazar.com/rss/",                                  "category": "GEO-POLITICAL", "authority": 9},
    {"name": "Sangbad Pratidin", "url": "https://www.sangbadpratidin.in/feed/",                              "category": "GEO-POLITICAL", "authority": 8},
    {"name": "Ei Samay",         "url": "https://eisamay.com/feeds/",                                       "category": "GEO-POLITICAL", "authority": 8},
    {"name": "ABP Ananda",       "url": "https://bengali.abplive.com/feeds",                                 "category": "GEO-POLITICAL", "authority": 8},
    {"name": "News18 Bangla",    "url": "https://bengali.news18.com/commonfeeds/v1/bng/rss/news18-bengali.xml","category": "GEO-POLITICAL","authority": 8},
    {"name": "Zee 24 Ghanta",    "url": "https://zeenews.india.com/bengali/rss/all-news.xml",               "category": "GEO-POLITICAL", "authority": 8},
    {"name": "Jugantor",         "url": "https://www.jugantor.com/feed/rss.xml",                            "category": "GEO-POLITICAL", "authority": 8},
    {"name": "Daily Ittefaq",    "url": "https://www.ittefaq.com.bd/feed",                                  "category": "GEO-POLITICAL", "authority": 8},
    {"name": "Dainik Statesman", "url": "https://www.dainikstatesman.com/feed/",                            "category": "GEO-POLITICAL", "authority": 7},
    {"name": "Kaler Kantho",     "url": "https://www.kalerkantho.com/rss.xml",                              "category": "GEO-POLITICAL", "authority": 8},
]

_cache: dict = {'en': {'ts': 0.0, 'data': []}, 'bn': {'ts': 0.0, 'data': []}}
CACHE_TTL = 60

def fetch_all_cached(lang: str = 'en') -> list:
    now = time.time()
    c = _cache[lang]
    if c['data'] and (now - c['ts']) < CACHE_TTL:
        return c['data']
    sources = BN_SOURCES if lang == 'bn' else SOURCES
    data = fetch_all(sources)
    c['ts'] = now
    c['data'] = data
    return data

def fetch_all(sources=None) -> list:
    if sources is None:
        sources = SOURCES
    seen, out = set(), []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fetch_reddit if s.get('type') == 'reddit' else fetch_rss, s): s
                for s in sources}
        for fut in as_completed(futs, timeout=8):
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
        h.send_header('Cache-Control', 'no-store')
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
            qs   = parse_qs(parsed.query)
            q    = (qs.get('q') or [None])[0]
            lang = (qs.get('lang') or ['en'])[0]
            data = search_news(q) if q else fetch_all_cached(lang)
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
