# Deploying Klaro as a public, key-backed demo

This hosts the live agent so anyone with the URL can run it. The Gemini credential
stays on the server; visitors never need their own. Two paths.

The hosted default audits isolated copies of the bundled demo. Live URLs are rejected,
and local paths are rejected unless an administrator sets `AUDIT_ALLOWED_DIR`. Browser
scripts and external resources are blocked. The per-IP rate limit
(`RATE_LIMIT_PER_MIN`, default 20) is only a demo safeguard; every heal call bills your
account. See [SAFETY.md](SAFETY.md) for limitations and production requirements.

Never put the key in the repo or in client JavaScript. Use the host's secret manager only.

## Updating the existing Agent Runtime API

To update an existing Agent Runtime deployment, use the source deployment helper.
It exports frozen requirements and includes the Chromium build script. The ordinary
`agents-cli deploy` source package does not include that browser setup.

```bash
uv run python scripts/deploy_runtime.py \
  --project <your-project-id> --region us-east1 \
  --engine projects/<project-number>/locations/us-east1/reasoningEngines/<engine-id>
```

The helper updates only an explicitly named `accessibility-shield` agent. It keeps
existing environment settings and API schemas, uses one worker/instance for session
files, and disables full message capture in telemetry. Agent Runtime exposes an
authenticated API; the dashboard requires the separate Cloud Run deployment below.

## Option A — Google Cloud Run (recommended, NO API key)

Uses the Cloud Run service account + Vertex AI, so there is no key to leak.

```bash
gcloud config set project <your-project-id>

# 1. let the service account call Vertex
PROJECT=<your-project-id>
SA="$(gcloud projects describe $PROJECT --format='value(projectNumber)')-compute@developer.gserviceaccount.com"
gcloud projects add-iam-policy-binding $PROJECT \
  --member="serviceAccount:$SA" --role="roles/aiplatform.user"

# 2. build + deploy from this folder (uses the Dockerfile)
gcloud run deploy klaro \
  --source . \
  --region us-central1 \
  --allow-unauthenticated \
  --memory 2Gi --cpu 2 --timeout 300 \
  --max-instances 1 \
  --set-env-vars GOOGLE_GENAI_USE_VERTEXAI=True,GOOGLE_CLOUD_LOCATION=global,RATE_LIMIT_PER_MIN=20
```

Cloud Run prints a public `https://klaro-...run.app` URL. Share that. (2 GiB / 2 vCPU and a 300 s
timeout give headless Chromium + the heal call room to run.)

## Option B — Render or Railway (API key as a secret)

For these, switch off Vertex and use a Gemini API key.

1. Push the repo to GitHub.
2. Create a new **Web Service**, choose **Docker** (it picks up the `Dockerfile`).
3. Set environment variables (as secrets):
   - `GOOGLE_GENAI_USE_VERTEXAI=False`
   - `GOOGLE_API_KEY=<your Gemini API key>`
   - `GOOGLE_CLOUD_LOCATION=global`
   - `RATE_LIMIT_PER_MIN=20`
4. Deploy. Use the public URL it gives you.

## After deploying

- Open the URL, click **Run audit**, approve a fix — confirm the full loop works on the host.
- Watch billing for the first day; lower `RATE_LIMIT_PER_MIN` if needed.
- For the capstone "Public Project Link," this URL (or the static `docs/demo.html`) both qualify.

## Notes / limits

- The container filesystem is ephemeral; the demo heals an in-container copy of the page, which is
  fine for a demo and resets on restart.
- Use one application process and one instance for this in-memory demo; restarts lose
  pending approvals. Multi-worker hosting requires a shared authenticated session store.
- Before production, add authentication, persistent sessions, workspace expiry/cleanup,
  durable per-user quotas, and a mature accessibility engine. Passing these limited
  checks does not establish WCAG conformance.
