"""Personal YouTube downloader. Run behind an HTTPS proxy for remote access."""
import base64
import hmac
import importlib.util
import json
import mimetypes
import os
from pathlib import Path
import queue
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse
import uuid

ROOT = Path(__file__).parent
DATA = Path(os.environ.get('DATA_DIR', ROOT / 'data')).resolve()
PASSWORD = os.environ.get('APP_PASSWORD', '')
PUBLIC_ORIGIN = os.environ.get('PUBLIC_ORIGIN', '').rstrip('/')
JOBS = {}
LOCK = threading.RLock()
QUEUE = queue.Queue()
TTL = 24 * 3600


def canonical_url(value):
    if not isinstance(value, str) or len(value) > 2048:
        raise ValueError('Paste a valid YouTube video link.')
    parsed = urlparse(value.strip())
    if parsed.scheme not in ('https', 'http') or parsed.username or parsed.password:
        raise ValueError('Use an http or https YouTube video link.')
    host = parsed.hostname
    parts = parsed.path.strip('/').split('/')
    video = None
    if host == 'youtu.be' and len(parts) == 1:
        video = parts[0]
    elif host in ('youtube.com', 'www.youtube.com', 'm.youtube.com', 'music.youtube.com'):
        if parsed.path == '/watch':
            video = parse_qs(parsed.query).get('v', [None])[0]
        elif len(parts) == 2 and parts[0] in ('shorts', 'embed', 'live'):
            video = parts[1]
    if not video or not re.fullmatch(r'[A-Za-z0-9_-]{11}', video):
        raise ValueError('Use a YouTube video or Shorts link, rather than a playlist.')
    return 'https://www.youtube.com/watch?v=' + video


def parse_time(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{1,5}(?::\d{2}){0,2}', value.strip()):
        raise ValueError('Enter times as seconds, MM:SS, or HH:MM:SS.')
    parts = [int(part) for part in value.strip().split(':')]
    if any(part >= 60 for part in parts[1:]):
        raise ValueError('Minutes and seconds after a colon must be below 60.')
    seconds = 0
    for part in parts:
        seconds = seconds * 60 + part
    return seconds


def clip_range(start, end):
    if start in (None, '') and end in (None, ''):
        return None
    if start in (None, '') or end in (None, ''):
        raise ValueError('Enter both a start and an end time, or leave both blank for the full video.')
    start, end = parse_time(start), parse_time(end)
    if end <= start:
        raise ValueError('The end time must be after the start time.')
    if end > 7200:
        raise ValueError('Clip times must be within the two-hour video limit.')
    return {'start': start, 'end': end, 'padded_start': max(0, start - 5), 'padded_end': end + 5}


def dependencies():
    return [name for name, ok in (
        ('yt-dlp', importlib.util.find_spec('yt_dlp') is not None),
        ('FFmpeg', shutil.which('ffmpeg')),
        ('Node.js', shutil.which('node')),
    ) if not ok]


def update(job_id, **fields):
    with LOCK:
        JOBS[job_id].update(fields)
        directory = DATA / job_id
        directory.mkdir(parents=True, exist_ok=True)
        temp = directory / 'job.tmp'
        temp.write_text(json.dumps(JOBS[job_id]))
        temp.replace(directory / 'job.json')


def command(job):
    cmd = [sys.executable, '-m', 'yt_dlp', '--ignore-config', '--no-playlist',
           '--js-runtimes', 'node', '--newline', '--no-colors', '--no-simulate',
           '--socket-timeout', '30', '--retries', '3', '--max-filesize', '2G',
           '--match-filters', '!is_live & duration < 7200',
           '--progress-template', 'download:PROGRESS:%(progress._percent_str)s',
           '--print', 'before_dl:TITLE:%(title)s',
           '--print', 'after_move:FILE:%(filepath)s',
           '-o', str(DATA / job['id'] / '%(title).150B [%(id)s].%(ext)s')]
    if job['format'] == 'mp3':
        cmd += ['-f', 'bestaudio/best', '-x', '--audio-format', 'mp3', '--audio-quality', '192K']
    else:
        height = job['quality']
        cmd += ['-f', f'bv*[ext=mp4][height<={height}]+ba[ext=m4a]/b[ext=mp4][height<={height}]',
                '--merge-output-format', 'mp4']
    clip = job.get('clip')
    if clip:
        cmd += ['--download-sections', f"*{clip['padded_start']}-{clip['padded_end']}",
                '--force-keyframes-at-cuts']
    return cmd + ['--', job['url']]


def run_job(job_id):
    job = JOBS[job_id]
    update(job_id, status='downloading')
    process = None
    timer = None
    expired = threading.Event()
    try:
        process = subprocess.Popen(command(job), stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, start_new_session=True)
        def timeout():
            expired.set()
            try:
                os.killpg(process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        timer = threading.Timer(1800, timeout)
        timer.start()
        result = None
        last_error = ''
        for line in process.stdout:
            line = line.strip()
            if line.startswith('TITLE:'):
                update(job_id, title=line[6:])
            elif line.startswith('PROGRESS:'):
                match = re.search(r'(\d+(?:\.\d+)?)%', line)
                if match:
                    update(job_id, progress=min(99, float(match[1])))
            elif line.startswith('FILE:'):
                result = Path(line[5:]).resolve()
                update(job_id, status='processing')
            elif line.startswith('ERROR:'):
                last_error = line[6:].strip()[:500]
            elif line.startswith(('[Merger]', '[ExtractAudio]')):
                update(job_id, status='processing')
        code = process.wait()
        if expired.is_set():
            raise ValueError('This download exceeded the 30-minute time limit.')
        if code != 0 or not result or not result.is_file():
            raise ValueError(last_error or 'No file was produced. The video may be unavailable, live, too long, or too large.')
        if result.parent != DATA / job_id or result.suffix not in ('.mp4', '.mp3'):
            raise ValueError('Unexpected download output.')
        update(job_id, status='ready', progress=100, filename=result.name, size=result.stat().st_size)
    except Exception as exc:
        update(job_id, status='error', error=str(exc)[:500])
        for path in (DATA / job_id).iterdir():
            if path.is_file() and path.name != 'job.json':
                path.unlink(missing_ok=True)
    finally:
        if timer:
            timer.cancel()
        if process and process.stdout:
            process.stdout.close()


def worker():
    while True:
        job_id = QUEUE.get()
        try:
            run_job(job_id)
        finally:
            QUEUE.task_done()


def cleanup():
    with LOCK:
        for job_id, job in list(JOBS.items()):
            if job['status'] in ('ready', 'error') and time.time() - job['created'] > TTL:
                shutil.rmtree(DATA / job_id, ignore_errors=True)
                del JOBS[job_id]


def janitor():
    while True:
        cleanup()
        time.sleep(60)


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(30)

    def authenticated(self):
        expected = 'Basic ' + base64.b64encode(('admin:' + PASSWORD).encode()).decode()
        if PASSWORD and not hmac.compare_digest(self.headers.get('Authorization', ''), expected):
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="Pocket", charset="UTF-8"')
            self.end_headers()
            return False
        return True

    def headers_for(self, status, content_type, size):
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(size))
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Cache-Control', 'no-store')
        self.send_header('Referrer-Policy', 'no-referrer')
        self.send_header('Content-Security-Policy', "default-src 'self'; style-src 'self'; script-src 'self'; img-src 'self'; object-src 'none'; frame-ancestors 'none'; base-uri 'none'")

    def json(self, status, body):
        encoded = json.dumps(body).encode()
        self.headers_for(status, 'application/json', len(encoded))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self):
        if not self.authenticated():
            return
        path = urlparse(self.path).path
        if path == '/api/jobs':
            with LOCK:
                return self.json(200, {'jobs': sorted(JOBS.values(), key=lambda j: j['created'], reverse=True), 'missing': dependencies()})
        if path.startswith('/files/'):
            job_id = path.removeprefix('/files/')
            with LOCK:
                job = JOBS.get(job_id)
                if not job or job['status'] != 'ready':
                    return self.json(404, {'error': 'Download not found or expired.'})
                file = DATA / job_id / job['filename']
                try:
                    stream = file.open('rb')
                except FileNotFoundError:
                    return self.json(404, {'error': 'This file has expired.'})
            with stream:
                self.headers_for(200, mimetypes.guess_type(file.name)[0] or 'application/octet-stream', os.fstat(stream.fileno()).st_size)
                from urllib.parse import quote
                self.send_header('Content-Disposition', "attachment; filename*=UTF-8''" + quote(file.name))
                self.end_headers()
                try:
                    shutil.copyfileobj(stream, self.wfile)
                except (BrokenPipeError, ConnectionResetError):
                    pass
            return
        static = {'/': 'index.html', '/app.js': 'app.js', '/style.css': 'style.css'}
        if path not in static:
            return self.json(404, {'error': 'Not found.'})
        file = ROOT / 'static' / static[path]
        body = file.read_bytes()
        self.headers_for(200, (mimetypes.guess_type(file.name)[0] or 'text/plain') + '; charset=utf-8', len(body))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if not self.authenticated():
            return
        origin = self.headers.get('Origin')
        if (self.headers.get('Sec-Fetch-Site') == 'cross-site' or
            (origin and origin != PUBLIC_ORIGIN and urlparse(origin).netloc != self.headers.get('Host'))):
            return self.json(403, {'error': 'Cross-site requests are not allowed.'})
        if self.path != '/api/jobs':
            return self.json(404, {'error': 'Not found.'})
        if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
            return self.json(415, {'error': 'JSON required.'})
        try:
            size = int(self.headers.get('Content-Length', '0'))
            if size <= 0 or size > 4096:
                raise ValueError('Invalid request size.')
            body = json.loads(self.rfile.read(size))
            if not isinstance(body, dict):
                raise ValueError('Invalid request.')
            url = canonical_url(body.get('url'))
            clip = clip_range(body.get('start'), body.get('end'))
            fmt, quality = body.get('format'), str(body.get('quality'))
            if fmt not in ('mp4', 'mp3') or quality not in ('360', '720', '1080'):
                raise ValueError('Choose a supported format and quality.')
        except (ValueError, UnicodeDecodeError) as exc:
            return self.json(400, {'error': str(exc)})
        missing = dependencies()
        if missing:
            return self.json(503, {'error': 'Server setup required: install ' + ', '.join(missing) + ', or use Docker.'})
        with LOCK:
            if sum(j['status'] in ('queued', 'downloading', 'processing') for j in JOBS.values()) >= 8:
                return self.json(429, {'error': 'The queue is full. Try again once a download finishes.'})
            if shutil.disk_usage(DATA).free < 5 * 1024**3:
                return self.json(507, {'error': 'The server needs at least 5 GB of free disk space.'})
            job_id = uuid.uuid4().hex
            JOBS[job_id] = dict(id=job_id, url=url, format=fmt, quality=quality, created=time.time(),
                                title='Fetching video details…', status='queued', progress=0, clip=clip)
            update(job_id)
            QUEUE.put(job_id)
            self.json(202, JOBS[job_id])


def main():
    DATA.mkdir(parents=True, exist_ok=True)
    for file in DATA.glob('*/job.json'):
        try:
            job = json.loads(file.read_text())
            if job['id'] != file.parent.name or not re.fullmatch('[a-f0-9]{32}', job['id']):
                continue
            JOBS[job['id']] = job
            if job['status'] not in ('ready', 'error'):
                update(job['id'], status='error', error='The server restarted. Please try the download again.')
        except (ValueError, KeyError):
            continue
    cleanup()
    threading.Thread(target=worker, daemon=True).start()
    threading.Thread(target=janitor, daemon=True).start()
    host, port = os.environ.get('HOST', '127.0.0.1'), int(os.environ.get('PORT', '8080'))
    print(f'Pocket is listening on http://{host}:{port}', flush=True)
    ThreadingHTTPServer((host, port), Handler).serve_forever()


if __name__ == '__main__':
    main()
