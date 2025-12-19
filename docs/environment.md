# Environment variables

This project uses environment variables for configuration. For local development, copy `.env.example` to `.env`.

## Core services
- `DATABASE_URL`
  - PostgreSQL connection string.
  - Example: `postgresql+asyncpg://ragnex:ragnex@localhost:5432/ragnex`
- `REDIS_URL`
  - Redis connection string.
  - Example: `redis://localhost:6379/0`
- `OPENSEARCH_URL`
  - OpenSearch (or Elasticsearch) base URL.
  - Example: `http://localhost:9200`

## Object storage (S3-compatible)
- `S3_ENDPOINT_URL`
  - S3-compatible endpoint.
  - Example: `http://localhost:9000`
- `S3_ACCESS_KEY`
  - Access key for S3-compatible storage.
- `S3_SECRET_KEY`
  - Secret key for S3-compatible storage.
- `S3_BUCKET`
  - Bucket name to store uploaded documents.
- `S3_REGION`
  - Region identifier (mostly informational for MinIO).

## Security
- `JWT_SECRET`
  - Secret used to sign JWTs.
- `JWT_ALGORITHM`
  - JWT signing algorithm (default planned: `HS256`).
- `ACCESS_TOKEN_EXPIRES_MINUTES`
  - Access token TTL.
- `REFRESH_TOKEN_EXPIRES_DAYS`
  - Refresh token TTL.

## Limits
- `MAX_UPLOAD_MB`
  - Max upload size (MB).

## Optional provider config (future work)
- `OPENAI_API_KEY`
- `OLLAMA_BASE_URL`
- `VLLM_BASE_URL`
