# Deploy on Render Free

Render builds the included Dockerfile on its servers. You do not need to install Docker on your computer.

1. Upload the latest project contents to your GitHub repository. Ensure `render.yaml`, `Dockerfile`, and `server.py` are at the root.
2. In Render, choose **New → Blueprint**, connect GitHub, and select the repository.
3. Render reads `render.yaml`. Confirm that the service shows the **Free** plan, then deploy the Blueprint. No database or paid disk is needed.
4. Wait for the build to finish and the service to become **Live**. This build installs the download tools automatically.
5. Open the service's `https://….onrender.com` address. Sign in with username `admin`. The generated password is in the service's **Environment → APP_PASSWORD** value. Keep it private; do not copy it into GitHub or the website's JavaScript.
6. Try a short video or clip and save the finished file to your computer. The backend already serves the full website, so this verifies it before adding Vercel.

## Connect the Vercel website

1. In the Render service's **Environment** settings, add `PUBLIC_ORIGIN` with your exact production Vercel origin, for example `https://pocket-example.vercel.app`. No trailing slash. Save and redeploy.
2. In GitHub, copy the contents of `vercel.backend.example.json` into `vercel.json`.
3. Replace all three `https://YOUR-BACKEND-DOMAIN` values with the Render service's HTTPS origin.
4. Commit the change and wait for Vercel to redeploy.
5. Open the Vercel production URL and sign in using the same `admin` credentials.

See `DEPLOY.md` for the complete GitHub and Vercel instructions. Only configure the origin you actually use; preview URLs differ from your production URL.

## Free-tier behavior

- Render sleeps after 15 minutes without inbound traffic. Waking it may take about a minute. Opening the Render URL directly first can help when checking a sleeping backend.
- Downloaded files and history disappear when Render restarts, redeploys, or sleeps. The app's 24-hour retention is a maximum, not a persistence guarantee on this plan. Save completed files promptly.
- Video encoding is demanding; start with short 360p or 720p clips. This app has not yet been tested on a live Render Free instance.
- Free services have bandwidth and compute limits, and Render can suspend a service that initiates unusually high external traffic. This setup is for a small experiment, not unlimited downloading.
- If YouTube rejects the cloud server's IP, deploying successfully will not resolve that restriction.
- If a file fails to transfer through Vercel, use the Render website's Download button directly. Vercel proxies have a 120-second request timeout.

Official references: https://render.com/docs/free and https://render.com/docs/blueprint-spec.
