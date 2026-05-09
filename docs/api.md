# API

Primary APIs are under `/api`.

- Auth: `POST /api/auth/register`, `POST /api/auth/login`, `POST /api/auth/logout`, `GET /api/auth/me`, `DELETE /api/auth/me/data`
- Banks: `POST /api/banks/connect`, `GET /api/banks/accounts`, `POST /api/banks/sync`, `POST /api/banks/refresh-balances`, `DELETE /api/banks/{accountId}`
- Transactions: `GET /api/transactions`, `POST /api/transactions`, `POST /api/transactions/import-csv`, `GET /api/transactions/{id}`, `PUT /api/transactions/{id}`, `DELETE /api/transactions/{id}`
- Receipts: `POST /api/receipts/upload`, `GET /api/receipts`, `GET /api/receipts/{id}`, `PUT /api/receipts/{id}/correct`
- Receipt extraction: `POST /extract-receipt` for PaddleOCR -> LLM -> validated expense JSON
- Budgets: `POST /api/budgets`, `GET /api/budgets`, `PUT /api/budgets/{id}`, `DELETE /api/budgets/{id}`
- Goals: `POST /api/goals`, `GET /api/goals`, `PUT /api/goals/{id}`, `DELETE /api/goals/{id}`
- Analytics: `GET /api/analytics/monthly-summary`, `GET /api/analytics/category-spending`, `GET /api/analytics/trends`
- AI: `POST /api/ai/chat`, `POST /api/ai/analyze-spending`, `POST /api/ai/categorize-transaction`, `POST /api/ai/extract-receipt`, `GET /api/ai/insights`

Legacy routes such as `/dashboard`, `/budgets`, `/add-expense`, and `/add-income` remain for the existing UI.
