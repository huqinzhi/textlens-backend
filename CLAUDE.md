# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

TextLens is an AI-powered image text editing service. The backend provides:
- OCR recognition via Google Cloud Vision API
- AI image generation via OpenAI GPT-4o / DALL-E
- Credits/subscription system with Stripe payments
- JWT authentication with email, Google OAuth, and Apple Sign In

## Tech Stack

- **Framework**: FastAPI (Python)
- **Database**: PostgreSQL + SQLAlchemy (sync ORM) + Alembic migrations
- **Cache/Queue**: Redis + Celery (async task processing)
- **Storage**: AWS S3 or Cloudflare R2 (configurable via `USE_R2`)
- **External APIs**: Google Cloud Vision, OpenAI, Stripe
- **Config**: Pydantic Settings via `.env` file

## Commands

### Development

```bash
# Start all services (API + Celery + Postgres + Redis)
docker-compose up

# Run API server locally (requires Postgres + Redis running)
uvicorn app.main:app --reload --port 8000

# Run Celery worker
celery -A app.tasks.celery_app worker --loglevel=info

# Run Celery beat (scheduled tasks)
celery -A app.tasks.celery_app beat --loglevel=info
```

### Database Migrations

```bash
# Create a new migration
alembic revision --autogenerate -m "description"

# Apply migrations
alembic upgrade head

# Rollback one step
alembic downgrade -1
```

### Testing

```bash
# Run all tests
pytest

# Run a single test file
pytest tests/unit/test_auth.py

# Run a single test function
pytest tests/unit/test_auth.py::test_register_success

# Run with verbose output
pytest -v
```

### Code Quality

```bash
# Format code
black app/ tests/

# Sort imports
isort app/ tests/
```

## Architecture

### Request Flow

```
HTTP Request
  → CORS Middleware
  → RequestLoggingMiddleware
  → ErrorHandlerMiddleware
  → FastAPI Router (app/features/<feature>/router.py)
  → Service Layer (app/features/<feature>/service.py)
  → DB Models / External Clients
```

### Directory Structure

```
app/
  main.py              # App factory, middleware + router registration
  config.py            # Pydantic Settings (all env vars)
  dependencies.py      # Shared FastAPI dependencies (get_current_user)
  features/            # Business logic by domain
    auth/              # JWT auth, Google/Apple OAuth
    users/             # User profile management
    credits/           # Credits balance, earn/spend transactions
    ocr/               # Image upload + Google Vision OCR
    generation/        # AI image generation (async via Celery)
    history/           # Generation/OCR history
    payments/          # Stripe checkout + webhooks + Apple IAP
  db/
    session.py         # SQLAlchemy engine + get_db() dependency
    models/            # ORM models (user, credit, image, purchase)
    base.py            # DeclarativeBase
  external/            # Third-party API clients
    google_vision.py
    openai_api.py
    s3_client.py
    stripe_api.py
  core/
    security.py        # JWT creation/verification, password hashing
    exceptions.py      # Custom exception classes
    constants.py       # QualityLevel, TaskStatus, credit costs
  tasks/               # Celery tasks
    celery_app.py      # Celery config + beat schedule
    generation_tasks.py
    ocr_tasks.py
    cleanup_tasks.py   # GDPR cleanup, expired image removal
  middleware/
    error_handler.py
    request_logging.py
migrations/            # Alembic migration versions
tests/
  unit/
  integration/
  fixtures/
```

### Feature Module Pattern

Each feature follows the same structure:
- `router.py` — FastAPI route handlers, dependency injection only
- `service.py` — Business logic class (e.g. `AuthService`, `OCRService`)

Services receive a `db: Session` in `__init__` and call external clients directly. There is no separate repository layer.

### Async Generation Flow

AI image generation is asynchronous:
1. `POST /api/v1/generate` → `GenerationService.submit()` creates a `GenerationTask` record and enqueues a Celery task
2. Celery worker (`generation_tasks.py`) calls OpenAI, updates task status
3. Client polls `GET /api/v1/generate/{task_id}` for status

### Credits System

- Users start with `CREDITS_INITIAL_BONUS` (10) credits on registration
- Low-quality generation uses a daily free quota (`FREE_DAILY_LIMIT=3`) before consuming credits
- Credit costs per quality level are defined in `app/core/constants.py` (`QUALITY_CREDITS_MAP`)
- All credit changes are recorded as `CreditTransaction` rows

### Authentication

- JWT access tokens (24h) + refresh tokens (30d) with rolling refresh
- Refresh tokens are stored in DB and blacklisted on logout
- `get_current_user` dependency in `app/dependencies.py` is used across all protected routes

## Code Comment Convention

All methods must have Chinese docstrings following this format:

```python
def method_name(self, param: Type) -> ReturnType:
    """
    方法用途描述

    [param] 参数说明
    返回 ReturnType 返回值说明
    """
```
