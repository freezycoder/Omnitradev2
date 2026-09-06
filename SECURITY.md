# Security policy

## Reporting a vulnerability

Do not include vulnerability details, credentials, or private data in a public
issue. Use GitHub's **Security → Report a vulnerability** flow when it is
available. If private reporting is unavailable, contact the repository
maintainer privately through the maintainer's GitHub profile before sharing
technical details.

Include the affected component, impact, reproduction steps, and the smallest
safe proof of concept. Never test against a deployment you do not own or have
explicit permission to assess.

## Deployment defaults

- Hosted API processes are read-only unless `OMNITRADE_WRITE_MODE=local` is
  explicitly set.
- `OMNITRADE_CORS_ORIGINS` must contain exact trusted frontend origins.
- API keys belong in the hosting provider's secret store or
  `~/.config/omnitrade/secrets.env`, never in Git or `NEXT_PUBLIC_*` variables.
- Demo and stale scans keep research output visible but disable actionable
  trade states and price levels.

## Security checklist

This product is a local research terminal plus an optional read-only hosted API.
It has **no user accounts**, so password hashing, session cookies, and login
CAPTCHAs do not apply. The controls below match the stack that actually exists.

| Control | Status |
|---|---|
| Hide API keys | Provider keys stay in `~/.config/omnitrade/secrets.env` or the host secret store. The desktop Settings panel never receives the raw key (hint + last 4 only). Never put keys in `NEXT_PUBLIC_*`. |
| Purge secrets from Git | Tracked history has no live keys. `python3 scripts/check_public_repo.py` scans the tree and full Git history. If a real key is ever committed, revoke it, then rewrite history before publishing. |
| Expose only the public DB key | Not applicable. The database is a local SQLite file, not a hosted Postgres/Supabase project. |
| Enable row-level security | Not applicable. Single-user local SQLite; no multi-tenant Data API. |
| Encrypt sensitive data | `secrets.env` is written with mode `0600` on Unix. Use the OS user account / FileVault / BitLocker for disk encryption. |
| Enforce server-side auth | Hosted API is read-only unless `OMNITRADE_WRITE_MODE=local`. Optional `OMNITRADE_WRITE_TOKEN` is required on POST/DELETE when set. |
| Lock record access | Mutations are denied in read-only mode (403). There are no per-user records to isolate. |
| Block field tampering | Watchlist and performance-log bodies are Pydantic-validated (ticker charset, strategy/status enums, numeric bounds). |
| Secure session cookies | Not applicable (no login sessions). |
| Hash passwords | Not applicable (no passwords). |
| Rate limit login | Not applicable. Mutation and Refresh Scan routes are rate-limited per client IP. |
| Add bot protection | Rate limits plus production security headers. Put a WAF/CDN in front of any public host. |
| Parameterize queries | SQLite repositories bind user values with `?` / named parameters. |
| Validate all input | FastAPI/Pydantic on mutations; data_mode/universe/ticker checks on reads. |
| Escape user content | React escapes text. External links must be `http`/`https` (`safeHttpUrl`). |
| Restrict file uploads | No upload endpoints. |
| Trim API responses | Production 500s omit exception text; OpenAPI `/docs` is disabled in production; Kronos `service_url` is not returned. |
| Add security headers | FastAPI middleware + Next.js `headers()` (nosniff, DENY framing, referrer, CSP, HSTS on HTTPS). |
| Force HTTPS | Production requests with `X-Forwarded-Proto: http` redirect to HTTPS. Localhost stays HTTP. |
| Scan dependencies | Dependabot plus CI `pip-audit` and `npm audit`. |

## Public-release checks

Run `python3 scripts/check_public_repo.py` before publishing. The CI workflow
runs the same check for every pull request and push to `main`.

If a credential reaches Git history, removing it in a later commit is not
enough. Revoke or rotate it first, then rewrite the affected history before
making the repository public.
