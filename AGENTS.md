# Nexpent Agent Guide

## Setup
- Backend: `cd backend && pip install -r requirements.txt`
- Frontend: `cd frontend && npm install`
- Run both locally from repo root: `./run.sh`
- Backend defaults to PostgreSQL via `DATABASE_URL`; use a dedicated test database or SQLite URL for tests.

## Test And Lint
- Backend unit/integration tests: `PYTHONPATH=backend pytest backend/tests`
- Backend syntax smoke check: `python -m compileall backend`
- Frontend lint: `cd frontend && npm run lint`
- Frontend production build: `cd frontend && npm run build`

## Architecture
- Existing stack is FastAPI + SQLAlchemy + PostgreSQL on the backend and Vite + React + TypeScript on the frontend.
- Keep legacy expense/income routes working; new financial-advisor functionality lives behind `/api/...` REST endpoints.
- Financial flow: bank/mock/csv/receipt/manual input -> transaction normalization -> database -> exact calculation service -> Cloudflare LLM advice -> dashboard/reports.
- Bank providers live under `backend/providers/banking`; every real provider must implement the same interface and must never collect bank usernames or passwords.
- OCR providers live under `backend/providers/ocr`; mock OCR is acceptable when external credentials are absent.

## Coding Rules
- Do exact financial calculations in backend code, preferably `backend/services/calculation_service.py`; never ask the LLM to calculate totals.
- Store all transaction amounts signed: positive is income, negative is expense.
- Every transaction must include currency, country, source, and date.
- Keep Cloudflare LLM secrets server-side only and read them from environment variables.
- Encrypt provider tokens with `services/encryption_service.py`.
- Validate request bodies with Pydantic models and enforce user ownership in every query.
- Add audit logs for important financial actions.
- Prefer small routers/services that match the current FastAPI style rather than introducing a new framework layout.

