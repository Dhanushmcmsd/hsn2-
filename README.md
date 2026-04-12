# HSN Classifier — Production System

## Quick Start

```bash
cp .env.example .env
# Edit .env — set API_KEY, ADMIN_API_KEY, SECRET_KEY, POSTGRES_PASSWORD

# Docker (recommended — PostgreSQL + Redis + Prometheus + Grafana)
docker-compose up --build

# Local dev (SQLite, no Redis required)
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

## Frontend (Next.js)

```bash
cd hsn-frontend
npm install
cp .env.local.example .env.local
npm run dev   # → http://localhost:3000
```

## Security Checklist (before going live)

| Variable | Requirement |
|----------|-------------|
| `SECRET_KEY` | Must not be `change-me`. Generate: `python -c "import secrets; print(secrets.token_hex(32))"` |
| `API_KEY` | Must not be `dev-api-key`. |
| `ADMIN_API_KEY` | Separate from `API_KEY`. Must not be the same value. |
| `POSTGRES_PASSWORD` | Must be set. Docker-compose will refuse to start without it. |
| `DATABASE_URL` | Must be PostgreSQL URL in production. SQLite rejected. |
| `CORS_ORIGINS` | Explicit origin list. Wildcard `*` rejected in production. |

## API Endpoints

### Auth (JWT)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/auth/register` | Register new user |
| `POST` | `/auth/login` | Login → JWT tokens |
| `POST` | `/auth/refresh` | Refresh access token |
| `GET` | `/auth/me` | Current user info |

### User-facing (require `X-API-Key` header)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/predict` | Classify product → HSN code |
| `GET` | `/health` | Health check |
| `GET` | `/review/pending` | Predictions needing review |
| `POST` | `/review/resolve` | Resolve a review |

### Admin (require `X-API-Key` with ADMIN key)
| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/admin/retrain/check` | Trigger retraining |
| `GET` | `/admin/retrain/versions` | Model versions |
| `POST` | `/admin/dataset/reload` | Reload dataset |
| `GET` | `/admin/dataset/integrity` | Verify dataset |
| `GET` | `/admin/circuit-breakers` | Circuit breaker states |

## Deployment

### Backend → Railway
```bash
npm install -g @railway/cli
railway login && railway init
railway add postgresql && railway add redis
railway variables set APP_ENV=production
railway variables set SECRET_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
railway variables set API_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
railway variables set ADMIN_API_KEY=$(python -c "import secrets; print(secrets.token_hex(32))")
railway variables set CORS_ORIGINS=https://your-app.vercel.app
railway up
```

### Frontend → Vercel
```bash
cd hsn-frontend
npx vercel
# Set NEXT_PUBLIC_API_URL=https://your-backend.railway.app in Vercel dashboard
npx vercel --prod
```

## Running Tests
```bash
pip install -r requirements.txt
pytest -v --tb=short
```

## Infrastructure
```
api:8000 ──▶ postgres:5432
     └──▶ redis:6379
     └──▶ prometheus:9090 ──▶ grafana:3001
hsn-frontend:3000 ──▶ api:8000 (JWT + X-API-Key)
```

## Project Structure
```
hsn_app_fixed/
├── app/
│   ├── main.py              FastAPI app + startup validators
│   ├── config.py            Pydantic settings
│   ├── routes/
│   │   ├── auth.py          POST /auth/* (JWT register/login/refresh)  ← NEW
│   │   ├── predict.py       POST /predict
│   │   ├── review.py        GET+POST /review
│   │   ├── health.py        GET /health
│   │   └── admin.py         GET+POST /admin/*
│   ├── services/
│   │   ├── dataset.py       HSN CSV loader
│   │   ├── matcher.py       FAISS + keyword hybrid matcher
│   │   └── confidence.py    Scoring + labels
│   ├── models/
│   │   ├── database.py      SQLAlchemy: User, Prediction, ApiKey  ← User added
│   │   └── schemas.py       Pydantic request/response schemas
│   └── utils/
│       ├── auth.py          X-API-Key dependency
│       ├── cache.py         Redis async cache
│       ├── rate_limit.py    Sliding-window rate limiter
│       ├── metrics.py       Prometheus metrics
│       ├── circuit_breaker.py  Circuit breaker pattern
│       ├── scheduler.py     APScheduler jobs
│       ├── fallback.py      Fallback responses
│       ├── key_rotation.py  API key rotation
│       └── logging.py       structlog JSON logging
├── alembic/                 DB migrations
├── data/
│   └── hsn_codes.csv        34 HSN codes (extend with full dataset)
├── tests/                   pytest test suite
├── monitoring/              Prometheus + Grafana config
├── load_test/               Locust load test
├── hsn-frontend/            Next.js 14 SaaS frontend  ← NEW
├── Dockerfile
├── docker-compose.yml       (Grafana on 3001, PostgreSQL env-secured)
├── entrypoint.sh            (dynamic workers + max-requests guard)
├── requirements.txt         (+ python-jose, bcrypt, email-validator)
└── railway.json             Railway deployment config  ← NEW
```
