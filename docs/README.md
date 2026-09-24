# Bookinator project resources

These public-facing materials reuse the small, static corporate-resource system developed for PD Doseinator. They are deliberately separate from the local manuscript application and can be hosted beneath `inator.com`, `book.inator.com`, or any static path.

Start at [`presentations/index.html`](presentations/index.html).

## Included

- `briefs/one-pager.html` — printable product overview
- `pitch-authors-editors/` — 16-slide, 20-minute audience deck and presenter view
- `briefs/elevator-pitches.html` — short and audience-specific descriptions
- `briefs/wish-list.html` — prioritized things the project should want, and ambitions it should refuse
- `presentations/catalog.json` — machine-readable resource catalog

## Presenting the deck

- Right arrow, Page Down, or Space: next slide
- Left arrow or Page Up: previous slide
- Home / End: first / last slide
- `N`: open presenter notes
- `F`: full screen

Serve the repository over HTTP rather than opening files directly so module imports and the catalog request work. From the project root, `./bin/serve` is sufficient; then open `/docs/presentations/` on the displayed local URL. The Bookinator server exposes only the public `web/` and `docs/` trees; project data remains outside the static routes.

## Hosting

The resource index resolves its Application link two directories upward. For a separate resources host, set the `bookinator-app-url` meta tag in `presentations/index.html` to an absolute application URL.
