import base64
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import server


class ServerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.data_patch = patch.object(server, 'DATA', Path(self.tmp.name).resolve())
        self.data_patch.start()
        server.JOBS.clear()

    def tearDown(self):
        self.data_patch.stop()
        self.tmp.cleanup()

    def job(self):
        job = dict(id='a' * 32, url='https://www.youtube.com/watch?v=BaW_jenozKc',
                   format='mp4', quality='720', title='Test', created=time.time(), status='queued', progress=0)
        server.JOBS[job['id']] = job
        server.update(job['id'])
        return job

    def test_canonicalizes_supported_links(self):
        for value in ['https://youtu.be/BaW_jenozKc?t=12',
                      'https://www.youtube.com/shorts/BaW_jenozKc',
                      'https://m.youtube.com/watch?v=BaW_jenozKc&list=ignored']:
            self.assertEqual(server.canonical_url(value), 'https://www.youtube.com/watch?v=BaW_jenozKc')

    def test_rejects_untrusted_inputs(self):
        for value in [None, 'file:///etc/passwd', 'http://localhost/video',
                      'https://youtube.com.evil.example/watch?v=BaW_jenozKc',
                      'https://evil@youtube.com/watch?v=BaW_jenozKc',
                      'https://youtube.com/playlist?list=abc', '--exec rm']:
            with self.subTest(value=value), self.assertRaises(ValueError):
                server.canonical_url(value)

    def test_clip_padding_and_time_formats(self):
        self.assertEqual(server.clip_range('01:30', '02:00'),
                         dict(start=90, end=120, padded_start=85, padded_end=125))
        self.assertEqual(server.clip_range('3', '10')['padded_start'], 0)
        self.assertEqual(server.parse_time('01:02:03'), 3723)
        self.assertIsNone(server.clip_range('', ''))
        self.assertIsNone(server.clip_range(None, None))

    def test_invalid_clip_ranges(self):
        for start, end in [('', '10'), ('10', ''), ('20', '10'), ('10', '10'),
                           ('-1', '10'), ('1:60', '200'), ('1', '7201'),
                           ('NaN', '10'), (True, '10'), ('1;cmd', '10')]:
            with self.subTest(start=start, end=end), self.assertRaises(ValueError):
                server.clip_range(start, end)

    def test_clip_command_for_video_and_audio(self):
        job = self.job()
        self.assertNotIn('--download-sections', server.command(job))
        job['clip'] = server.clip_range('01:30', '02:00')
        for fmt in ('mp4', 'mp3'):
            job['format'] = fmt
            cmd = server.command(job)
            self.assertEqual(cmd[cmd.index('--download-sections') + 1], '*85-125')
            self.assertIn('--force-keyframes-at-cuts', cmd)

    def test_command_does_not_invoke_shell_or_playlists(self):
        job = self.job()
        cmd = server.command(job)
        self.assertIn('--no-playlist', cmd)
        self.assertEqual(cmd[-2:], ['--', job['url']])
        self.assertIn('bv*[ext=mp4][height<=720]+ba[ext=m4a]/b[ext=mp4][height<=720]', cmd)
        job['format'] = 'mp3'
        self.assertIn('--audio-format', server.command(job))

    def test_worker_tracks_output_and_completion(self):
        job = self.job()
        output = server.DATA / job['id'] / 'sample.mp4'
        script = f"from pathlib import Path; Path({str(output)!r}).write_bytes(b'test'); print('TITLE:Sample'); print('PROGRESS:50.0%'); print('FILE:' + {str(output)!r})"
        with patch.object(server, 'command', return_value=[sys.executable, '-c', script]):
            server.run_job(job['id'])
        self.assertEqual(job['status'], 'ready')
        self.assertEqual(job['title'], 'Sample')
        self.assertEqual(job['size'], 4)
        self.assertEqual(json.loads((output.parent / 'job.json').read_text())['status'], 'ready')

    def test_worker_reports_failure(self):
        job = self.job()
        with patch.object(server, 'command', return_value=[sys.executable, '-c', "import sys; print('ERROR: Unavailable video'); sys.exit(1)"]):
            server.run_job(job['id'])
        self.assertEqual(job['status'], 'error')
        self.assertEqual(job['error'], 'Unavailable video')

    def test_cleanup_preserves_running_jobs(self):
        job = self.job()
        job['created'] -= server.TTL + 1
        server.cleanup()
        self.assertIn(job['id'], server.JOBS)
        job['status'] = 'error'
        server.cleanup()
        self.assertNotIn(job['id'], server.JOBS)
        self.assertFalse((server.DATA / job['id']).exists())

    def test_http_validation_auth_and_download(self):
        httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.Handler)
        threading.Thread(target=httpd.serve_forever, daemon=True).start()
        def request(method, path, body=None, headers=None):
            conn = http.client.HTTPConnection('127.0.0.1', httpd.server_port)
            conn.request(method, path, body, headers or {})
            response = conn.getresponse()
            result = response.status, response.read(), dict(response.getheaders())
            conn.close()
            return result
        try:
            self.assertEqual(request('GET', '/')[0], 200)
            self.assertEqual(request('GET', '/../server.py')[0], 404)
            with patch.object(server, 'PASSWORD', 'secret'):
                self.assertEqual(request('GET', '/api/jobs')[0], 401)
                auth = 'Basic ' + base64.b64encode(b'admin:secret').decode()
                self.assertEqual(request('GET', '/api/jobs', headers={'Authorization': auth})[0], 200)
            body = json.dumps(dict(url='https://youtu.be/BaW_jenozKc', format='mp4', quality='720'))
            headers = {'Content-Type': 'application/json', 'Origin': 'https://evil.example'}
            self.assertEqual(request('POST', '/api/jobs', body, headers)[0], 403)
            headers.pop('Origin')
            self.assertEqual(request('POST', '/api/jobs', '[]', headers)[0], 400)
            with patch.object(server, 'dependencies', return_value=['FFmpeg']):
                self.assertEqual(request('POST', '/api/jobs', body, headers)[0], 503)
                with patch.object(server, 'PUBLIC_ORIGIN', 'https://pocket-example.vercel.app'):
                    headers['Origin'] = 'https://pocket-example.vercel.app'
                    self.assertEqual(request('POST', '/api/jobs', body, headers)[0], 503)
                    headers['Origin'] = 'https://pocket-example.vercel.app.evil.example'
                    self.assertEqual(request('POST', '/api/jobs', body, headers)[0], 403)
                    headers.pop('Origin')
            with patch.object(server, 'dependencies', return_value=[]), patch.object(server.QUEUE, 'put') as put, patch.object(server.shutil, 'disk_usage') as disk:
                disk.return_value.free = 10 * 1024**3
                self.assertEqual(request('POST', '/api/jobs', body, headers)[0], 202)
                put.assert_called_once()
                for i in range(7):
                    self.assertEqual(request('POST', '/api/jobs', body, headers)[0], 202)
                self.assertEqual(request('POST', '/api/jobs', body, headers)[0], 429)
            job = self.job()
            file = server.DATA / job['id'] / 'hello.mp4'
            file.write_bytes(b'example media')
            server.update(job['id'], status='ready', filename=file.name)
            status, data, headers = request('GET', '/files/' + job['id'])
            self.assertEqual((status, data), (200, b'example media'))
            self.assertIn('attachment', headers['Content-Disposition'])
        finally:
            httpd.shutdown()
            httpd.server_close()


if __name__ == '__main__':
    unittest.main()
