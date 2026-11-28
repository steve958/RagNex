# Deploying RagNex

How to run RagNex for real users with `docker-compose.prod.yml`: secrets, TLS, backups,
and a checklist for going live. Every setting is described in
[configuration.md](configuration.md).

## Secrets

### What is secret and where it lives

| Secret | Where | Who can use it |
|---|---|---|
| `JWT_SECRET` | `.env.prod` | Anyone who has it can sign in as any user. |
| `RAGNEX_ENCRYPTION_KEY` | `.env.prod` | Together with the database or a backup of it, reads workspaces' model API keys. |
| `POSTGRES_PASSWORD` | `.env.prod` | Full access to all data: users, workspaces, chats, and workspace API keys. |
| `MINIO_ROOT_PASSWORD` | `.env.prod` | Full access to every uploaded file. |
| `OPENAI_API_KEY` | `.env.prod` | Model usage billed to you. |
| Workspace model API keys | Postgres, encrypted with `RAGNEX_ENCRYPTION_KEY`; set by workspace owners in Settings | Model usage billed to that workspace's account. |
| User passwords | Postgres, as argon2 hashes | Not recoverable from the database. |
| RagNex API keys | Postgres, as SHA-256 hashes | Shown once when created; not recoverable from the database. |

Keep `.env.prod` out of version control (`.gitignore` already excludes it) and readable
only by the account that runs Docker (`chmod 600 .env.prod`). Anyone who can run `docker`
commands on the host can read these values from the containers (`docker inspect`), so treat
Docker access as access to the secrets.

Workspace model API keys are encrypted in the database with `RAGNEX_ENCRYPTION_KEY`, and the
API never returns them. A database backup alone doesn't reveal them, so **store the
encryption key separately from database backups**, but keep it somewhere safe: losing it
means every workspace owner has to enter their keys again.

### Generating them

```bash
openssl rand -hex 32    # JWT_SECRET (at least 32 bytes; the backend refuses weaker values)
openssl rand -base64 32 # RAGNEX_ENCRYPTION_KEY (exactly 32 bytes, base64)
openssl rand -hex 24    # POSTGRES_PASSWORD, MINIO_ROOT_PASSWORD
```

Use hex (letters and digits only) for `POSTGRES_PASSWORD`: compose puts it inside the
database URL, where characters such as `@`, `:`, `/` or `#` break the connection.

`OPENSEARCH_INITIAL_ADMIN_PASSWORD` is only demanded by the OpenSearch image. It needs upper
and lower case, a digit and a symbol, and must not resemble the user name `admin` (for
example `Ragnex-` followed by `openssl rand -hex 8`); otherwise OpenSearch refuses to start.
RagNex never uses it.

### Rotating secrets

After editing `.env.prod`, apply it with:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

This recreates only the containers whose settings changed.

| Secret | How | Effect |
|---|---|---|
| `JWT_SECRET` | Change it in `.env.prod`, then apply. | Everyone is signed out and logs in again. RagNex API keys keep working: they don't depend on this secret. |
| `POSTGRES_PASSWORD` | Change it in the database **first**, then in `.env.prod`, then apply (see below). | None, if done in this order. Changing only `.env.prod` locks the API out of the database, because Postgres applies `POSTGRES_PASSWORD` only when its volume is first created. |
| `MINIO_ROOT_PASSWORD` | Change it in `.env.prod`, then apply. | MinIO and the backend restart with the new password; uploads are briefly unavailable. |
| `RAGNEX_ENCRYPTION_KEY` | In steps, keeping the old key readable (see below). | None, if done in steps. Replacing it outright makes stored workspace keys unreadable: owners must enter them again. |
| `OPENAI_API_KEY` | Change it in `.env.prod`, then apply. | None. |
| Workspace model API keys | The workspace owner replaces them in Settings. | Takes effect on the next request. |
| A RagNex API key | Create a new key in Settings, switch clients to it, then revoke the old one. | The old key stops working when revoked. |

Changing the Postgres password:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec postgres \
  psql -U ragnex -d ragnex -c "ALTER USER ragnex PASSWORD 'NEW_PASSWORD'"
# then set POSTGRES_PASSWORD=NEW_PASSWORD in .env.prod and apply
```

(Use your `POSTGRES_USER` and `POSTGRES_DB` if you changed them.)

### Rotating the encryption key

1. Generate a new key. In `.env.prod`, move the current key into the list of previous
   keys and set the new one:
   ```bash
   RAGNEX_ENCRYPTION_KEY=NEW_KEY
   RAGNEX_ENCRYPTION_PREVIOUS_KEYS=["OLD_KEY"]
   ```
2. Apply. Stored keys are still readable through the previous key.
3. Re-encrypt them under the new key:
   ```bash
   docker compose -f docker-compose.prod.yml --env-file .env.prod exec api      python -m backend.app.services.stored_secrets reencrypt
   ```
4. Remove the old key (`RAGNEX_ENCRYPTION_PREVIOUS_KEYS=[]`) and apply again.

`python -m backend.app.services.stored_secrets check` lists any workspace whose stored key
can't be decrypted. Those owners see a notice in Settings asking them to enter it again.

## Reverse proxy and TLS

RagNex serves plain HTTP on `RAGNEX_HTTP_PORT`. To expose it beyond your machine, put a
reverse proxy that handles TLS in front of it (nginx, Caddy, Traefik or a cloud load
balancer). The proxy must:

- **Forward everything** to the `frontend` port. nginx inside RagNex serves the web app and
  forwards `/api` to the API.
- **Not buffer `/api` responses.** Chat answers stream as server-sent events; a buffering
  proxy delivers them all at once at the end. (nginx: `proxy_buffering off`.)
- **Allow long requests:** 300 seconds or more, for long answers and large uploads.
- **Accept uploads at least as large as `MAX_UPLOAD_SIZE_MB`.** (nginx: `client_max_body_size`.)
- **Send the client's address in `X-Forwarded-For`**, and then set `RAGNEX_TRUSTED_PROXY`,
  as described below.

### Client addresses and `RAGNEX_TRUSTED_PROXY`

Rate limits on login and registration count requests per client address. Behind a proxy,
every request comes from the proxy's address, so RagNex must learn the real one from the
proxy's `X-Forwarded-For` header. It believes that header only from the address in
`RAGNEX_TRUSTED_PROXY` and ignores it from anyone else, so clients can't make up their own
address.

To find the proxy's address as RagNex sees it, leave `RAGNEX_TRUSTED_PROXY` unset, open
the site through the proxy, and look at the first field of the latest line in:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod logs --tail 5 frontend
```

A proxy on the same machine usually shows up as the Docker network's gateway (for example
`172.18.0.1`). Set that address in `.env.prod` and apply. With several proxies, a CIDR
range covering exactly them works too.

Never set a range that includes the internet (such as `0.0.0.0/0`): any client could then
pick its own address and get around the rate limits.

If the proxy runs on the same machine, also set `RAGNEX_HTTP_PORT=127.0.0.1:8080` so
RagNex accepts connections only through the proxy.

## Creating accounts

With sign-up off (`REGISTRATION_ENABLED=false`), create accounts with:

```bash
# A user with a workspace of their own (as with sign-up):
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api   python -m backend.app.services.accounts create-user alice@example.com

# A user who joins an existing workspace instead (role: member or owner):
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api   python -m backend.app.services.accounts create-user bob@example.com --workspace WORKSPACE_ID --role member
```

It asks for the password twice. For scripts, pass `--password-stdin` and pipe the password
in (use `exec -T` then). Tell the user their password through a separate channel.

To find a workspace's ID, list them all with
`python -m backend.app.services.accounts list-workspaces` (the same way, through
`docker compose ... exec api`).

## Backups

| Store | Holds | Back up? |
|---|---|---|
| Postgres (`pgdata`) | Users, workspaces, document records, chats, settings, workspace API keys | **Yes.** Everything else hangs off it. |
| MinIO (`miniodata`) | The uploaded original files | **Yes.** They can't be recreated. |
| OpenSearch (`opensearchdata`) | Search index: document chunks and their vectors | Recommended. It can be rebuilt by reprocessing every document, but that re-runs parsing and embedding, which is slow for large collections. |
| Redis (`redisdata`) | Task queue, embedding cache and rate-limit counts | No. Losing it loses only queued work: documents being processed at that moment need to be reprocessed. |

Back up Postgres and MinIO at about the same time, so document records and files match.
For Postgres, `pg_dump` from the `postgres` container works while RagNex is running:

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec -T postgres \
  pg_dump -U ragnex -d ragnex -Fc > ragnex-$(date +%F).dump
```

For MinIO and OpenSearch, back up the volumes with the stack stopped, or use their own
tools (`mc mirror`, OpenSearch snapshots). Test a restore before you rely on it.

## Upgrading

Building locally:

```bash
git pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d --build
```

Or with the images CI publishes (see [Prebuilt images](#prebuilt-images)):

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod pull
docker compose -f docker-compose.prod.yml --env-file .env.prod up -d
```

Database migrations run automatically before the new API and worker start. Back up
Postgres first: migrations can't always be undone.

**MinIO image:** the official `minio/minio` image is no longer published, so RagNex uses
Chainguard's maintained build of the same server (`cgr.dev/chainguard/minio`), pinned by
digest in the compose files. Existing MinIO data volumes work with it unchanged. To update
it, run `docker pull cgr.dev/chainguard/minio:latest`, put the new digest
(`docker image inspect --format '{{index .RepoDigests 0}}' cgr.dev/chainguard/minio:latest`)
into `docker-compose.prod.yml`, and apply.

**Data of workspaces deleted before November 2026:** deleting a workspace used to leave
its search index and uploaded files behind. To find and remove them, run the deletion
backfill once after upgrading: as a dry run first, which lists what it would delete, then
with `--execute`.

```bash
docker compose -f docker-compose.prod.yml --env-file .env.prod exec api   python -m backend.app.services.deletion_backfill
```

**Upgrading from a version without `RAGNEX_ENCRYPTION_KEY`:** add it to `.env.prod` first
(`openssl rand -base64 32`). Compose refuses to start without it, and the upgrade encrypts
the workspace model API keys already stored.

## Re-ranking

Optional, and off by default. A re-ranker re-scores the best search candidates for each
question, which usually improves answers, especially for questions worded differently from
the documents. It costs one extra model call per question.

The compose file includes one, started only on request: Hugging Face Text Embeddings
Inference on CPU, with `cross-encoder/mmarco-mMiniLMv2-L12-H384-v1`, a small multilingual
model (it matches questions and passages across languages too).

```bash
# .env.prod
RERANK_PROVIDER=tei
RERANK_BASE_URL=http://reranker

docker compose -f docker-compose.prod.yml --env-file .env.prod --profile rerank up -d
```

On first start it downloads the model (about 500 MB). Measured on 8 CPU cores: about 2.5 GB
of memory, and about 3 seconds per question to re-score the default 15 candidates (8 seconds
for 30), which is added before the answer starts. Keep `--profile rerank` on later `up` and
`pull` commands, or the service is left out.

Larger re-rankers are more accurate but need a GPU: `BAAI/bge-reranker-v2-m3` took over a
minute per question on the same CPU. With a GPU, run TEI's GPU image (or vLLM) with that
model and point `RERANK_BASE_URL` at it.

To use another server instead (vLLM, Infinity, Jina, Cohere), set `RERANK_PROVIDER=cohere`,
`RERANK_BASE_URL` to its API base (for example `http://gpu-box:8000/v1`), `RERANK_MODEL`,
and `RERANK_API_KEY` if it needs one. See [configuration.md](configuration.md#re-ranking).

To check it's used: a search through the API returns `"reranked": true`. If the
re-ranker can't be reached, search falls back to its normal order and the API log says
`Re-ranking failed`.

## Prebuilt images

Every push to `master` that passes the tests publishes both images to the GitHub Container
Registry, and so does every version tag (`v1.2.3`):

| Image | Tags |
|---|---|
| `ghcr.io/OWNER/ragnex-backend` | `latest` and `master` (newest `master`), `sha-abc1234` (one commit), `1.2.3` and `1.2` (releases) |
| `ghcr.io/OWNER/ragnex-frontend` | the same |

To use them, set in `.env.prod`:

```bash
RAGNEX_IMAGE_PREFIX=ghcr.io/OWNER/
RAGNEX_VERSION=1.2.3        # pin a release or commit in production rather than latest
```

Images of a private repository are private too: log in first with
`docker login ghcr.io` (a GitHub personal access token with `read:packages`).

To publish a release: `git tag v1.2.3 && git push origin v1.2.3`.

## Go-live checklist

**Before the first start**

- [ ] A copy of `RAGNEX_ENCRYPTION_KEY` kept somewhere safe, apart from database backups.
- [ ] `.env.prod` created from `.env.prod.example`, with generated secrets (see
      [Generating them](#generating-them)), and `chmod 600`.
- [ ] Models available where `OLLAMA_BASE_URL` (or the OpenAI or vLLM settings) point:
      `ollama pull llama3` and `ollama pull bge-m3`, or your chosen models.
- [ ] `EMBEDDING_DIMENSION` matches the embedding model. This is hard to change later.
- [ ] `LLM_CONTEXT_WINDOW` set to the chat model's real context size.
- [ ] `TENANT_MODEL_BASE_URLS` lists only endpoints you trust, or is left empty.
- [ ] Enough resources: OpenSearch alone needs about twice `OPENSEARCH_HEAP` in memory. On
      Linux it also needs `vm.max_map_count` of at least 262144
      (`sysctl -w vm.max_map_count=262144`, and persisted in `/etc/sysctl.conf`).

**Network**

- [ ] TLS proxy in front, configured as in [Reverse proxy and TLS](#reverse-proxy-and-tls).
- [ ] `RAGNEX_TRUSTED_PROXY` set to the proxy's address.
- [ ] Only the proxy can reach `RAGNEX_HTTP_PORT` (`127.0.0.1:8080`, or a firewall rule).
- [ ] No data store ports published. `docker-compose.prod.yml` publishes none; don't use
      `docker-compose.dev.yml` on a server, because it publishes all of them without
      passwords on Redis or OpenSearch.

**Decide who can sign up**

- [ ] By default anyone who can reach the site can create an account, and each account gets
      its own workspace that uses your models and storage. Either limit sign-up to your
      email domains (`REGISTRATION_EMAIL_DOMAINS`), or turn it off
      (`REGISTRATION_ENABLED=false`) and [create accounts yourself](#creating-accounts).

**After the first start**

- [ ] All services healthy: `docker compose -f docker-compose.prod.yml --env-file .env.prod ps`.
- [ ] Data stores reachable from the API. This shows `"ok": true` when they are:
      ```bash
      docker compose -f docker-compose.prod.yml --env-file .env.prod exec api \
        python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health/ready').read().decode())"
      ```
- [ ] Create an account, upload a small document, wait for it to show **Ready**, and ask a
      question about it. This checks parsing, embedding, search and the chat model together.
- [ ] A chat answer appears word by word, not all at once. If it arrives all at once, the
      proxy is buffering.
- [ ] Rate limits see real addresses: the address in `docker compose ... logs frontend` is a
      client's, not the proxy's.
- [ ] Backups scheduled, and one restore tested.
