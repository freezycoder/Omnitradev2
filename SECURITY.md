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

## Public-release checks

Run `python3 scripts/check_public_repo.py` before publishing. The CI workflow
runs the same check for every pull request and push to `main`.

If a credential reaches Git history, removing it in a later commit is not
enough. Revoke or rotate it first, then rewrite the affected history before
making the repository public.
