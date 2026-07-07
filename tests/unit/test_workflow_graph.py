# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     https://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Guards the workflow graph wiring.

These caught nothing before, which is how a duplicate (from, to) edge shipped:
importing ``root_agent`` makes ADK validate the whole graph, so an invalid graph
fails at import time here.
"""

import os
import tempfile

from app.agent import (
    DEFAULT_TARGET_HTML,
    MAX_HEAL_ATTEMPTS,
    _resolve_target,
    root_agent,
)


def _edges():
    return list(root_agent.edges)


def test_graph_constructs():
    """If ADK's graph validation fails, this import-level access raises."""
    assert root_agent.name == "root_agent"
    assert len(_edges()) > 0


def test_no_duplicate_from_to_pairs():
    """ADK forbids two edges sharing the same (from_node, to_node)."""
    pairs = [(id(e.from_node), id(e.to_node)) for e in _edges()]
    assert len(pairs) == len(set(pairs)), "duplicate (from, to) edge in workflow"


def test_terminal_routes_present():
    """Self-heal loop must expose success, retry (loop) and giveup (cap) exits."""
    routes = {getattr(e, "route", None) for e in _edges()}
    routes = {r for r in routes if isinstance(r, str)}
    for required in ("clean", "flagged", "violations", "remediating", "success", "retry", "giveup"):
        assert required in routes, f"missing route: {required}"


def test_retry_cap_is_positive_int():
    assert isinstance(MAX_HEAL_ATTEMPTS, int)
    assert MAX_HEAL_ATTEMPTS >= 1


def test_resolve_target_defaults_to_mock_app():
    assert _resolve_target("just a commit message")[0] == DEFAULT_TARGET_HTML
    assert _resolve_target("")[0] == DEFAULT_TARGET_HTML
    assert _resolve_target("/nonexistent/page.html")[0] == DEFAULT_TARGET_HTML


def test_resolve_target_uses_explicit_existing_html():
    with tempfile.TemporaryDirectory() as d:
        p = os.path.join(d, "page.html")
        with open(p, "w", encoding="utf-8") as f:
            f.write("<html></html>")
        assert _resolve_target(p)[0] == os.path.abspath(p)
