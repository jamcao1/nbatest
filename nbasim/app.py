"""Local dashboard and JSON API; no external Python dependencies."""
import argparse
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .data import ROOT, demo_dataset, validate_dataset
from .model import backtest, report
from .provider import live_dataset

STATIC = ROOT / 'nbasim/static'
LIVE_LOCK = threading.Lock()


class Handler(BaseHTTPRequestHandler):
    def send(self, status, body, content_type='application/json; charset=utf-8'):
        if not isinstance(body, bytes):
            body = json.dumps(body, allow_nan=False).encode()
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        route = urlsplit(self.path)
        query = parse_qs(route.query)
        try:
            if route.path == '/api/health':
                return self.send(200, {'status': 'ok'})
            if route.path == '/api/demo':
                return self.send(200, demo_dataset(query.get('week', ['2015-04-06'])[0]))
            if route.path == '/api/live':
                if not LIVE_LOCK.acquire(blocking=False):
                    return self.send(429, {'error': 'A live-data request is already running. Try again when it finishes.'})
                try:
                    return self.send(200, live_dataset(query.get('week', [''])[0]))
                finally:
                    LIVE_LOCK.release()
            if route.path == '/api/backtest':
                season = json.loads((ROOT / 'data/season_2015.json').read_text())
                return self.send(200, backtest(season['games']))
            files = {'/': ('index.html', 'text/html; charset=utf-8'),
                     '/app.js': ('app.js', 'text/javascript; charset=utf-8'),
                     '/style.css': ('style.css', 'text/css; charset=utf-8')}
            if route.path in files:
                filename, mime = files[route.path]
                return self.send(200, (STATIC / filename).read_bytes(), mime)
            return self.send(404, {'error': 'Not found'})
        except ValueError as exc:
            return self.send(400, {'error': str(exc)})
        except Exception:
            self.log_error('Unexpected server error')
            return self.send(500, {'error': 'Unexpected server error; inspect the terminal.'})

    def do_POST(self):
        if urlsplit(self.path).path != '/api/simulate':
            return self.send(404, {'error': 'Not found'})
        # Browser writes must originate from this local application.
        origin = self.headers.get('Origin')
        if origin and urlsplit(origin).netloc != self.headers.get('Host'):
            return self.send(403, {'error': 'Cross-origin requests are not allowed.'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.send(415, {'error': 'Use application/json.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if not 0 < size <= 2_000_000:
                return self.send(413, {'error': 'Upload a JSON body smaller than 2 MB.'})
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict) or not isinstance(body.get('odds_csv', ''), str):
                raise ValueError('Request must be an object; odds_csv must be text.')
            result = report(body.get('dataset'), body.get('seed', 42), body.get('odds_csv', ''))
            return self.send(200, result)
        except (ValueError, UnicodeError) as exc:
            return self.send(400, {'error': str(exc)})
        except Exception:
            self.log_error('Unexpected simulation error')
            return self.send(500, {'error': 'Unexpected simulation error; inspect the terminal.'})


def main():
    parser = argparse.ArgumentParser(description='Courtside NBA simulation dashboard')
    parser.add_argument('--host', default='127.0.0.1')
    parser.add_argument('--port', type=int, default=8000)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f'Courtside listening on {args.host}:{args.port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == '__main__':
    main()
