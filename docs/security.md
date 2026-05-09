# Security

- Passwords are hashed with Passlib; new `/api/auth/register` users use Argon2.
- Auth supports HTTP-only cookies and bearer JWTs.
- Provider tokens are encrypted at rest with `TOKEN_ENCRYPTION_KEY` or the JWT secret-derived development key.
- Secrets must only be configured in environment variables.
- Request bodies are validated with Pydantic.
- Financial routes filter by `current_user.id` and enforce ownership checks.
- Important actions write `audit_logs`.
- The Cloudflare LLM receives only necessary financial summaries or cleaned receipt text, never credentials or provider tokens.
- Rate limiting and basic security headers are enabled in FastAPI middleware.

