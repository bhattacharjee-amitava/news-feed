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
import re as _re

def _strip_html(text: str) -> str:
    return _re.sub(r'<[^>]+>', '', text).replace('&nbsp;', ' ').replace('&amp;', '&').strip()

def _extract_image(entry) -> str:
    for attr in ('media_content', 'media_thumbnail'):
        for item in (getattr(entry, attr, None) or []):
            url = item.get('url', '')
            if url and url.startswith('http'):
                return url
    for enc in (getattr(entry, 'enclosures', None) or []):
        url = enc.get('url', '')
        if url and enc.get('type', '').startswith('image/'):
            return url
    for link in (getattr(entry, 'links', None) or []):
        if link.get('type', '').startswith('image/'):
            url = link.get('href', '')
            if url:
                return url
    return ''

TIMEOUT      = 5
BN_TIMEOUT   = 8
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
    # ── Google News — section feeds (already category-specific) ──────────────
    {"name": "Google News World",  "url": "https://news.google.com/rss/headlines/section/topic/WORLD?hl=en&gl=IN",       "category": "GEO-POLITICAL", "authority": 10},
    {"name": "Google News Tech",   "url": "https://news.google.com/rss/headlines/section/topic/TECHNOLOGY?hl=en",        "category": "TECH",          "authority": 10},
    {"name": "Google News Biz",    "url": "https://news.google.com/rss/headlines/section/topic/BUSINESS?hl=en",          "category": "FINANCE",       "authority": 10},
    {"name": "Google News Sports", "url": "https://news.google.com/rss/headlines/section/topic/SPORTS?hl=en",            "category": "SPORTS",        "authority": 10},
    {"name": "Google News Health", "url": "https://news.google.com/rss/headlines/section/topic/HEALTH?hl=en",            "category": "HEALTH",        "authority": 10},
    {"name": "Google News Science","url": "https://news.google.com/rss/headlines/section/topic/SCIENCE?hl=en",           "category": "SCIENCE",       "authority": 10},
    {"name": "Google News India",  "url": "https://news.google.com/rss/headlines/section/geo/IN?hl=en-IN&gl=IN&ceid=IN:en","category": "INDIA",      "authority": 10},
    # ── BBC — section feeds ───────────────────────────────────────────────────
    {"name": "BBC World",          "url": "https://feeds.bbci.co.uk/news/world/rss.xml",                                "category": "GEO-POLITICAL", "authority": 9},
    {"name": "BBC Sport",          "url": "https://feeds.bbci.co.uk/sport/rss.xml",                                     "category": "SPORTS",        "authority": 9},
    {"name": "BBC Science",        "url": "https://feeds.bbci.co.uk/news/science_and_environment/rss.xml",              "category": "SCIENCE",       "authority": 9},
    {"name": "BBC Health",         "url": "https://feeds.bbci.co.uk/news/health/rss.xml",                               "category": "HEALTH",        "authority": 9},
    {"name": "BBC Business",       "url": "https://feeds.bbci.co.uk/news/business/rss.xml",                             "category": "FINANCE",       "authority": 9},
    {"name": "BBC Entertainment",  "url": "https://feeds.bbci.co.uk/news/entertainment_and_arts/rss.xml",               "category": "ENTERTAINMENT", "authority": 9},
    {"name": "BBC Tech",           "url": "https://feeds.bbci.co.uk/news/technology/rss.xml",                           "category": "TECH",          "authority": 9},
    # ── Other world sources ───────────────────────────────────────────────────
    {"name": "Al Jazeera",         "url": "https://www.aljazeera.com/xml/rss/all.xml",                                  "category": "GEO-POLITICAL", "authority": 9},
    {"name": "Foreign Policy",     "url": "https://foreignpolicy.com/feed/",                                            "category": "GEO-POLITICAL", "authority": 9},
    {"name": "The Diplomat",       "url": "https://thediplomat.com/feed/",                                              "category": "GEO-POLITICAL", "authority": 8},
    # ── Sports — dedicated sources ────────────────────────────────────────────
    {"name": "ESPN",               "url": "https://www.espn.com/espn/rss/news",                                         "category": "SPORTS",        "authority": 9},
    {"name": "ESPNcricinfo",       "url": "https://www.espncricinfo.com/rss/content/story/feeds/0.xml",                 "category": "SPORTS",        "authority": 10},
    # ── Tech — dedicated sources ──────────────────────────────────────────────
    {"name": "TechCrunch",         "url": "https://techcrunch.com/feed/",                                               "category": "TECH",          "authority": 9},
    {"name": "Ars Technica",       "url": "https://feeds.arstechnica.com/arstechnica/index",                            "category": "TECH",          "authority": 9},
    {"name": "MIT Tech Review",    "url": "https://www.technologyreview.com/feed/",                                     "category": "TECH",          "authority": 10},
    # ── Finance — dedicated sources ───────────────────────────────────────────
    {"name": "MarketWatch",        "url": "https://feeds.marketwatch.com/marketwatch/topstories/",                      "category": "FINANCE",       "authority": 9},
    {"name": "ET Markets",         "url": "https://economictimes.indiatimes.com/markets/rssfeeds/1977021501.cms",       "category": "FINANCE",       "authority": 8},
    # ── Science — dedicated sources ───────────────────────────────────────────
    {"name": "NASA",               "url": "https://www.nasa.gov/rss/dyn/breaking_news.rss",                             "category": "SCIENCE",       "authority": 10},
    {"name": "Science Daily",      "url": "https://www.sciencedaily.com/rss/all.xml",                                   "category": "SCIENCE",       "authority": 9},
    {"name": "Phys.org",           "url": "https://phys.org/rss-feed/",                                                "category": "SCIENCE",       "authority": 9},
    # ── Health — dedicated sources ────────────────────────────────────────────
    {"name": "WHO",                "url": "https://www.who.int/rss-feeds/news-english.xml",                             "category": "HEALTH",        "authority": 10},
    # ── Explore — dedicated sources ───────────────────────────────────────────
    {"name": "Atlas Obscura",      "url": "https://www.atlasobscura.com/feeds/latest",                                  "category": "EXPLORE",       "authority": 9},
    {"name": "Smithsonian",        "url": "https://www.smithsonianmag.com/rss/latest_articles/",                        "category": "EXPLORE",       "authority": 9},
    {"name": "Big Think",          "url": "https://bigthink.com/feed/",                                                 "category": "EXPLORE",       "authority": 8},
    # ── Politics — dedicated sources ──────────────────────────────────────────
    {"name": "The Hill",           "url": "https://thehill.com/rss/syndicator/19110",                                   "category": "POLITICS",      "authority": 8},
    # ── Fashion — dedicated sources ───────────────────────────────────────────
    {"name": "Vogue",              "url": "https://www.vogue.com/feed/rss",                                             "category": "FASHION",       "authority": 10},
    {"name": "Harper's Bazaar",    "url": "https://www.harpersbazaar.com/rss/all.xml",                                  "category": "FASHION",       "authority": 9},
    {"name": "Elle",               "url": "https://www.elle.com/rss/all.xml",                                          "category": "FASHION",       "authority": 9},
    # ── Times of India — section feeds ───────────────────────────────────────
    {"name": "TOI India",          "url": "https://timesofindia.indiatimes.com/rssfeeds/296589292.cms",                 "category": "INDIA",         "authority": 9},
    {"name": "TOI Sports",         "url": "https://timesofindia.indiatimes.com/rssfeeds/4719162.cms",                   "category": "SPORTS",        "authority": 8},
    {"name": "TOI Tech",           "url": "https://timesofindia.indiatimes.com/rssfeeds/66949542.cms",                  "category": "TECH",          "authority": 8},
    {"name": "TOI Business",       "url": "https://timesofindia.indiatimes.com/rssfeeds/1898055.cms",                   "category": "FINANCE",       "authority": 8},
    {"name": "TOI Entertainment",  "url": "https://timesofindia.indiatimes.com/rssfeeds/1081479906.cms",                "category": "ENTERTAINMENT", "authority": 8},
    {"name": "TOI Health",         "url": "https://timesofindia.indiatimes.com/rssfeeds/3908081.cms",                   "category": "HEALTH",        "authority": 8},
    # ── The Hindu — section feeds ─────────────────────────────────────────────
    {"name": "Hindu India",        "url": "https://www.thehindu.com/news/national/feeder/default.rss",                  "category": "INDIA",         "authority": 9},
    {"name": "Hindu Sports",       "url": "https://www.thehindu.com/sport/feeder/default.rss",                          "category": "SPORTS",        "authority": 9},
    {"name": "Hindu SciTech",      "url": "https://www.thehindu.com/sci-tech/feeder/default.rss",                       "category": "TECH",          "authority": 9},
    {"name": "Hindu Business",     "url": "https://www.thehindu.com/business/feeder/default.rss",                       "category": "FINANCE",       "authority": 9},
    {"name": "Hindu Health",       "url": "https://www.thehindu.com/sci-tech/health/feeder/default.rss",                "category": "HEALTH",        "authority": 9},
    {"name": "Hindu Entertainment","url": "https://www.thehindu.com/entertainment/feeder/default.rss",                  "category": "ENTERTAINMENT", "authority": 9},
    # ── Indian Express — section feeds ───────────────────────────────────────
    {"name": "IE India",           "url": "https://indianexpress.com/section/india/feed/",                              "category": "INDIA",         "authority": 9},
    {"name": "IE Sports",          "url": "https://indianexpress.com/section/sports/feed/",                             "category": "SPORTS",        "authority": 9},
    {"name": "IE Tech",            "url": "https://indianexpress.com/section/technology/feed/",                         "category": "TECH",          "authority": 9},
    {"name": "IE Business",        "url": "https://indianexpress.com/section/business/feed/",                           "category": "FINANCE",       "authority": 9},
    {"name": "IE Entertainment",   "url": "https://indianexpress.com/section/entertainment/feed/",                      "category": "ENTERTAINMENT", "authority": 9},
    {"name": "IE Health",          "url": "https://indianexpress.com/section/lifestyle/health/feed/",                   "category": "HEALTH",        "authority": 9},
    # ── NDTV — section feeds ─────────────────────────────────────────────────
    {"name": "NDTV India",         "url": "https://feeds.feedburner.com/ndtvnews-india-news",                           "category": "INDIA",         "authority": 8},
    {"name": "NDTV Business",      "url": "https://feeds.feedburner.com/ndtvprofit-latest",                             "category": "FINANCE",       "authority": 8},
    {"name": "NDTV Entertainment", "url": "https://feeds.feedburner.com/ndtvmovies-latest",                             "category": "ENTERTAINMENT", "authority": 8},
    # ── Hindustan Times — section feeds ──────────────────────────────────────
    {"name": "HT India",          "url": "https://www.hindustantimes.com/feeds/rss/india-news/rssfeed.xml",           "category": "INDIA",         "authority": 8},
    {"name": "HT Sports",         "url": "https://www.hindustantimes.com/feeds/rss/sports/rssfeed.xml",               "category": "SPORTS",        "authority": 8},
    {"name": "HT Tech",           "url": "https://www.hindustantimes.com/feeds/rss/technology/rssfeed.xml",           "category": "TECH",          "authority": 8},
    {"name": "HT Entertainment",  "url": "https://www.hindustantimes.com/feeds/rss/entertainment/rssfeed.xml",        "category": "ENTERTAINMENT", "authority": 8},
    # ── Reddit — category-specific subreddits ────────────────────────────────
    {"name": "Reddit r/worldnews",       "url": "https://www.reddit.com/r/worldnews/hot.json?limit=25",        "category": "GEO-POLITICAL", "authority": 7, "type": "reddit"},
    {"name": "Reddit r/geopolitics",     "url": "https://www.reddit.com/r/geopolitics/hot.json?limit=25",     "category": "GEO-POLITICAL", "authority": 7, "type": "reddit"},
    {"name": "Reddit r/india",           "url": "https://www.reddit.com/r/india/hot.json?limit=25",           "category": "INDIA",         "authority": 6, "type": "reddit"},
    {"name": "Reddit r/Cricket",         "url": "https://www.reddit.com/r/Cricket/hot.json?limit=25",         "category": "SPORTS",        "authority": 7, "type": "reddit"},
    {"name": "Reddit r/soccer",          "url": "https://www.reddit.com/r/soccer/hot.json?limit=25",          "category": "SPORTS",        "authority": 7, "type": "reddit"},
    {"name": "Reddit r/technology",      "url": "https://www.reddit.com/r/technology/hot.json?limit=25",      "category": "TECH",          "authority": 7, "type": "reddit"},
    {"name": "Reddit r/MachineLearning", "url": "https://www.reddit.com/r/MachineLearning/hot.json?limit=25", "category": "TECH",          "authority": 8, "type": "reddit"},
    {"name": "Reddit r/science",         "url": "https://www.reddit.com/r/science/hot.json?limit=25",         "category": "SCIENCE",       "authority": 7, "type": "reddit"},
    {"name": "Reddit r/investing",       "url": "https://www.reddit.com/r/investing/hot.json?limit=25",       "category": "FINANCE",       "authority": 6, "type": "reddit"},
    {"name": "Reddit r/movies",          "url": "https://www.reddit.com/r/movies/hot.json?limit=25",          "category": "ENTERTAINMENT", "authority": 6, "type": "reddit"},
    {"name": "Reddit r/todayilearned",   "url": "https://www.reddit.com/r/todayilearned/hot.json?limit=25",   "category": "EXPLORE",       "authority": 7, "type": "reddit"},
]


# ── Category classifier ────────────────────────────────────────────────────────
# Follows the guide exactly:
#   Step 1 — categoriesFromSource: map RSS <category> tags → internal category
#   Step 2 — keyword scoring: score title+desc, pick highest if threshold met
#   Step 3 — source category: definitive for sectional feeds; GEO-POLITICAL otherwise

# Map RSS <category> / <tag> terms → internal categories (lowercase keys)
_RSS_CAT_MAP = {
    'technology': 'TECH',         'tech': 'TECH',          'science & technology': 'TECH',
    'gadgets': 'TECH',            'computing': 'TECH',      'internet': 'TECH',
    'business': 'FINANCE',        'finance': 'FINANCE',     'economy': 'FINANCE',
    'markets': 'FINANCE',         'investing': 'FINANCE',   'money': 'FINANCE',
    'sports': 'SPORTS',           'sport': 'SPORTS',        'cricket': 'SPORTS',
    'football': 'SPORTS',         'soccer': 'SPORTS',       'tennis': 'SPORTS',
    'health': 'HEALTH',           'medicine': 'HEALTH',     'wellness': 'HEALTH',
    'medical': 'HEALTH',
    'science': 'SCIENCE',         'space': 'SCIENCE',       'environment': 'SCIENCE',
    'climate': 'SCIENCE',         'sci-tech': 'TECH',
    'entertainment': 'ENTERTAINMENT', 'arts': 'ENTERTAINMENT', 'movies': 'ENTERTAINMENT',
    'music': 'ENTERTAINMENT',     'television': 'ENTERTAINMENT', 'film': 'ENTERTAINMENT',
    'fashion': 'FASHION',         'style': 'FASHION',       'beauty': 'FASHION',
    'politics': 'POLITICS',       'government': 'POLITICS', 'world politics': 'POLITICS',
    'india': 'INDIA',             'nation': 'INDIA',        'national': 'INDIA',
    'nature': 'NATURE',           'wildlife': 'NATURE',     'ocean': 'NATURE',
    'world': 'GEO-POLITICAL',     'international': 'GEO-POLITICAL', 'global': 'GEO-POLITICAL',
    'travel': 'EXPLORE',          'history': 'EXPLORE',     'culture': 'EXPLORE',
}

# Keyword sets per category — substring matched, scored
_KW: dict[str, list[str]] = {
    'SPORTS': [
        'cricket', 'football', 'soccer', 'tennis', 'golf', 'basketball', 'hockey',
        'rugby', 'olympic', 'ipl', 'fifa', 'wimbledon', 'formula 1', 'grand prix',
        'batsman', 'bowler', 'wicket', 'innings', 'odi', 't20', 'test match',
        'hat-trick', 'penalty shootout', 'premier league', 'la liga', 'bundesliga',
        'transfer window', 'nba', 'nfl', 'mlb', 'nhl', 'ufc', 'badminton',
        'world cup cricket', 'match report', 'test series', 'series win',
    ],
    'TECH': [
        'artificial intelligence', 'machine learning', 'chatgpt', 'openai', 'gemini',
        'claude ai', 'llm', 'large language model', 'robotics', 'semiconductor',
        'gpu', 'nvidia', 'cybersecurity', 'data breach', 'ransomware',
        'quantum computing', 'silicon valley', 'deep learning', 'neural network',
        'cloud computing', 'generative ai', 'microsoft azure', 'google deepmind',
        'anthropic', 'startup funding', 'saas', 'open source software',
        'autonomous vehicle', 'self-driving car', 'augmented reality', 'blockchain',
        'zero-day', 'malware', 'phishing attack', 'tech giant', 'big tech',
        'sam altman', 'sundar pichai', 'programming language', 'developer tools',
    ],
    'FINANCE': [
        'stock market', 'share price', 'gdp growth', 'inflation rate', 'recession',
        'interest rate', 'central bank', 'rbi rate', 'federal reserve', 'rate hike',
        'earnings report', 'ipo listing', 'nifty', 'sensex', 'nasdaq', 'dow jones',
        'cryptocurrency', 'bitcoin price', 'ethereum', 'trade deficit', 'tariff hike',
        'merger deal', 'acquisition deal', 'quarterly results', 'revenue growth',
        'net profit', 'market cap', 'hedge fund', 'venture capital', 'bond yield',
        'q1 results', 'q2 results', 'q3 results', 'q4 results', 'earnings call',
        'fiscal year', 'ebitda', 'mutual fund', 'dividend payout', 'oil prices',
        'gold price', 'crude oil', 'sebi', 'financial results', 'stock rally',
        'market crash', 'economic growth', 'trade war',
    ],
    'HEALTH': [
        'vaccine rollout', 'vaccination drive', 'covid', 'cancer treatment',
        'cancer diagnosis', 'clinical trial', 'mental health crisis', 'obesity epidemic',
        'diabetes treatment', 'heart disease', 'cardiac arrest', 'cdc', 'fda approval',
        'drug approval', 'antibiotic resistance', 'public health emergency',
        'blood pressure treatment', 'chemotherapy', 'organ transplant', 'pathogen',
        'dengue outbreak', 'malaria outbreak', 'tuberculosis', 'hiv treatment',
        'pharmaceutical company', 'drug trial', 'disease outbreak', 'epidemic',
        'pandemic', 'virus outbreak', 'mpox', 'monkeypox', 'genome therapy',
        'medical breakthrough', 'health insurance', 'healthcare reform',
    ],
    'SCIENCE': [
        'nasa', 'space mission', 'asteroid', 'comet', 'galaxy', 'telescope',
        'black hole', 'fossil discovery', 'dinosaur', 'genome sequencing',
        'scientific discovery', 'carbon emission', 'renewable energy', 'nuclear fusion',
        'particle physics', 'evolution', 'spacex', 'rocket launch', 'space station',
        'dark matter', 'exoplanet', 'climate change study', 'ozone layer',
        'neutron star', 'cern', 'gravitational wave', 'mars mission', 'moon mission',
        'satellite launch', 'isro launch', 'new species', 'scientific research',
    ],
    'NATURE': [
        'marine life', 'coral reef', 'wildlife conservation', 'extinction threat',
        'biodiversity loss', 'deforestation', 'national park', 'ecosystem',
        'cyclone warning', 'hurricane warning', 'typhoon warning',
        'wildfire', 'endangered species', 'poaching', 'reforestation',
        'sea level rise', 'glacier melting', 'rainforest', 'migratory bird',
        'tiger reserve', 'mangrove', 'wetland conservation', 'nature reserve',
        'species discovery', 'animal rescue', 'ocean pollution', 'plastic pollution',
    ],
    'ENTERTAINMENT': [
        'film festival', 'box office collection', 'netflix series', 'disney plus',
        'amazon prime video', 'hbo series', 'grammy award', 'oscar award',
        'bafta award', 'emmy award', 'bollywood film', 'hollywood film',
        'music album release', 'concert tour', 'film review', 'movie release',
        'web series', 'season finale', 'music video', 'blockbuster film',
        'movie trailer', 'ott release', 'streaming platform', 'song release',
        'album launch', 'music chart',
    ],
    'FASHION': [
        'fashion week', 'runway show', 'haute couture', 'fashion designer',
        'fashion show', 'fashion trend', 'luxury fashion', 'luxury brand',
        'gucci', 'prada', 'louis vuitton', 'chanel', 'dior', 'versace', 'hermes',
        'sustainable fashion', 'streetwear brand', 'fashion industry',
        'spring collection', 'resort collection', 'ready-to-wear', 'fashion house',
        'fashion model', 'clothing brand', 'fashion label',
    ],
    'INDIA': [
        'india', 'delhi', 'mumbai', 'west bengal', 'kolkata', 'gujarat', 'rajasthan',
        'kashmir', 'punjab', 'bihar', 'odisha', 'kerala', 'tamil nadu',
        'andhra pradesh', 'telangana', 'assam', 'narendra modi', 'bjp',
        'aam aadmi party', 'trinamool', 'lok sabha', 'rajya sabha', 'bcci',
        'supreme court of india', 'indian army', 'indian economy',
        'indian railways', 'maharashtra', 'karnataka', 'manipur',
        'niti aayog', 'election commission of india', 'upi payment',
    ],
    'POLITICS': [
        'election result', 'presidential election', 'senate vote',
        'parliament session', 'democrat', 'republican', 'trump', 'biden',
        'kamala harris', 'ballot', 'election campaign', 'sanctions imposed',
        'nato summit', 'united nations', 'un security council',
        'g7 summit', 'g20 summit', 'ceasefire deal', 'coup attempt',
        'referendum', 'legislation passed', 'foreign policy', 'geopolitics',
        'civil war', 'peace talks', 'diplomatic visit', 'war escalation',
        'opposition leader', 'ruling party', 'coalition government',
    ],
    'EXPLORE': [
        'ancient civilization', 'archaeology discovery', 'mythology', 'philosophy',
        'unexplained phenomenon', 'hidden history', 'lost city', 'fascinating fact',
        'did you know', 'cultural heritage', 'anthropology', 'folk tradition',
        'exploration', 'bizarre discovery', 'trivia', 'mystery solved',
        'historical discovery', 'ancient ruins', 'cave painting', 'treasure found',
    ],
}


def _map_rss_tags(entry) -> str:
    """Step 1: map RSS <category> tags to an internal category. Returns '' if none match."""
    tags = getattr(entry, 'tags', []) or []
    for tag in tags:
        term = (tag.get('term') or tag.get('label') or '').lower().strip()
        if term in _RSS_CAT_MAP:
            return _RSS_CAT_MAP[term]
        for word in term.split():
            if word in _RSS_CAT_MAP:
                return _RSS_CAT_MAP[word]
    return ''


def _keyword_score(text: str) -> tuple[str, int]:
    """Step 2: score text against all categories. Returns (best_cat, best_score)."""
    best_cat, best_score = '', 0
    others_have_score = False
    scores = {}
    for cat, words in _KW.items():
        s = sum(1 for w in words if w in text)
        scores[cat] = s
        if s > best_score:
            best_score = s
            best_cat = cat
    # Count categories besides best that also scored > 0
    others_have_score = any(s > 0 for c, s in scores.items() if c != best_cat)
    # Threshold: ≥ 2 matches, OR only winner with ≥ 1 match
    if best_score >= 2 or (best_score == 1 and not others_have_score):
        return best_cat, best_score
    return '', 0


def classify_category(title: str, desc: str, source_category: str,
                       rss_tags_entry=None) -> str:
    """
    Guide-exact classifier:
      Step 1 — categoriesFromSource: use RSS <category> tags if they map cleanly
      Step 2 — keyword scoring: threshold ≥ 2, or sole scorer with ≥ 1
      Step 3 — source category (authoritative for sectional feeds)
    """
    # Step 1: source category tags
    if rss_tags_entry is not None:
        mapped = _map_rss_tags(rss_tags_entry)
        if mapped:
            return mapped

    # Step 2: keyword scoring
    text = (title + ' ' + desc).lower()
    cat, score = _keyword_score(text)
    if cat:
        return cat

    # Step 3: source category is the authoritative fallback for sectional feeds
    return source_category


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

def fetch_rss(source: dict, req_timeout: int = TIMEOUT) -> list:
    try:
        r    = requests.get(source['url'], timeout=req_timeout, headers=RSS_HEADERS)
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
            desc = _strip_html(entry.get('summary') or entry.get('description') or '')
            if len(desc) > 300:
                desc = desc[:300].rsplit(' ', 1)[0] + '…'
            src_cat = source.get('category', 'GEO-POLITICAL')
            out.append({
                'id': make_id(url), 'title': title, 'url': url,
                'source': source['name'], 'category': classify_category(title, desc, src_cat, entry),
                'authority': source.get('authority', 5),
                'published': pub.isoformat(), 'published_ts': pub.timestamp(),
                'cross_source_count': 1,
                'description': desc,
                'image': _extract_image(entry),
                'score': compute_score(source.get('authority', 5), pub.timestamp(), now),
            })
        return out
    except Exception:
        return []


def fetch_reddit(source: dict, req_timeout: int = TIMEOUT) -> list:
    try:
        r     = requests.get(source['url'], timeout=req_timeout, headers=REDDIT_HEADERS)
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
            src_cat  = source.get('category', 'GEO-POLITICAL')
            selftext = p.get('selftext', '')[:300] or ''
            out.append({
                'id': make_id(url), 'title': title, 'url': url,
                'source': source['name'], 'category': classify_category(title, selftext, src_cat, None),
                'authority': authority,
                'published': datetime.fromtimestamp(pub_ts).isoformat(),
                'published_ts': pub_ts,
                'cross_source_count': min(5, max(1, p.get('num_comments', 0) // 200 + 1)),
                'description': selftext,
                'score': compute_score(authority, pub_ts, now),
            })
        return out
    except Exception:
        return []


BN_SOURCES = [
    # ── Global Bengali — international outlets ────────────────────────────────
    {"name": "BBC Bangla",        "url": "https://feeds.bbci.co.uk/bengali/rss.xml",                        "category": "GEO-POLITICAL", "authority": 10},
    {"name": "DW বাংলা",          "url": "https://rss.dw.com/rdf/rss-ben-all",                             "category": "GEO-POLITICAL", "authority": 9},
    {"name": "Google News বাংলা", "url": "https://news.google.com/rss/headlines/section/geo/BD?hl=bn&gl=BD&ceid=BD:bn", "category": "GEO-POLITICAL", "authority": 9},
    {"name": "Google News বাংলা WB","url":"https://news.google.com/rss/headlines/section/geo/IN?hl=bn-IN&gl=IN&ceid=IN:bn","category": "GEO-POLITICAL","authority": 9},
    # ── Indian Bengali ────────────────────────────────────────────────────────
    {"name": "Sangbad Pratidin",  "url": "https://www.sangbadpratidin.in/feed/",                            "category": "GEO-POLITICAL", "authority": 8},
    {"name": "ABP Ananda",        "url": "https://bengali.abplive.com/feeds",                               "category": "GEO-POLITICAL", "authority": 8},
    # ── Bangladeshi Bengali ───────────────────────────────────────────────────
    {"name": "Prothom Alo",       "url": "https://www.prothomalo.com/feed/",                                "category": "GEO-POLITICAL", "authority": 9},
]

_cache: dict = {'en': {'ts': 0.0, 'data': []}, 'bn': {'ts': 0.0, 'data': []}}
CACHE_TTL = 60

def fetch_all_cached(lang: str = 'en') -> list:
    now = time.time()
    c = _cache[lang]
    if c['data'] and (now - c['ts']) < CACHE_TTL:
        return c['data']
    sources = BN_SOURCES if lang == 'bn' else SOURCES
    req_t, global_t = (BN_TIMEOUT, 15) if lang == 'bn' else (TIMEOUT, 8)
    data = fetch_all(sources, req_timeout=req_t, global_timeout=global_t)
    c['ts'] = now
    c['data'] = data
    return data

def fetch_all(sources=None, req_timeout: int = TIMEOUT, global_timeout: int = 8) -> list:
    if sources is None:
        sources = SOURCES
    seen, out = set(), []
    with ThreadPoolExecutor(max_workers=12) as ex:
        futs = {ex.submit(fetch_reddit if s.get('type') == 'reddit' else fetch_rss, s, req_timeout): s
                for s in sources}
        for fut in as_completed(futs, timeout=global_timeout):
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
