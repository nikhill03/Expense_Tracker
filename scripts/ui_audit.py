#!/usr/bin/env python3
"""Automated UI audit for Bahi-Khata.

Drives a real Chromium against a running server and checks the things that are
easy to break and tedious to catch by eye: sideways scrolling on a phone, tap
targets too small for a thumb, form controls with no accessible name, missing
landmarks, JavaScript errors, and the light/dark theme actually flipping.

Usage:
    python app.py &                       # or any host/port
    python scripts/ui_audit.py --base http://127.0.0.1:5001 \
        --email demo@bahikhata.com --password demo123

Exits non-zero if any check fails, so it can gate a commit or a CI job.
"""

from __future__ import annotations

import argparse
import sys
from dataclasses import dataclass, field

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover - dependency hint
    sys.exit(
        "playwright is not installed. Run: pip install playwright && playwright install chromium"
    )


# Pages to audit. The signed-in ones need the login step to have worked.
PUBLIC_PAGES = ["/", "/login", "/register", "/terms", "/privacy"]
PRIVATE_PAGES = [
    "/profile",
    "/expenses",
    "/events",
    "/budgets",
    "/expenses/add",
    "/quick?text=Rs.340.00+debited+from+A%2Fc+XX4417+via+UPI",
]

# Common phone, small phone, tablet, desktop.
WIDTHS = [360, 390, 768, 1280]

# WCAG 2.5.8 asks for 24px; 44px is the long-standing touch guidance and the
# size this design is built to.
MIN_TAP = 44


@dataclass
class Report:
    failures: list[str] = field(default_factory=list)
    checks: int = 0

    def check(self, ok: bool, message: str) -> None:
        self.checks += 1
        if not ok:
            self.failures.append(message)


# ------------------------------------------------------------------ #
# Individual checks, run in the page                                  #
# ------------------------------------------------------------------ #

OVERFLOW_JS = """
() => {
  const d = document.documentElement;
  const overflowing = [...document.querySelectorAll('body *')]
    .filter(el => {
      const r = el.getBoundingClientRect();
      return r.width > 0 && (r.right > d.clientWidth + 1 || r.left < -1);
    })
    .slice(0, 5)
    .map(el => el.tagName.toLowerCase() + '.' + (el.className || '').toString().split(' ')[0]);
  return { scroll: d.scrollWidth, client: d.clientWidth, culprits: overflowing };
}
"""

TAP_TARGETS_JS = """
(min) => {
  const sel = 'a[href], button, input:not([type=hidden]), select, textarea, summary, [role=button]';
  return [...document.querySelectorAll(sel)]
    .filter(el => {
      const s = getComputedStyle(el);
      if (s.display === 'none' || s.visibility === 'hidden' || s.opacity === '0') return false;
      const r = el.getBoundingClientRect();
      if (r.width === 0 && r.height === 0) return false;
      // A visually-hidden skip link is 1x1 by design and grows on focus.
      if (r.width <= 1 && r.height <= 1) return false;
      // An inline link inside a paragraph is exempt: it flows with the text.
      const inProse = el.tagName === 'A' && el.closest('p, li, summary, legend');
      return !inProse && r.height < min;
    })
    .slice(0, 8)
    .map(el => {
      const r = el.getBoundingClientRect();
      const name = (el.getAttribute('aria-label') || el.textContent || el.name || '').trim().slice(0, 28);
      return `${el.tagName.toLowerCase()}[${name}] ${Math.round(r.width)}x${Math.round(r.height)}`;
    });
}
"""

ACCESSIBLE_NAMES_JS = """
() => {
  const controls = [...document.querySelectorAll('input:not([type=hidden]), select, textarea, button')];
  return controls
    .filter(el => {
      if (el.getAttribute('aria-label') || el.getAttribute('aria-labelledby')) return false;
      if (el.id && document.querySelector(`label[for="${CSS.escape(el.id)}"]`)) return false;
      if (el.closest('label')) return false;
      if (el.tagName === 'BUTTON' && el.textContent.trim()) return false;
      if (el.type === 'submit' && el.value) return false;
      return true;
    })
    .slice(0, 8)
    .map(el => el.tagName.toLowerCase() + '[name=' + (el.name || el.type || '?') + ']');
}
"""

STRUCTURE_JS = """
() => ({
  h1: document.querySelectorAll('h1').length,
  main: document.querySelectorAll('main').length,
  nav: document.querySelectorAll('nav').length,
  lang: document.documentElement.lang,
  title: document.title,
  viewport: (document.querySelector('meta[name=viewport]') || {}).content || '',
  // A heading that jumps a level (h1 -> h3) is a real screen-reader problem.
  headingJumps: (() => {
    const levels = [...document.querySelectorAll('h1,h2,h3,h4,h5,h6')]
      .map(h => Number(h.tagName[1]));
    let jumps = 0;
    for (let i = 1; i < levels.length; i++) if (levels[i] - levels[i - 1] > 1) jumps++;
    return jumps;
  })(),
})
"""


CONTRAST_JS = """
() => {
  const parse = c => c.match(/[\\d.]+/g).slice(0, 3).map(Number);
  const lum = ([r, g, b]) => {
    const f = v => { v /= 255; return v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4; };
    const [R, G, B] = [f(r), f(g), f(b)];
    return 0.2126 * R + 0.7152 * G + 0.0722 * B;
  };
  const cs = getComputedStyle(document.body);
  const [a, b] = [lum(parse(cs.color)), lum(parse(cs.backgroundColor))].sort((x, y) => y - x);
  return Math.round(((a + 0.05) / (b + 0.05)) * 100) / 100;
}
"""


def audit_page(page, path: str, width: int, report: Report, errors: list[str]) -> None:
    label = f"{path} @{width}px"

    overflow = page.evaluate(OVERFLOW_JS)
    report.check(
        overflow["scroll"] <= overflow["client"] + 1,
        f"{label}: page scrolls sideways ({overflow['scroll']}>{overflow['client']}) "
        f"— {', '.join(overflow['culprits']) or 'unknown element'}",
    )

    if width <= 430:  # tap targets only matter where there's a thumb
        small = page.evaluate(TAP_TARGETS_JS, MIN_TAP)
        report.check(
            not small, f"{label}: tap targets under {MIN_TAP}px — {'; '.join(small)}"
        )

    unnamed = page.evaluate(ACCESSIBLE_NAMES_JS)
    report.check(
        not unnamed,
        f"{label}: form controls with no accessible name — {', '.join(unnamed)}",
    )

    s = page.evaluate(STRUCTURE_JS)
    report.check(s["h1"] == 1, f"{label}: expected exactly one <h1>, found {s['h1']}")
    report.check(
        s["main"] == 1, f"{label}: expected a single <main> landmark, found {s['main']}"
    )
    report.check(bool(s["lang"]), f"{label}: <html> has no lang attribute")
    report.check(bool(s["title"]), f"{label}: page has no <title>")
    report.check(
        "width=device-width" in s["viewport"],
        f"{label}: viewport meta is not responsive",
    )
    report.check(
        s["headingJumps"] == 0,
        f"{label}: heading levels skip a step ({s['headingJumps']}x)",
    )

    report.check(not errors, f"{label}: JavaScript errors — {'; '.join(errors[:3])}")
    errors.clear()


def audit_theme(page, report: Report) -> None:
    """Both themes must actually render, and the choice must stick."""
    light_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")

    # dispatch_event rather than click: some headless environments never fire
    # requestAnimationFrame, and Playwright's actionability check waits on it.
    page.dispatch_event("#theme-toggle", "click")
    dark_bg = page.evaluate("getComputedStyle(document.body).backgroundColor")
    theme = page.evaluate("document.documentElement.dataset.theme")

    report.check(light_bg != dark_bg, f"theme toggle did not change the background ({light_bg})")
    report.check(theme == "dark", f"theme toggle left data-theme as {theme!r}")
    report.check(
        page.evaluate("document.getElementById('theme-toggle').getAttribute('aria-pressed')") == "true",
        "theme toggle did not update aria-pressed",
    )

    page.reload(wait_until="load")
    report.check(
        page.evaluate("document.documentElement.dataset.theme") == "dark",
        "chosen theme was not remembered across a reload",
    )

    # Text must stay readable in the dark theme, not just render.
    ratio = page.evaluate(CONTRAST_JS)
    report.check(ratio >= 4.5, f"dark theme body text contrast is {ratio}:1, below 4.5:1")

    page.dispatch_event("#theme-toggle", "click")


def audit_quick_sheet(page, report: Report) -> None:
    """The sheet is the app's main interaction; it must open, focus and close."""
    report.check(
        page.locator("#quick-sheet").count() == 1,
        "the quick-add sheet is missing from this page",
    )
    report.check(
        page.locator("button[popovertarget=quick-sheet]").count() >= 1,
        "nothing on the page opens the quick-add sheet",
    )

    page.evaluate("document.getElementById('quick-sheet').showPopover()")
    report.check(
        page.evaluate("document.getElementById('quick-sheet').matches(':popover-open')"),
        "the quick-add sheet did not open",
    )

    page.evaluate("document.querySelector('#quick-sheet [data-quick-amount]').focus()")
    report.check(
        page.evaluate("document.activeElement.name") == "amount",
        "the amount field in the sheet cannot take focus",
    )

    page.keyboard.press("Escape")
    report.check(
        not page.evaluate("document.getElementById('quick-sheet').matches(':popover-open')"),
        "Escape did not close the quick-add sheet",
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://127.0.0.1:5001")
    ap.add_argument("--email", default="demo@bahikhata.com")
    ap.add_argument("--password", default="demo123")
    args = ap.parse_args()

    report = Report()

    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            for width in WIDTHS:
                ctx = browser.new_context(viewport={"width": width, "height": 900})
                page = ctx.new_page()

                errors: list[str] = []
                page.on("pageerror", lambda e: errors.append(str(e)))
                page.on(
                    "console",
                    lambda m: errors.append(m.text) if m.type == "error" else None,
                )

                for path in PUBLIC_PAGES:
                    page.goto(args.base + path, wait_until="load")
                    audit_page(page, path, width, report, errors)

                page.goto(args.base + "/login", wait_until="load")
                page.fill("#email", args.email)
                page.fill("#password", args.password)
                page.click("button[type=submit]")
                page.wait_for_url(args.base + "/profile", timeout=10_000)

                signed_in = "/profile" in page.url
                report.check(signed_in, f"could not sign in as {args.email}")

                if signed_in:
                    for path in PRIVATE_PAGES:
                        page.goto(args.base + path, wait_until="load")
                        audit_page(page, path, width, report, errors)

                    page.goto(args.base + "/profile", wait_until="load")
                    audit_theme(page, report)
                    audit_quick_sheet(page, report)

                ctx.close()
        finally:
            browser.close()

    print(f"\n{report.checks} checks run at widths {WIDTHS}")
    if report.failures:
        print(f"{len(report.failures)} failed:\n")
        for f in report.failures:
            print(f"  ✗ {f}")
        return 1

    print("all passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
