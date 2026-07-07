# Klaro — Autonomous UI-Vision QA & Self-Healing Accessibility Agent

**Subtitle:** An agent that opens your page in a real browser, finds the accessibility bugs that never throw an error, fixes them with Gemini, asks a human to sign off, and then re-checks its own work.

**Track:** Agents for Good (Digital Inclusion / Accessibility)

## The problem

A lot of accessibility bugs are invisible to the people shipping them. An image with no `alt`, an input with no label, a `<div role="popup">` that no screen reader understands, grey text on a slightly different grey. None of these throw an error. The build passes, the console is clean, and the page goes live broken for the people who depend on a screen reader or a keyboard.

Manual accessibility QA catches this, but it's slow and it's the first thing dropped when a deadline hits. So the bugs pile up. In the US alone there were thousands of ADA web lawsuits last year, most of them aimed at e-commerce, and a big share of the defendants had already paid for an "accessibility widget" that didn't actually fix the code. The need is real, and the lazy fixes don't work.

## Why this needs an agent

You can't solve this with one model call. Fixing an accessibility bug is a loop: look at the rendered page, decide what's actually wrong, change the markup, and then check whether the change worked. A plain LLM can't see a rendered page, and a linter can't fix anything. An agent that uses tools and runs that loop can, and a human still gets to approve what ships.

That loop, look → decide → fix → verify, with a person in the middle, is what Klaro does.

## What it is

Klaro is a Google ADK `Workflow`: a state graph where each node is one small, testable job and the edges are chosen by what each node returns.

- **Security screen.** Every incoming request is checked for prompt-injection and scrubbed of leaked secrets (SSH keys, database URLs, Google API keys) before anything else runs. An injection attempt ends the run.
- **Browser capture.** Headless Chromium (via Playwright) loads the page, takes desktop and mobile screenshots, and measures colour contrast in the live DOM using the WCAG luminance math, with the correct 3:1 threshold for large text so headings don't get flagged by mistake.
- **Visual audit.** It parses the DOM for missing `alt`, unlabeled inputs, and invalid ARIA roles, folds in the contrast findings, and routes either "approved" (nothing wrong) or "violations."
- **Gemini remediation.** An `LlmAgent` rewrites the HTML to fix the issues without touching the layout.
- **Human approval gate.** The agent pauses here. It sends the violation list, both screenshots, and a before/after diff to the dashboard and waits for a person to approve or reject.
- **Verify.** It writes the fix, re-audits the healed file, and routes success, retry, or give-up. The retry loop is capped by `MAX_HEAL_ATTEMPTS`, so it can't spin forever.

State (violations, screenshots, the healed HTML, the attempt counter) travels through the ADK context. Sessions live in Vertex/in-memory session state, no separate database.

## What you actually do with it

A FastAPI service exposes `/trigger` and `/resume` and serves the review dashboard. You type a change, hit Run audit, and you get the list of issues with severity icons, the desktop and mobile renders, and a colour-highlighted diff of the proposed fix. Approve it and the agent applies the change, re-audits, and tells you it verified clean. There's a built-in library of 20 seeded violations served five at a time, with a Next 5 button, so you can watch the loop run over and over.

## Course concepts used

I leaned on more than the three the rubric asks for:

- Agent / ADK: the `Workflow` graph plus a Gemini `LlmAgent`.
- Human-in-the-loop: a `RequestInput` interrupt and `/resume`, with session state on Vertex and no DB.
- Security: the injection screen, secret redaction, Semgrep, and pre-commit hooks.
- Agent skills / Agents CLI: the project is scaffolded with `agents-cli` and ships an `accessibility-auditor` skill.
- Deployability: Terraform and Vertex Agent Runtime, with OpenTelemetry tracing.
- Antigravity: the whole thing was vibe-coded in Google Antigravity.
- Browser tool use: the headless browser is the agent's eyes.

## What I got wrong first, and fixed

The first version "verified" a fix by shelling out to the test suite. That proved nothing about the page, and in a deployed container with no test runner it would fail forever and loop. I tore that out and made verify do the honest thing: re-run the actual audit on the healed file, with a retry cap and a give-up path. I also fixed the contrast check to respect the large-text threshold, and tightened the injection filter so extra spaces or line breaks don't slip past it.

There's a real limit worth saying out loud: automated tools, this one included, catch roughly a third to a half of WCAG issues. The rest (is the alt text meaningful? does the keyboard order make sense?) needs human judgment. That's exactly why the approval gate exists, and why I'd plug a mature engine like axe-core in behind Klaro rather than pretend the rule set is complete.

## Where it goes next

Wrap the browser layer as a proper MCP server, add keyboard and focus-trap checks, crawl multiple routes and logged-in states, and run it on pull-request diffs so it comments fixes inline. The shape is already right for that.

## Links

- Code: <ADD PUBLIC GITHUB REPO URL>
- Video: <ADD YOUTUBE URL>
- Run it: `agents-cli install`, then `uv run playwright install --with-deps chromium`, then `uv run python -m app.ambient_service`, then open http://127.0.0.1:8080/
