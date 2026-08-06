# Per-page onboarding tours

## What shipped

Every major authenticated page now has a short, animated guided tour:

| Page | Storage key | Steps highlight |
|------|-------------|-----------------|
| Groups hub | `ledger_page_tour_v1_groups` | Hub paths, sample onboarding, create group |
| Overview | `ledger_page_tour_v1_overview` | Header, stat cards, growth chart |
| Empty ledger | `ledger_page_tour_v1_empty` | Empty copy + admin CTAs |
| Transactions | `ledger_page_tour_v1_transactions` | Submit form, status list |
| Forecast | `ledger_page_tour_v1_forecast` | Controls, horizon, chart |
| Payments | `ledger_page_tour_v1_payments` | Contribute, withdraw |
| Data Source | `ledger_page_tour_v1_data` | Source status, upload |
| Settings | `ledger_page_tour_v1_settings` | Head, members, help panel |

## Behaviour

- **First visit**: tour opens after a short delay (waits if the global welcome modal is still open).
- **Dismissal**: Skip, Done, or overlay click → `localStorage` flag so it does not auto-reopen.
- **Replay**: floating **Page guide** button (bottom-right) on any page that defines a tour; Settings also has **Replay page guide**.
- **Spotlight**: target element is highlighted with a marigold ring; the card animates to sit near the target.
- **Reduced motion**: transitions are disabled when `prefers-reduced-motion` is set.

## Sample data → onboarding mode

The old “Preview with sample data” path is reframed as **Onboarding mode**:

- Groups hub card: “Onboarding with sample data”
- Banner pill: “Onboarding mode”
- Exit CTA: “Exit onboarding”
- Flash copy points users at per-page guides

This keeps the sample dataset as the way to *see* charts and tables while learning, instead of staring at empty states.

## Implementation notes

- Shell: `templates/_page_tour.html`
- Engine: `startPageTour` / `replayPageTour` in `templates/base.html`
- Styles: `.page-tour-*` in `static/css/style.css`
- Page configs live in each template’s `{% block scripts %}`
- Targets use `data-tour="..."` attributes on key panels
