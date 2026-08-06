from http.server import BaseHTTPRequestHandler
import json
import hashlib
import math
import os
import time
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import urlparse, parse_qs, quote

import re
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


# ── Category classifier ────────────────────────────────────────────────────────

# Sources in _NICHE publish off-topic content — require keyword confirmation.
# If no keyword matches, fall back to GEO-POLITICAL instead of source category.
# Only SPORTS and GEO-POLITICAL are trusted enough to use as a raw fallback.
_NICHE = {
    'TECH', 'FINANCE', 'HEALTH', 'SCIENCE',
    'FASHION', 'ENTERTAINMENT', 'EXPLORE', 'NATURE',
    'INDIA', 'POLITICS',
}

# Map RSS <category> / <tag> terms → internal categories (lowercase keys)
_RSS_CAT_MAP = {
    'technology': 'TECH',         'tech': 'TECH',        'science & technology': 'TECH',
    'gadgets': 'TECH',            'computing': 'TECH',   'internet': 'TECH',
    'business': 'FINANCE',        'finance': 'FINANCE',  'economy': 'FINANCE',
    'markets': 'FINANCE',         'investing': 'FINANCE','money': 'FINANCE',
    'sports': 'SPORTS',           'sport': 'SPORTS',     'cricket': 'SPORTS',
    'football': 'SPORTS',         'soccer': 'SPORTS',    'tennis': 'SPORTS',
    'health': 'HEALTH',           'medicine': 'HEALTH',  'wellness': 'HEALTH',
    'medical': 'HEALTH',
    'science': 'SCIENCE',         'space': 'SCIENCE',    'environment': 'SCIENCE',
    'climate': 'SCIENCE',
    'entertainment': 'ENTERTAINMENT', 'arts': 'ENTERTAINMENT', 'movies': 'ENTERTAINMENT',
    'music': 'ENTERTAINMENT',     'television': 'ENTERTAINMENT', 'film': 'ENTERTAINMENT',
    'fashion': 'FASHION',         'style': 'FASHION',    'beauty': 'FASHION',
    'politics': 'POLITICS',       'government': 'POLITICS', 'world politics': 'POLITICS',
    'india': 'INDIA',             'nation': 'INDIA',     'national': 'INDIA',
    'nature': 'NATURE',           'wildlife': 'NATURE',  'ocean': 'NATURE',
    'world': 'GEO-POLITICAL',     'international': 'GEO-POLITICAL', 'global': 'GEO-POLITICAL',
    'travel': 'EXPLORE',          'history': 'EXPLORE',  'culture': 'EXPLORE',
}

# Keyword lists per category — whole-word matched, scored across all categories
_KW = {
    # Only use words that ARE THE TOPIC, not words that appear incidentally in any story.
    # Bad: "hospital" (crime stories set in hospitals), "doctor" (any person story),
    #      "earthquake" (appears in political speeches), "actor" (crime/politics).
    # Good: "vaccine", "ipl", "nasdaq" — these only appear when the topic IS that category.
    'SPORTS': [
        'cricket', 'football', 'soccer', 'tennis', 'golf', 'basketball', 'hockey',
        'rugby', 'olympic', 'olympics', 'ipl', 'fifa', 'wimbledon', 'formula 1',
        'grand prix', 'batsman', 'bowler', 'wicket', 'wicketkeeper', 'innings',
        'odi', 't20', 'test match', 'world cup cricket', 'hat-trick', 'penalty shootout',
        'offside', 'slam dunk', 'birdie', 'bogey', 'premier league', 'la liga',
        'bundesliga', 'transfer window', 'nba', 'nfl', 'mlb', 'nhl', 'ufc',
        'badminton', 'table tennis', 'run chase', 'powerplay', 'over-by-over',
        'match report', 'match preview', 'test series', 'series win', 'series loss',
        'century stand', 'double century', 'half century', 'bowling figures',
    ],
    'TECH': [
        'artificial intelligence', 'machine learning', 'chatgpt', 'openai', 'gemini',
        'claude ai', 'llm', 'large language model', 'robotics', 'semiconductor',
        'gpu', 'nvidia', 'iphone launch', 'android update', 'cybersecurity',
        'data breach', 'ransomware', 'quantum computing', 'drone technology',
        'silicon valley', 'deep learning', 'neural network', 'tech layoffs',
        'software engineer', 'cloud computing', 'generative ai', 'microsoft azure',
        'apple inc', 'google deepmind', 'anthropic', 'startup funding',
        'series a funding', 'series b funding', 'saas', 'open source software',
        'autonomous vehicle', 'self-driving car', 'augmented reality', 'virtual reality',
        'blockchain', 'zero-day', 'malware', 'phishing attack',
        'tech giant', 'big tech', 'elon musk', 'sam altman', 'sundar pichai',
        'mark zuckerberg', 'programming language', 'developer tools', 'api launch',
    ],
    'FINANCE': [
        'stock market', 'share price', 'gdp growth', 'inflation rate', 'recession',
        'interest rate', 'central bank', 'rbi rate', 'federal reserve', 'rate hike',
        'budget deficit', 'earnings report', 'ipo listing', 'nifty', 'sensex',
        'nasdaq', 'dow jones', 'cryptocurrency', 'bitcoin price', 'ethereum',
        'trade deficit', 'tariff hike', 'merger deal', 'acquisition deal',
        'quarterly results', 'revenue growth', 'net profit', 'market cap',
        'hedge fund', 'venture capital', 'private equity', 'bond yield', 'forex',
        'q1 results', 'q2 results', 'q3 results', 'q4 results', 'earnings call',
        'fiscal year', 'ebitda', 'mutual fund', 'dividend payout',
        'shares rally', 'shares fall', 'oil prices', 'gold price', 'crude oil',
        'sebi', 'financial results', 'profit rises', 'profit falls',
        'economic growth', 'trade war', 'import duty', 'export ban',
        'ipo price', 'listing gain', 'stock rally', 'market crash',
    ],
    'HEALTH': [
        # Only use words that are the health topic itself — never incidental settings
        'vaccine rollout', 'vaccination drive', 'covid', 'cancer treatment',
        'cancer diagnosis', 'clinical trial', 'mental health crisis', 'obesity epidemic',
        'diabetes treatment', 'heart disease', 'cardiac arrest', 'cdc', 'fda approval',
        'drug approval', 'antibiotic resistance', 'public health emergency',
        'blood pressure treatment', 'chemotherapy', 'organ transplant', 'pathogen',
        'dengue outbreak', 'malaria outbreak', 'tuberculosis', 'hiv treatment',
        'pharmaceutical company', 'drug trial', 'side effects', 'health ministry alert',
        'disease outbreak', 'epidemic', 'pandemic', 'virus outbreak', 'mpox',
        'monkeypox', 'genome therapy', 'medical breakthrough',
        'health insurance', 'healthcare reform', 'medical college',
        'ayushman bharat', 'pmjay', 'aiims',
    ],
    'SCIENCE': [
        'nasa', 'space mission', 'asteroid', 'comet', 'galaxy', 'telescope',
        'black hole', 'fossil discovery', 'dinosaur', 'genome sequencing',
        'scientific discovery', 'carbon emission', 'renewable energy', 'nuclear fusion',
        'particle physics', 'evolution', 'spacex', 'rocket launch', 'space station',
        'dark matter', 'exoplanet', 'climate change study', 'ozone layer',
        'neutron star', 'cern', 'quantum entanglement', 'big bang', 'gravitational wave',
        'mars mission', 'moon mission', 'satellite launch', 'isro launch',
        'new species', 'scientific research', 'physics experiment',
    ],
    'NATURE': [
        'marine life', 'coral reef', 'wildlife conservation', 'extinction threat',
        'biodiversity loss', 'deforestation', 'national park', 'ecosystem',
        'cyclone warning', 'hurricane warning', 'typhoon warning',
        'wildfire', 'endangered species', 'poaching', 'reforestation',
        'sea level rise', 'glacier melting', 'rainforest', 'migratory bird',
        'tiger reserve', 'mangrove', 'wetland conservation', 'nature reserve',
        'species discovery', 'animal rescue', 'ocean pollution', 'plastic pollution',
        'flood devastation', 'earthquake damage', 'drought relief',
    ],
    'ENTERTAINMENT': [
        'film festival', 'box office collection', 'netflix series', 'disney plus',
        'amazon prime video', 'hbo series', 'grammy award', 'oscar award',
        'bafta award', 'emmy award', 'bollywood film', 'hollywood film',
        'music album release', 'concert tour', 'film review', 'movie release',
        'web series', 'season finale', 'music video', 'stand-up comedy',
        'sitcom', 'blockbuster film', 'movie trailer', 'ott release',
        'box office hit', 'box office flop', 'streaming platform',
        'song release', 'album launch', 'music chart',
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
        'indian railways', 'maharashtra', 'karnataka', 'himachal pradesh',
        'uttarakhand', 'jharkhand', 'chhattisgarh', 'manipur',
        'bombay high court', 'niti aayog', 'election commission of india',
        'upi payment', 'make in india', 'india gdp', 'india inflation',
    ],
    'POLITICS': [
        'election result', 'presidential election', 'prime minister', 'senate vote',
        'parliament session', 'democrat', 'republican', 'trump', 'biden',
        'kamala harris', 'ballot', 'election campaign', 'sanctions imposed',
        'nato summit', 'united nations', 'un security council',
        'g7 summit', 'g20 summit', 'ceasefire deal', 'coup attempt',
        'referendum', 'legislation passed', 'foreign policy', 'geopolitics',
        'political party', 'civil war', 'peace talks', 'diplomatic visit',
        'head of state', 'prime minister visit', 'state visit', 'war escalation',
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

# Pre-compile all patterns for performance
_KW_PATTERNS = {
    cat: [re.compile(r'\b' + re.escape(kw) + r'\b') for kw in kws]
    for cat, kws in _KW.items()
}


def _rss_category(entry) -> str:
    """Extract the best matching category from RSS <category> tags."""
    tags = getattr(entry, 'tags', []) or []
    for tag in tags:
        term = (tag.get('term') or tag.get('label') or '').lower().strip()
        # Try full term first, then each word in the term
        if term in _RSS_CAT_MAP:
            return _RSS_CAT_MAP[term]
        for word in term.split():
            if word in _RSS_CAT_MAP:
                return _RSS_CAT_MAP[word]
    return ''


def classify_category(title: str, desc: str, source_category: str,
                       rss_category: str = '') -> str:
    """
    Three-pass classifier:
      1. RSS <category> tags from the feed (most reliable signal)
      2. Score-based keyword matching on title + description — picks highest scorer
      3. Tiered fallback: niche sources → GEO-POLITICAL, core → source category
    """
    # Pass 1 — trust RSS-provided category tag
    if rss_category:
        return rss_category

    # Pass 2 — score every category; pick highest with at least 1 hit
    text = (title + ' ' + desc).lower()
    best_cat, best_score = '', 0
    for cat, patterns in _KW_PATTERNS.items():
        score = sum(1 for p in patterns if p.search(text))
        if score > best_score:
            best_score, best_cat = score, cat
    if best_cat:
        return best_cat

    # Pass 3 — tiered fallback
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
            rss_cat = _rss_category(entry)
            out.append({
                'id': make_id(url), 'title': title, 'url': url,
                'source': source['name'], 'category': classify_category(title, desc, src_cat, rss_cat),
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
            src_cat  = source.get('category', 'GEO-POLITICAL')
            selftext = p.get('selftext', '')[:300] or ''
            out.append({
                'id': make_id(url), 'title': title, 'url': url,
                'source': source['name'], 'category': classify_category(title, selftext, src_cat),
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
