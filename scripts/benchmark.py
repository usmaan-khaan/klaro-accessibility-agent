# Copyright 2026 Google LLC
# Klaro performance benchmark — detection rate across the seeded case library.
#
# Detection (alt / label / ARIA role) runs with NO API key and NO browser.
# Contrast is detected at runtime by the headless browser, so it is reported
# separately. Heal-success additionally needs Gemini credentials (see --help).
"""Run:  uv run python scripts/benchmark.py"""

from collections import Counter

from app.agent import run_visual_audit
from app.case_library import BATCH_SIZE, CASES

# Each case index maps to the violation its builder plants (see case_library).
PLANTED = ["Missing Alt Tag", "Missing Form Label", "Low Color Contrast", "Invalid ARIA Role"]


def main() -> None:
    planted = Counter(PLANTED[i % len(PLANTED)] for i in range(len(CASES)))
    detected: Counter = Counter()

    # Audit each batch page statically (no browser); contrast is excluded here.
    for start in range(0, len(CASES), BATCH_SIZE):
        from app.case_library import build_batch_page

        _msg, _route, state = run_visual_audit(build_batch_page(start), [])
        for v in state["violations"]:
            detected[v["type"]] += 1

    print("Klaro detection benchmark")
    print(f"  cases: {len(CASES)}  |  batches: {len(CASES) // BATCH_SIZE}\n")
    static_types = ["Missing Alt Tag", "Missing Form Label", "Invalid ARIA Role"]
    hit = total = 0
    for t in static_types:
        p, d = planted[t], detected.get(t, 0)
        total += p
        hit += min(d, p)
        print(f"  {t:<20} planted {p:>2}  detected {d:>2}")
    rate = 100 * hit / total if total else 0
    print(f"\n  static detection rate (alt/label/role): {rate:.0f}%  ({hit}/{total})")
    print(f"  {'Low Color Contrast':<20} planted {planted['Low Color Contrast']:>2}  "
          "detected at runtime by the headless browser (not in this static run)")
    print("\n  heal-success rate needs Gemini credentials; run the full workflow via the dashboard to measure it.")


if __name__ == "__main__":
    main()
