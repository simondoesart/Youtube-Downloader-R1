# GitHub → Vercel

This package is ready to upload to GitHub. Vercel can publish the website immediately. **Working downloads also require an always-on Docker host with persistent storage.** This application's Python server, background queue, FFmpeg, and local file storage do not run as-is on Vercel Functions.

## 1. Upload to GitHub

1. Unzip `youtube-downloader.zip`.
2. On GitHub, create a new repository named `youtube-downloader`. A private repository is fine.
3. Select **uploading an existing file** (or **Add file → Upload files**).
4. Upload the **contents** of the extracted `youtube-downloader` folder, preserving the `static` and `tests` folders. Do not upload the ZIP itself.
5. Commit the upload. `vercel.json`, `server.py`, and `README.md` must be at the repository root, not inside another folder.

Do not upload `.env`, downloaded media, or passwords. The included `.env.example` contains placeholders only. Browser uploads can omit hidden files; GitHub Desktop or Git can include the `.gitignore` and `.env.example` files reliably.

Optional terminal route (replace YOUR-USERNAME; create an empty GitHub repository first):

```sh
cd /path/to/youtube-downloader
git init -b main
git add .
git commit -m "Add Pocket YouTube downloader"
git remote add origin https://github.com/YOUR-USERNAME/youtube-downloader.git
git push -u origin main
```

## 2. Publish the website on Vercel

1. In Vercel, choose **Add New → Project** and import the GitHub repository.
2. Use **Other** as the framework preset.
3. Keep **Root Directory** at the repository root (`.`).
4. Leave the install and build commands empty; the supplied `vercel.json` sets these and uses `static` as the output directory.
5. Click **Deploy**.

The website now has a public Vercel URL. It will show “Download server not connected” until you complete step 3. No Vercel secrets or environment variables are needed for this configuration. Never put your password in JavaScript or `vercel.json`.

## 3. Connect the download server

You need a Docker-capable server with persistent disk space and a public HTTPS address, such as `https://downloads.your-domain.com`. The computer running the local preview is not automatically accessible to Vercel; `localhost` will not work as a backend URL.

On that server:

1. Clone this same repository.
2. Copy `.env.example` to `.env`.
3. Set `APP_PASSWORD` to a long, unique password.
4. Set `PUBLIC_ORIGIN` to your exact production Vercel origin, for example `https://pocket-example.vercel.app`. Include `https://`, omit the trailing slash. If you later add a custom domain, update this value to the domain you use.
5. Run `docker compose up -d --build`.
6. Configure an HTTPS reverse proxy and domain as described in `README.md`. The Docker port stays bound to localhost when the reverse proxy runs directly on that server.
7. Open the backend HTTPS address directly and verify you can sign in with username `admin` and your password. Test an actual video download here before connecting Vercel.

In your GitHub repository:

1. Replace the contents of `vercel.json` with `vercel.backend.example.json`.
2. Replace **all three** `https://YOUR-BACKEND-DOMAIN` values with your real backend HTTPS origin. Do not include a path or credentials.
3. Commit the change. Vercel redeploys the project.
4. Open the production Vercel URL and sign in with username `admin` and the backend password.

The root-page rewrite lets the backend request a browser login before the page loads. The API and file rewrites keep requests on the website's origin. Static CSS and JavaScript come from Vercel. Both hosts should run the same source revision. Backend changes require pulling the repository and rebuilding Docker on your server; Vercel redeployments do not update that server.

Only the origin configured in `PUBLIC_ORIGIN` is explicitly allowed through the reverse proxy. Preview deployments with different origins may reject new downloads; use the production URL for functional testing.

## Limits and checks

- Test sign-in, a video download, an audio download, and saving the completed file after deploying. The Vercel integration has not been tested against a live deployment in this workspace.
- Download preparation continues on your Docker host; API requests only queue work and read progress.
- Vercel external rewrites have a 120-second proxy timeout. If a large file transfer fails through Vercel, open the backend HTTPS address and download directly there. File transfers through Vercel also consume Vercel data transfer allowance.
- Keep the backend password enabled even if the repository is private. Repository privacy does not protect a deployed website.
- Files expire after 24 hours. YouTube may block some server IPs; deploying successfully does not guarantee every video is downloadable.

If you prefer one hosting service, the Docker server already serves the entire website. You can use its HTTPS URL directly without Vercel.

References: [Vercel external rewrites](https://vercel.com/docs/routing/rewrites), [Vercel proxy limits](https://vercel.com/docs/limits#proxied-request-timeout), [Vercel Functions limits](https://vercel.com/docs/functions/limitations).
