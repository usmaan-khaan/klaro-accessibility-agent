# Share Klaro with a temporary public link (tunnel)

This exposes the agent running on your own machine at a public HTTPS URL, for as long as
you leave it running. No cloud account, no standing cost. The heal step still calls Gemini,
so it uses your local Google credential and bills per heal — keep the link private and stop
it when you're done.

You need two terminals, both open the whole time.

## Terminal 1 — start Klaro
```bash
cd <path>\accessibility-shield
uv run playwright install --with-deps chromium   # once
gcloud auth application-default login            # so the heal step can call Gemini
uv run python -m app.ambient_service             # serves http://127.0.0.1:8080
```
Leave it running.

## Terminal 2 — open the tunnel

### Option A — Cloudflare Tunnel (recommended: free, no signup)
Install once (Windows):
```bash
winget install --id Cloudflare.cloudflared
```
Then:
```bash
cloudflared tunnel --url http://localhost:8080
```
It prints a line like `https://random-words.trycloudflare.com`. That is your shareable link.

### Option B — ngrok (needs a free account + authtoken)
```bash
winget install --id Ngrok.Ngrok
ngrok config add-authtoken <your-token>     # once, from dashboard.ngrok.com
ngrok http 8080
```
Copy the `https://....ngrok-free.app` URL it shows.

## Share it
Send the printed HTTPS URL. The person opens it, clicks Run audit, reviews the diff, and
approves — the full agent runs on your machine. To stop sharing, press Ctrl+C in Terminal 2
(or both). The URL dies immediately.

## Things to know
- Your computer must stay on and both terminals open for the link to work.
- A Cloudflare quick-tunnel URL is new each time you start it (fine for a one-off share).
- Behind a tunnel, all visitors look like one local IP, so the per-minute rate limit acts as a
  single global cap. Keep `RATE_LIMIT_PER_MIN` modest (e.g., 15) since every heal is billed to you.
- Don't post the link publicly; share it directly with the person checking the prototype.
