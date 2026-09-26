# Fonts

Self-hosted rather than loaded from Google Fonts. Production serves a
`default-src 'self'` CSP, which blocks fonts.googleapis.com outright — the site
silently rendered in the fallback stack until these were moved here. Serving them
ourselves keeps the policy strict, removes two third-party round trips from every
page load, and lets the service worker cache them for the offline shell.

These are the exact `woff2` files Google serves, unmodified.

## What's here

| File | Family | Subset |
|---|---|---|
| `bricolage-grotesque-latin.woff2` | Bricolage Grotesque, variable `wght 500..800` | latin |
| `bricolage-grotesque-latin-ext.woff2` | ″ | latin-ext |
| `hanken-grotesk-latin.woff2` | Hanken Grotesk, variable `wght 400..700` | latin |
| `hanken-grotesk-latin-ext.woff2` | ″ | latin-ext |

**Do not drop the `latin-ext` subsets.** `₹` is U+20B9, which falls inside
`U+20AD-20C0` — that range is in latin-ext, not latin. Without it the rupee sign
falls back to a system face and sits visibly wrong next to Bricolage digits in the
amount column.

(Hanken Grotesk has no ₹ glyph in any subset, so body-text rupees already fall
back. Amounts use `--font-display`, i.e. Bricolage, which does have it.)

## Licence

Both families are licensed under the SIL Open Font License 1.1. The OFL requires
the licence text to travel with the fonts, not merely a link to it, so the full
text of each sits beside them:

| Family | Copyright | Licence |
|---|---|---|
| Bricolage Grotesque | 2022 The Bricolage Grotesque Project Authors ([source](https://github.com/ateliertriay/bricolage)) | `OFL-BricolageGrotesque.txt` |
| Hanken Grotesk | 2021 The Hanken Grotesk Project Authors ([source](https://github.com/marcologous/hanken-grotesk)) | `OFL-HankenGrotesk.txt` |

Keep those files here if the fonts stay. Deleting them while redistributing the
`woff2` files would put this repository out of compliance.

## Replacing them

The `@font-face` rules, including the `unicode-range` values that decide which
subset a browser fetches, live in `static/css/src/app.css`. Re-download with the
same subsets and ranges, or the ranges will not match the files and glyphs will
go missing in ways that are hard to spot.
