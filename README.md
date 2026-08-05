# Stokvel Forecasting Platform

A multi-tenant Flask app — live statistical forecasting (Holt-Winters
exponential smoothing & auto-tuned ARIMA, `statsmodels` + `pmdarima`) over
stokvel (savings-group) member contributions, withdrawals, and balances.
Users sign up, create or join a stokvel group via invite code, and every
page operates on their group's own data — fully isolated in SQLite.
Packaged the way a production Flask service should be: multi-stage Docker
build, health checks, non-root user, and three CI/CD workflows.

## Features

- **Accounts & groups** — sign up/log in (hashed passwords via Flask-Login), create a stokvel group or join one with an invite code, switch between groups you belong to
- **Per-group data isolation** — every route checks your membership in the active group before showing anything; there's no way to view another group's data via URL manipulation
- **Roles** — group admins can invite/remove members, regenerate the invite code, and upload/reset data; regular members get read-only dashboards
- **Group Overview** — total balance/contributions/withdrawals, balance growth per member, category & region breakdown
- **Member Forecast** — live Holt-Winters/auto-tuned-ARIMA forecast with a 95% confidence band, adjustable horizon and model, contributions vs withdrawals
- **Model Accuracy** — live train/holdout backtest comparing Holt-Winters vs ARIMA (RMSE, MAE, MAPE) per member, plus the stored 2024–2025 historical comparison
- **Regional View** — Cape Town vs Durban contributions, withdrawals, balance spread, and contribution frequency
- **Bring your own data** — group admins can upload replacement CSVs from the Data Source tab, or reset to the bundled sample dataset
- **Group & notification settings** — admins set contribution amount/frequency, payout/rotation rules, and how many admin approvals a withdrawal needs; every member sets their own notification preferences (`/settings`)
- **AI assistant** — a floating chat widget, 100% knowledge-based: a curated knowledge base (`src/knowledge_base.py`, TF-IDF retrieval, zero extra dependencies) covering both "how this app works" and stokvel financial best practice, plus the current group's live balance/contribution numbers, both retrieved fresh per question. There is no external AI provider, no API key, and no network call involved — it's pure local retrieval, every time, out of the box.
- **Payments (PayFast)** — members contribute via PayFast's hosted checkout (`/payments`); confirmation is webhook-driven (PayFast's ITN), never trusted on browser redirect, and idempotent against duplicate webhooks. Runs against PayFast's public sandbox by default — no real credentials needed to try it.
- **Withdrawals & approvals** — members request a withdrawal; it needs N admin approvals (configurable per group, with a higher threshold for large amounts) before an admin marks it paid. Every state change is written to an audit log.

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

## CI/CD Workflows

Three automated GitHub Actions workflows ship with this project:

### 1. Docker Build & Push (Docker Hub)
**File:** `.github/workflows/docker-build-push.yml`

Triggers on `push`/`pull_request` to `main`, and manual dispatch. Builds on
every PR (no push); on push to `main`, builds and pushes to Docker Hub
tagged `latest`, the branch name, the git SHA, and semantic version tags
when the commit is tagged.

**Required secrets:** `DOCKERHUB_USERNAME`, `DOCKERHUB_TOKEN` (a Docker Hub
Personal Access Token, not your password).

### 2. GitHub Container Registry (GHCR)
**File:** `.github/workflows/ghcr-build-push.yml`

Triggers on `push` to `main` and manual dispatch. Pushes to `ghcr.io` using
the repo's built-in `GITHUB_TOKEN` — no extra secrets needed.

### 3. Tests
**File:** `.github/workflows/tests.yml`

Triggers on `push`/`pull_request` to `main`/`develop`, and manual dispatch.
Runs a Python 3.12 matrix: flake8 lint, pytest with coverage (uploaded to
Codecov if `CODECOV_TOKEN` is set), then builds the Docker image, runs a
container health check, and reports image size.

## Setting Up Secrets

### Docker Hub
1. Create a Docker Hub account: https://hub.docker.com/signup
2. Account Settings → Security → New Access Token → copy it immediately
3. Repo → Settings → Secrets and variables → Actions → New repository secret
   → add `DOCKERHUB_USERNAME` and `DOCKERHUB_TOKEN`

### GHCR
No setup needed — `secrets.GITHUB_TOKEN` is provided automatically.

## Deployment

```bash
# Docker Hub
docker pull <your-dockerhub-username>/stokvel-forecasting:latest
docker run -d -p 5000:5000 -v stokvel-data:/app/data \
  -e ANVIL_SECRET_KEY=your-secret <your-dockerhub-username>/stokvel-forecasting:latest

# GHCR
docker pull ghcr.io/<your-org>/<your-repo>:latest
docker run -d -p 5000:5000 -v stokvel-data:/app/data \
  -e ANVIL_SECRET_KEY=your-secret ghcr.io/<your-org>/<your-repo>:latest
```

The image binds to `0.0.0.0:5000` and includes a healthcheck at `/healthz`,
so it runs as-is on Render, Railway, Fly.io, any AWS/GCP/Azure container
service, or a VM with Docker.

## Project Structure

```
.
├── .github/workflows/
│   ├── docker-build-push.yml   # Docker Hub build & push
│   ├── ghcr-build-push.yml     # GHCR build & push
│   └── tests.yml                # Lint, test, Docker health check
├── src/
│   ├── models.py                  # SQLAlchemy models: User, Group, GroupMembership, Transaction, HistoricalForecast
│   ├── forms.py                   # WTForms (auth, groups, settings, upload) — gives every POST CSRF protection
│   ├── extensions.py              # Flask-Login + Flask-WTF CSRFProtect singletons
│   ├── auth_routes.py             # Signup / login / logout
│   ├── group_routes.py            # Create / join / switch stokvel groups
│   ├── settings_routes.py         # Profile, password, membership management
│   ├── group_access.py            # @group_required / @admin_required authorization decorators
│   ├── data_loader.py             # Per-group data access (SQLite), CSV validation & import
│   ├── forecasting.py             # Holt-Winters & auto-tuned ARIMA engine, backtesting
│   └── charts.py                  # Themed Plotly figure builders
├── templates/                    # Jinja2 templates (ledger UI), incl. auth/ and groups/
├── static/css/style.css          # Visual identity
├── data/                         # SQLite DB lives here (volume mount)
│   └── samples/                  # Pristine sample CSVs used to seed new groups / "reset to sample"
├── tests/test_app.py             # pytest suite (auth + group-scoping + forecasting)
├── app.py                        # Flask entry point / app factory
├── Dockerfile                    # Multi-stage production build
├── docker-compose.yml            # Development compose config
├── docker-compose.prod.yml       # Production compose config
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
```

## Data

All data now lives in a single SQLite database at `data/app.db` (covered by
the same volume mount the old CSVs used), scoped by `group_id`:

| Table | Description |
|-------|--------------|
| `users` | Accounts — email, hashed password, name |
| `groups` | Stokvel groups — name, region, invite code |
| `group_members` | Membership + role (`admin` / `member`) per user per group |
| `transactions` | 2026 transaction-level data: contribution/withdrawal/balance per member, scoped to a group |
| `historical_forecasts` | 2024–2025 historical per-member forecast, RMSE/MAE/MAPE, region, category, scoped to a group |

When a new group is created it's seeded from the bundled sample CSVs in
`data/samples/`; a group admin can replace that with their own CSVs from the
Data Source tab, or reset back to the sample data, at any time — both
actions only ever touch that group's own rows.

## Forecasting models

| Model | Library | Notes |
|-------|---------|-------|
| **Holt-Winters (ETS)** | `statsmodels.tsa.holtwinters.ExponentialSmoothing` | Damped additive trend, fit live per member |
| **ARIMA** | `statsmodels.tsa.arima.model.ARIMA` + `pmdarima.auto_arima` | Order `(p,d,q)` is auto-tuned per member via a stepwise AIC search, falling back to `(1,1,1)` only if that fails (e.g. a very short series) |

Accuracy is computed via a live train/holdout backtest (last few points
held out) rather than replaying numbers stored in a CSV, so the **Model
Accuracy** page reflects the models actually running in this app.

## Security

- ✅ Non-root user (`stokvel:stokvel`)
- ✅ Multi-stage Docker build (no build tools in the runtime image)
- ✅ Secrets via environment variables, never baked into the image
- ✅ Health check endpoint (`/healthz`) for automatic recovery
- ✅ Resource limits (configurable in `docker-compose.prod.yml`)
- ✅ Upload size capped at 8 MB; CSVs are column-validated before use
- ✅ Passwords hashed with `werkzeug.security` (PBKDF2), never stored or logged in plaintext
- ✅ CSRF protection on every POST endpoint (Flask-WTF)
- ✅ Group membership re-checked against the database on every request — no cross-group data access via URL manipulation, ever

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
- **Database:** SQLite via Flask-SQLAlchemy (users, groups, memberships, transactions, historical forecasts)
- **Charts:** Plotly (client-rendered, interactive)
- **Forecasting:** statsmodels (Holt-Winters, ARIMA), pmdarima (auto-tuned ARIMA order)
- **Data:** pandas
- **Deployment:** Docker / docker-compose, or plain Python + gunicorn

## Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit changes (`git commit -am 'Add feature'`)
4. Push to branch (`git push origin feature/my-feature`)
5. Open a Pull Request

All PRs trigger linting, tests, and a Docker build (no push). Merges to
`main` trigger build-and-push to Docker Hub and GHCR.

## License

MIT
