# Stokvel Forecasting Platform

A multi-tenant Flask app that gives every South African stokvel (informal
savings group) the record-keeping, transparency, and forward planning that
a bank account alone doesn't provide — group membership, a shared ledger,
live statistical forecasting per member, and admin-controlled payouts, all
isolated per group and backed by a real database instead of a spreadsheet.

## The problem

Stokvels move an estimated R50+ billion a year in South Africa, and an
estimated 1 in 4 adults belongs to one. Structurally, though, most stokvels
are still run the way they were forty years ago: a treasurer's notebook, a
WhatsApp group, and a spreadsheet that only one person understands. That
creates real, recurring problems:

- **No shared source of truth.** Members have to trust the treasurer's word
  on who's paid, who hasn't, and what the group's balance actually is —
  there's no record they can check themselves.
- **Disputes are hard to resolve.** When a member disputes a contribution
  or a payout, "check the notebook" isn't a great audit trail, and there's
  no record of who approved what, or when.
- **No way to see trouble coming.** A member who's quietly missed two
  contributions in a row looks the same as one who's on track, right up
  until the group needs the money and it isn't there.
- **Payouts rely on manual coordination.** Rotation order, approval
  thresholds, and "has everyone agreed" tend to live in someone's head or
  a chat thread, not in a system that enforces them.
- **Onboarding a new member is manual.** Someone has to explain the rules,
  add them to every group chat, and manually back-fill their history.

This app addresses each of those directly: a shared, per-group ledger that
every member can see; role-based admin controls with an audit log for every
state change; a live forecast per member that flags irregular contribution
patterns before they become a shortfall; a configurable withdrawal-approval
workflow instead of an ad-hoc group decision; and a role-aware onboarding
flow plus an in-app assistant so new members and admins aren't left to
figure out the rules on their own.

## Features

- **Accounts & groups** — sign up/log in with hashed passwords, create a
  stokvel group or join one with an invite code, switch between groups you
  belong to
- **Per-group data isolation** — every route checks your membership in the
  active group before showing anything; there's no way to view another
  group's data via URL manipulation
- **Roles** — group admins can invite/remove members, regenerate the invite
  code, and upload/reset data; regular members get read-only dashboards
  plus the ability to contribute and request withdrawals
- **Group Overview** — total balance/contributions/withdrawals, balance
  growth per member, category & region breakdown
- **Member Forecast** — a live Holt-Winters forecast (damped additive
  trend) fit fresh on each member's own contribution/withdrawal history,
  with a 95% confidence band and an adjustable horizon. A widening band is
  a visible early signal that a member's contributions have become
  irregular, well before it shows up as a shortfall
- **Model Accuracy** — a live train/holdout backtest (RMSE, MAE, MAPE) per
  member, so you can see how reliable the forecast actually is for a given
  member's pattern instead of trusting it blindly
- **Regional View** — Cape Town vs Durban contributions, withdrawals,
  balance spread, and contribution frequency
- **Manual ledger** — a member can submit a contribution or withdrawal for
  admin confirmation, or an admin can back-fill an entry directly; every
  entry recalculates that member's running balance and is excluded from
  forecasting until the group's next explicit retrain, so a late edit never
  silently changes a forecast an admin hasn't reviewed
- **Bring your own data** — group admins can upload replacement CSVs from
  the Data Source tab, or reset to the bundled sample dataset
- **Group & notification settings** — admins set contribution amount/
  frequency, payout/rotation rules, and how many admin approvals a
  withdrawal needs; every member sets their own notification preferences
- **Role-aware onboarding** — a first-run tour with member and admin-only
  slides, replayable from Settings, plus a server-side admin checklist on
  Overview ("invite your first member," "upload your first transaction")
  that persists across devices
- **AI assistant** — a floating chat widget, 100% knowledge-based: a
  curated knowledge base (`src/knowledge_base.py`, TF-IDF retrieval, zero
  extra dependencies) covering both "how this app works" and stokvel
  financial best practice, plus the current group's live balance/
  contribution numbers, both retrieved fresh per question. There is no
  external AI provider, no API key, and no network call involved — it's
  pure local retrieval, every time, out of the box
- **Payments (PayFast)** — members contribute via PayFast's hosted
  checkout; confirmation is webhook-driven (PayFast's ITN), never trusted
  on browser redirect, and idempotent against duplicate webhooks. Runs
  against PayFast's public sandbox by default — no real credentials needed
  to try it
- **Withdrawals & approvals** — a member requests a withdrawal; it needs N
  admin approvals (configurable per group, with a higher threshold above a
  configurable amount) before an admin marks it paid. Every state change —
  request, approval, rejection, payout — is written to an audit log

## Quick Start

### Local Development

```bash
# Install dependencies
pip install -r requirements.txt

# Run locally (Flask development server)
python app.py
# Access: http://localhost:5000
```

### Docker Development

```bash
# Build image
docker build -t stokvel-forecasting .

# Run container
docker run -d -p 5000:5000 \
  -v $(pwd)/data:/app/data \
  -e ANVIL_SECRET_KEY=your-secret-key \
  stokvel-forecasting
```

### Docker Compose

```bash
# Development (with hot-reload)
docker-compose up

# Production
docker-compose -f docker-compose.prod.yml up -d
```

### First run

Visit `/auth/signup` to create an account, then either **create a group**
(you become its admin, and it's seeded with sample data) or **join one**
with an invite code from an existing admin. Every dashboard page then
operates on your active group — switch groups any time from the sidebar
if you belong to more than one.

## Project Structure

```
.
├── src/
│   ├── models.py                # SQLAlchemy models: User, Group, GroupMembership, Transaction, HistoricalForecast, ...
│   ├── forms.py                 # WTForms (auth, groups, settings, upload) — gives every POST CSRF protection
│   ├── extensions.py            # Flask-Login + Flask-WTF CSRFProtect singletons
│   ├── auth_routes.py           # Signup / login / logout
│   ├── group_routes.py          # Create / join / switch stokvel groups
│   ├── group_access.py          # @group_required / @admin_required authorization decorators
│   ├── members_routes.py        # Member pre-registration, invite claiming, custom fields
│   ├── settings_routes.py       # Profile, password, group settings, membership management
│   ├── transactions_routes.py   # Transaction listing and manual-entry review
│   ├── manual_ledger.py         # Manual/admin-confirmed entries and running-balance recalculation
│   ├── payments.py              # PayFast signature/config helpers
│   ├── payments_routes.py       # Contribute (PayFast checkout), withdrawal requests & approvals
│   ├── data_loader.py           # Per-group data access (SQLite), CSV validation & import
│   ├── forecasting.py           # Holt-Winters forecasting engine + train/holdout backtesting
│   ├── accuracy_view.py         # Model Accuracy page data assembly
│   ├── charts.py                # Themed Plotly figure builders
│   ├── assistant.py             # Knowledge-based AI assistant reply logic
│   ├── assistant_routes.py      # Assistant chat/history/notifications endpoints
│   ├── knowledge_base.py        # TF-IDF knowledge base the assistant retrieves from
│   ├── onboarding.py            # Server-side admin onboarding checklist logic
│   ├── onboarding_routes.py     # Onboarding checklist step/dismiss endpoints
│   └── migrations.py            # Lightweight SQLite schema migrations run at startup
├── templates/                   # Jinja2 templates (ledger UI), incl. auth/ and groups/
├── static/css/style.css         # Visual identity
├── data/                        # SQLite DB lives here (volume mount)
│   └── samples/                 # Pristine sample CSVs used to seed new groups / "reset to sample"
├── tests/test_app.py            # pytest suite (auth + group-scoping + forecasting)
├── docs/ONBOARDING_NOTES.md     # Design notes for the role-aware onboarding flow
├── app.py                       # Flask entry point / app factory
├── Dockerfile                   # Multi-stage production build
├── docker-compose.yml           # Development compose config
├── docker-compose.prod.yml      # Production compose config
├── entrypoint.sh                # Container entrypoint (fixes data-volume ownership, then execs gunicorn)
├── requirements.txt / requirements-dev.txt
└── .dockerignore
```

## Environment Variables

**Development**
```bash
ANVIL_SECRET_KEY=dev-secret-key-change-in-production
PYTHONUNBUFFERED=1
PYTHONDONTWRITEBYTECODE=1
```

**Production** — see `.env.production.example`:
```bash
ANVIL_SECRET_KEY=<strong-random-secret>
FLASK_ENV=production
DEBUG=False
PORT=5000

# Optional — defaults to PayFast's public sandbox credentials
PAYFAST_SANDBOX=true
PAYFAST_MERCHANT_ID=<your-merchant-id>
PAYFAST_MERCHANT_KEY=<your-merchant-key>
PAYFAST_PASSPHRASE=<your-passphrase>
```

## Data

All data lives in a single SQLite database at `data/app.db`, scoped by
`group_id`:

| Table | Description |
|-------|--------------|
| `users` | Accounts — email, hashed password, name |
| `groups` | Stokvel groups — name, region, invite code |
| `group_members` | Membership + role (`admin` / `member`) per user per group |
| `transactions` | 2026 transaction-level data: contribution/withdrawal/balance per member, scoped to a group |
| `historical_forecasts` | 2024–2025 historical per-member forecast data, region, category, scoped to a group |

When a new group is created it's seeded from the bundled sample CSVs in
`data/samples/`; a group admin can replace that with their own CSVs from the
Data Source tab, or reset back to the sample data, at any time — both
actions only ever touch that group's own rows.

## Forecasting model

| Model | Library | Notes |
|-------|---------|-------|
| **Holt-Winters (ETS)** | `statsmodels.tsa.holtwinters.ExponentialSmoothing` | Damped additive trend, fit live per member |

An earlier version of this app also fit an auto-tuned ARIMA model
alongside Holt-Winters for comparison. It was removed: Holt-Winters alone
was already accurate and fast on this kind of series, and running a second
model on every request doubled the CPU/memory cost of every forecast and
accuracy check for comparison numbers nobody was acting on. The
`historical_forecasts` table still carries a column for it (populated from
before the removal) purely for that older data's own record.

Accuracy is computed via a live train/holdout backtest (the last few points
held out and predicted) rather than replaying numbers stored in a CSV, so
the **Model Accuracy** page reflects the model actually running in this
app, on that member's actual current data.

## Security

- ✅ Non-root user (`stokvel:stokvel`) in the container
- ✅ Multi-stage Docker build (no build tools in the runtime image)
- ✅ Secrets via environment variables, never baked into the image
- ✅ Health check endpoint (`/healthz`) for automatic recovery
- ✅ Resource limits (configurable in `docker-compose.prod.yml`)
- ✅ Upload size capped at 8 MB; CSVs are column-validated before use
- ✅ Passwords hashed with `werkzeug.security` (PBKDF2), never stored or
  logged in plaintext
- ✅ CSRF protection on every POST endpoint (Flask-WTF)
- ✅ Group membership re-checked against the database on every request —
  no cross-group data access via URL manipulation, ever
- ✅ Every withdrawal request, approval, rejection, and payout is written
  to an audit log
- ✅ PayFast payment confirmation is driven entirely by the signed webhook
  (ITN), never trusted from the browser redirect, and idempotent against
  duplicate deliveries

## Performance

| Metric | Value | Notes |
|--------|-------|-------|
| Gunicorn workers | 1 | Keeps SQLite writes (uploads, membership changes) single-writer |
| Memory limit | 2 GB (prod) | Adjustable in `docker-compose.prod.yml` |
| CPU limit | 2 cores (prod) | Adjustable |
| Health check | 30s interval | Tunable |

## Tech stack

- **App/UI:** Flask, Jinja2
- **Auth:** Flask-Login, werkzeug password hashing
- **Forms/CSRF:** Flask-WTF
- **Database:** SQLite via Flask-SQLAlchemy (users, groups, memberships,
  transactions, historical forecasts, caches, audit log)
- **Charts:** Plotly (client-rendered, interactive)
- **Forecasting:** statsmodels (Holt-Winters / ETS)
- **Data:** pandas
- **AI assistant:** hand-rolled TF-IDF retrieval over a local knowledge
  base (`numpy` only — no external AI provider or API key)
- **Deployment:** Docker / docker-compose, or plain Python + gunicorn

## Deployment

The image binds to `0.0.0.0:5000` and includes a healthcheck at
`/healthz`, so it runs as-is on Render, Railway, Fly.io, any AWS/GCP/Azure
container service, or a VM with Docker:

```bash
docker build -t stokvel-forecasting .
docker run -d -p 5000:5000 -v stokvel-data:/app/data \
  -e ANVIL_SECRET_KEY=your-secret stokvel-forecasting
```

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit changes (`git commit -am 'Add feature'`)
4. Push to branch (`git push origin feature/my-feature`)
5. Run the test suite (`pytest tests/`) before opening a PR
6. Open a Pull Request

## License

MIT
