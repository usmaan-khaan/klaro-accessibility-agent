# Klaro — video script (aim for ~4:45, hard limit 5:00)

Screen recording with voiceover, uploaded to YouTube. Reset the demo first:
`copy app\mock_app\index.broken.html app\mock_app\index.html`, then start the server.

## 0:00–0:30 — the hook
On screen: the broken page (grey-on-grey text, an image with no alt, an unlabeled field).
Say: "Most accessibility bugs don't throw an error. No alt text, no label, bad contrast. The
build passes, nobody notices, and the page ships broken for people using a screen reader. This
is Klaro. It finds those bugs, fixes them, and checks its own work, with you approving the fix."

## 0:30–1:00 — why an agent
On screen: a simple loop animation, look → decide → fix → verify.
Say: "One model call can't do this. You have to see the rendered page, decide what's wrong,
change the code, and confirm the change actually worked. That's a loop, and that's what an agent
is good at. The human stays in the loop for the part that needs judgment."

## 1:00–1:50 — architecture
On screen: the architecture diagram (docs/architecture.png).
Say: "Klaro is a Google ADK workflow. A security node screens the input. A browser node opens the
page in headless Chromium and grabs desktop and mobile shots plus contrast. An audit node checks
the DOM against WCAG. If something's broken, Gemini rewrites the markup, the run pauses for your
approval, and a verify node re-audits the fix and retries until it passes."

## 1:50–3:50 — the demo (let this breathe)
On screen: the dashboard at localhost:8080.
1. Click Run audit. The scan bar runs.
2. Show the six violations with their icons, and the desktop and mobile screenshots.
3. Open the diff. Point at the green lines: alt added, label added, contrast fixed, role corrected.
4. Click Approve. Status flips to "Healed," and it says the fix verified clean.
5. Click Next 5. A fresh batch loads and runs.
Say, while clicking: "Here are the issues it found, here's the page it saw, and here's the fix it's
proposing. I approve it, and watch, it doesn't just apply the change, it re-audits to prove the
page is actually clean now. That re-check is the part most tools skip."

## 3:50–4:30 — how it's built
On screen: quick cuts of agent.py, the node functions, and Antigravity.
Say: "I built this by vibe coding in Google Antigravity. ADK runs the workflow, Gemini does the
remediation, Playwright is the browser, and a FastAPI dashboard handles the human approval. Semgrep
and pre-commit keep secrets out, there are unit tests including one that fails if the graph is
invalid, and it deploys to Vertex Agent Runtime with Terraform."

## 4:30–4:45 — close
On screen: Klaro logo, "Audit. Repair. Verify."
Say: "Klaro makes accessibility automatic on every change, without taking the human out of the
decision. That's an agent for good."

## checklist before recording
- [ ] Demo reset to the broken page
- [ ] Server running, GCP auth done so the heal works on camera
- [ ] 1080p, slow cursor
- [ ] One architecture slide
- [ ] Under 5:00, then upload and paste the link into the writeup and Media Gallery
