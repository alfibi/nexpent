# Database

The preferred database is PostgreSQL through SQLAlchemy.

Core financial tables:

- `users`
- `bank_accounts`
- `provider_tokens`
- `transactions`
- `receipts`
- `receipt_items`
- `budgets`
- `savings_goals`
- `categories`
- `ai_insights`
- `ai_chat_messages`
- `monthly_summaries`
- `audit_logs`

Important indexes and constraints:

- `transactions.user_id + date`
- `transactions.user_id + category`
- `transactions.account_id`
- `transactions.provider_transaction_id`
- `transactions.receipt_id`
- unique `transactions.user_id + fingerprint` for duplicate prevention
- `bank_accounts.user_id`
- `provider_tokens.user_id + provider`

Provider tokens are encrypted before storage. Bank passwords are never requested or stored.

