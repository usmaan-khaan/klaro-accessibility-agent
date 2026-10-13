#!/bin/bash
set -euo pipefail

# Agent Runtime builds as root. Install the lockfile's Playwright version and
# keep browser binaries in a directory readable by the runtime service user.
export PLAYWRIGHT_BROWSERS_PATH=/opt/klaro-browsers
python -m pip install --no-cache-dir playwright==1.60.0
python -m playwright install --with-deps chromium
chmod -R a+rX /opt/klaro-browsers
