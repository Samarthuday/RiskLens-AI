# Deployment preparation

The repository includes a Docker image suitable for local use and a Docker Space on Hugging Face. No public deployment is currently configured and this document does not claim a public URL.

## Local Docker

```bash
docker compose up --build
```

The container listens on `0.0.0.0:7860`, runs as a non-root user, and persists SQLite data under the mounted `./data` directory. It starts in evidence-only mode unless a trusted `risklens-causal-v2` model artifact is mounted. This demonstration has no user authentication or per-visitor database isolation; do not expose shared reset/write controls to untrusted concurrent visitors until a session isolation layer is added.

## Hugging Face Spaces

1. Create a new Docker Space and push this repository.
2. Keep the model absent for the public synthetic-only walkthrough, or add a compatible artifact through a private Space storage/mount mechanism permitted by its license.
3. Store the artifact SHA-256 in Space secrets/settings as `RISKLENS_MODEL_SHA256`; set `RISKLENS_MODEL_PATH` to the mounted path. Do not commit model binaries, raw SAML-D, API credentials, or `.env`.
4. Check memory and startup behavior with the exact model build before sharing a URL. The full research dataset is never required at runtime.
5. The local SQLite database is ephemeral on many hosted containers. Use persistent storage or document reset-on-restart behavior before treating cases as durable.

## Remaining production requirements

This demo has no user authentication, role-based authorization, tenant separation, durable managed database, distributed rate limiting, secrets rotation, formal privacy review, or financial service integration. Do not expose it as an operational payment control. A production system would need those controls, model governance, label feedback, deployment rollback, and institution-specific validation.
