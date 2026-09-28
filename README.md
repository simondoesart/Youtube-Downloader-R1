# Pocket — personal YouTube downloader

A small self-hosted website for saving individual YouTube videos as MP4 (up to 1080p) or MP3 (192 kbps). Includes a responsive interface, a sequential download queue, progress, browser downloads, optional password protection, and automatic 24-hour cleanup.

**Deploying from GitHub to Vercel? Follow [DEPLOY.md](DEPLOY.md).** The included Vercel configuration publishes the interface; functional downloads require the Docker backend described in that guide.

## Start with Docker

Install Docker with Compose on your computer, NAS, or server. From this folder:

```sh
docker compose up -d --build
```

Open **http://localhost:8080**. Paste a YouTube video or Shorts URL, select format and quality, and click **Save to my shelf**. When ready, click **Download** to save the file to your device. Closing the browser does not stop a queued download.

To save a clip, enter both **Start time** and **End time** as seconds, `MM:SS`, or `HH:MM:SS`. The app adds five seconds on either side: `01:30–02:00` requests `01:25–02:05`. The start is clamped to zero and the media ends at the source's end if padding runs beyond it. Leave both fields blank for the full video. Clips work for MP4 and MP3. The downloader uses FFmpeg section downloads and re-encoding at cut points for more accurate boundaries; padding provides extra context but does not guarantee a successful download. Depending on the source, additional data may need to be fetched. The existing source-video duration limit still applies.

Docker installs Python, FFmpeg, Node.js 24, and yt-dlp with its JavaScript components. Current YouTube support requires a compatible JavaScript runtime and the EJS package: [yt-dlp setup documentation](https://github.com/yt-dlp/yt-dlp/wiki/EJS).

## Access from another device

The default port is accessible only on the host computer. For a trusted home network, create a `.env` file next to `compose.yaml`:

```dotenv
BIND_ADDRESS=0.0.0.0
APP_PASSWORD=replace-with-a-long-unique-password
```

Re-run `docker compose up -d`, then open `http://YOUR-SERVER-IP:8080`. Sign in with username **admin** and your password. All users share one shelf; this is a personal app, not a multi-user service.

For public access, keep the Docker port bound to `127.0.0.1`, set `APP_PASSWORD`, and put an HTTPS reverse proxy in front. Example Caddy configuration when Caddy runs directly on the same host:

```caddyfile
downloads.example.com {
    reverse_proxy 127.0.0.1:8080
}
```

Replace the domain with yours and point its DNS to your server. HTTPS is necessary to protect the password over the internet. A proxy running in a separate container needs a shared Docker network and `downloader:8080` as its upstream instead. Preserve the original Host header.

## Maintenance

```sh
# Get current downloader fixes and rebuild dependencies
docker compose build --pull --no-cache
docker compose up -d

# Read logs
docker compose logs -f

# Stop; retain downloaded files
docker compose down
```

Files and job metadata persist in a Docker volume. Completed and failed jobs expire 24 hours after submission. Interrupted jobs are marked failed after a restart and can be submitted again. The queue allows eight pending or running jobs, processes one at a time, and requires 5 GB of free disk space before accepting a job. Videos must be shorter than two hours; live streams and playlists are excluded. Each job times out after 30 minutes. yt-dlp applies a 2 GB file limit where supported; this is not a hard disk quota, and merged files or unknown-size downloads can exceed it. Use a volume quota for strict storage limits.

## Run without Docker

Requires Python 3.10+, FFmpeg, and Node.js 22+ installed and available on PATH (Node.js 24 recommended).

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python server.py
```

This starts on `127.0.0.1:8080`. Optional environment variables: `HOST`, `PORT`, `DATA_DIR`, `APP_PASSWORD`. Local files default to `data/` beside `server.py`. Keep this service behind an HTTPS proxy when accessing it remotely.

## Verification and limitations

Run the automated checks with `python3 -m unittest discover -s tests -v`. They cover URL restrictions, queue limits, authentication, cross-site request rejection, file delivery, worker success/failure, persistence, and expiry. Worker tests use a controlled process, not a real YouTube download.

YouTube may reject downloads from some server IPs or require sign-in for particular videos. This version does not accept cookies, download private videos, or work around access restrictions. MP4 quality is capped at the selected height and depends on the available source formats. Save content you own or have permission to download.

The Docker build and a real YouTube download still need to be verified on your host; Docker and FFmpeg were unavailable in the build workspace.
