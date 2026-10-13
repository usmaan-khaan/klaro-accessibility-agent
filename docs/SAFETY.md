# Audit and repair boundaries

Klaro audits offline session copies. The bundled demo is always available. To audit
a local HTML file, an administrator must set `AUDIT_ALLOWED_DIR` to a directory
containing only files intended for audit. Resolved paths outside that directory,
including symlink escapes, are rejected. Source files are never overwritten.

Live URL audits are disabled. Re-enabling them requires an isolated egress service
that prevents access to internal networks, cloud metadata, redirects to internal
addresses, and unsafe subrequests. A URL regex or DNS lookup alone is insufficient.

Target scripts and service workers are disabled during capture and verification.
All target network requests are blocked. Consequently external CSS, images, and
JavaScript-driven UI are not evaluated. Inline CSS and data images work; this is an
offline HTML audit, not a complete audit of a live application.

Each audit receives its own target and screenshots. A random session capability is
required to resume an audit. Keep that token private. Approval accepts exactly
`approve` or `reject`, checks the pending interrupt, and serializes resumes for that
session. In-memory sessions and capabilities require one application process and
are lost on restart; a distributed authenticated session store is required before
multi-worker deployment. Public triggers still need production authentication and
durable per-user quotas; the existing IP limiter is only a demo safeguard.

Model output must preserve markup structure, text, scripts, URLs, and unrelated
attributes. Only accessibility attributes and literal foreground/background colors
can change. New labels must be expressed as `aria-label` attributes. Model output
that violates this boundary is rejected rather than applied. Regex screening and
secret redaction are limited defenses, not a comprehensive injection/secret detector.

The browser verifies both desktop and mobile candidates before atomically replacing
the session copy. Browser failure, residual issues, or changed source content keeps
the original. A successful repair saves `original.html` alongside the repaired
session file. Downloaded HTML may retain scripts from the original document; the
dashboard previews it in a sandbox with network access blocked by CSP.

Passing the implemented checks does not establish WCAG conformance. Manual keyboard,
screen-reader, content, and interaction review remains necessary. A mature audit
engine such as axe-core is a future improvement.

Run regression checks with:

```bash
uv run pytest tests/unit tests/test_agent.py
uv run pre-commit run --all-files
```

The tests cover approval semantics, path boundaries, repair validation, rollback,
browser failure, control names, and the workflow graph. A live Gemini end-to-end
test requires Google credentials and should be run before deployment.
