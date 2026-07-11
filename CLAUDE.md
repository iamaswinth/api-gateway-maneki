# CLAUDE.md

This file provides guidance to Claude Code when working with code in this repository.

## What this is

`api-gateway` is the auth + tenant-config + token-issuance boundary for Maneki. It sits in
front of the ingestion service (`Firecrawl-scraper-ingestion`, :8000) and the voice runtime
(`voice runtime gateway`) — neither of which enforces caller auth themselves. This service:

1. Owns `tenant_config` (provider selection, `allowed_origin`, `published`, rate limits) —
   the single source of truth other services read.
2. Authenticates dashboard owners (Clerk JWT) for tenant CRUD and forwards their
   authenticated requests to the ingestion service's owner-facing endpoints.
3. Issues LiveKit access tokens to anonymous widget visitors, gated by `Origin` validation,
   `published` state, and per-tenant concurrency/rate limits — enforced *before* any
   STT/LLM/TTS cost is incurred.
4. Exposes an internal, service-token-protected endpoint the voice runtime will eventually
   call at session start instead of its local JSON fixture
   (`voice_runtime/tenant_config.py`).

**Three distinct trust levels — owner JWT (Clerk), anonymous widget, and internal service
token — must never share a token type or a validation code path.** A credential from one
trust level satisfying another's check is the worst failure mode for this service.

## Model routing reminder

- **Planning**: use **Fable**.
- **Writing/editing code**: switch to **Sonnet** or **Opus** first.

## Dev server rule

**Never leave background servers running after testing.** Stop `uvicorn` and
`docker compose` (Redis) before ending a task.

```powershell
docker compose up -d          # Redis
uvicorn app.main:app --reload --port 8080
```

## Stack

- FastAPI app in `app/`, own git repo (sibling to the other two Maneki services — see the
  workspace root `../CLAUDE.md`).
- Postgres: same instance as the other services in dev, own schema (`gateway`, via
  `search_path` — see `app/db.py`). No shared tables with ingestion or voice_runtime.
- Redis: new to the Maneki stack, used only here (`app/redis_client.py`) for rate-limit
  windows and active-session counts.
- Clerk for owner auth (JWKS-verified JWT, `app/auth/clerk.py`).
- `livekit-api` server SDK for `AccessToken`/`RoomAgentDispatch` minting and webhook
  signature verification.

## Integration contracts — do not drift

- Internal endpoint response shape must match `voice_runtime/fixtures/tenant_config.json`
  exactly: `tenant_id, stt_provider, tts_provider, tts_voice_id, llm_tier_default,
  allowed_origin, max_concurrent_sessions, published, greeting?`.
- Widget tokens must include a `RoomConfiguration` with `RoomAgentDispatch(agent_name=
  "voice-runtime", metadata=json.dumps({"tenant_id", "visitor_id", "page_url", "email"}))`
  — these are exactly the keys `voice_runtime/agent.py::_job_metadata` reads. Without this
  dispatch config, no agent joins the room.
- Ingestion wire models (`ScrapeRequest`, `SalesScriptRecord`, etc.) are duplicated here
  rather than imported — matches how ingestion and voice_runtime already treat each other.

## Running things

```powershell
docker compose up -d
uvicorn app.main:app --reload --port 8080
pytest
```

Docs at `http://localhost:8080/docs`.
