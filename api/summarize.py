from http.server import BaseHTTPRequestHandler
from urllib.parse import parse_qs, urlparse
import json


class handler(BaseHTTPRequestHandler):

    def do_GET(self):
        params = parse_qs(urlparse(self.path).query)
        url = params.get('url', [None])[0]

        if not url:
            self._respond({'summary': None})
            return

        summary = None
        try:
            from newspaper import Article
            from sumy.parsers.plaintext import PlaintextParser
            from sumy.nlp.tokenizers import Tokenizer
            from sumy.summarizers.lsa import LsaSummarizer

            article = Article(url)
            article.download()
            article.parse()

            text = article.text.strip()
            if text and len(text) >= 150:
                parser     = PlaintextParser.from_string(text, Tokenizer('english'))
                summarizer = LsaSummarizer()
                sentences  = summarizer(parser.document, 3)
                summary    = ' '.join(str(s) for s in sentences) or None
        except Exception:
            pass  # silent fallback — frontend shows existing description

        self._respond({'summary': summary})

    def _respond(self, data):
        body = json.dumps(data).encode()
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass
