# API guide

Everything the web app does goes through this HTTP API, so other programs can do the same:
upload documents, search them, and chat. This guide covers signing in and the common tasks.
For every endpoint and field, see the interactive reference at **`/api/docs`** on your
RagNex server (for example `https://ragnex.example.com/api/docs`); the machine-readable
schema is at `/api/openapi.json`.

All endpoints are under `/api/v1/` and exchange JSON, except file upload (multipart) and
file download.

## Signing in

There are two ways to authenticate.

**API key** (for programs and scripts). Create one in the web app under
**Settings → API keys**, or through the API (see [API keys](#api-keys)). Send it in the
`X-API-Key` header. A key belongs to one workspace and can do what its access allows:

| Access | Allows |
|---|---|
| `read` | `GET` requests (listing, reading, downloading, chat history) and search |
| `write` | Everything a workspace member can do, including uploads, deletes and chat |

API keys can't manage accounts: workspaces, members, model settings and API keys need a
signed-in user.

**Login token** (what the web app uses). Exchange email and password for tokens:

```bash
curl -s https://ragnex.example.com/api/v1/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"email": "alice@example.com", "password": "..."}'
```

```json
{"access_token": "eyJ...", "refresh_token": "eyJ...", "token_type": "bearer"}
```

Send the access token as `Authorization: Bearer <access_token>`. It lasts 30 minutes by
default; get a new pair with `POST /api/v1/auth/refresh` and `{"refresh_token": "..."}`.
`POST /api/v1/auth/logout` and `GET /api/v1/auth/me` do what their names say.

### Choosing the workspace

Requests about knowledge bases, documents, search and chat act in one workspace, named in
the `X-Tenant-ID` header. List yours with `GET /api/v1/tenants`:

```json
[{"id": "3f9c2a6e-...", "name": "alice@example.com's tenant"}]
```

With an API key, `X-Tenant-ID` must be the key's own workspace.

The examples below assume:

```bash
API=https://ragnex.example.com/api/v1
AUTH=(-H "X-API-Key: rk_..." -H "X-Tenant-ID: 3f9c2a6e-...")
```

## Knowledge bases

```bash
# Create: template is general (default), laws or paper; see the user guide
curl -s "$API/knowledgebases" "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"name": "Policies", "description": "HR policies", "template": "laws"}'
# -> {"id": "8b1d...", "name": "Policies", "description": "HR policies", "template": "laws"}

curl -s "$API/knowledgebases" "${AUTH[@]}"                    # list
curl -s -X PUT "$API/knowledgebases/8b1d..." "${AUTH[@]}" \
  -H 'Content-Type: application/json' -d '{"name": "HR policies"}'   # change fields given
curl -s -X DELETE "$API/knowledgebases/8b1d..." "${AUTH[@]}"  # also deletes its documents
```

## Documents

### Uploading

```bash
curl -s "$API/knowledgebases/8b1d.../documents" "${AUTH[@]}" -F file=@handbook.pdf
# -> {"id": "c41e...", "kb_id": "8b1d...", "filename": "handbook.pdf", "status": "pending", "task_id": "..."}
```

Only part of a PDF: add `?from_page=0&to_page=20` to the URL. Pages count from 0 and
`to_page` isn't included, so that's the first 20 pages.
Supported types and the size limit are in the [user guide](user-guide.md#supported-files);
anything else gets `400` with the list of supported types, and a file over the limit
gets `413`.

### Waiting until it's ready

Processing runs in the background. Poll the document until `status` is `indexed` (or
`failed`, with the reason in `error_message`):

```bash
curl -s "$API/documents/c41e..." "${AUTH[@]}"
```

```json
{
  "id": "c41e...", "kb_id": "8b1d...", "filename": "handbook.pdf", "status": "indexing",
  "parse_progress": 1.0, "index_progress": 0.4, "error_message": null, "...": "..."
}
```

The statuses are `pending`, `parsing`, `done` (parsed, waiting to be indexed), `indexing`,
`indexed` and `failed`. Polling every few seconds is plenty.

### Other document requests

| Request | Does |
|---|---|
| `GET /knowledgebases/{kb_id}/documents` | Lists a knowledge base's documents with their status. |
| `GET /documents/{id}/file` | Downloads the original file (always as an attachment). |
| `GET /documents/{id}/chunks?q=...&page=1&size=20` | The passages made from it, optionally filtered by text. `GET /chunks/{chunk_id}` returns one. |
| `POST /documents/{id}/reprocess` | Processes it again (e.g. after a failure). `409` while it's still being processed. |
| `POST /knowledgebases/{kb_id}/documents/reprocess-failed` | Reprocesses every failed document; returns what was queued and what was skipped, and why. |
| `DELETE /documents/{id}` | Deletes it; it disappears from search at once. |

## Search

Find the passages that best match a query, without generating an answer:

```bash
curl -s "$API/knowledgebases/8b1d.../search" "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"query": "How many vacation days do new employees get?", "top_k": 5}'
```

```json
{"hits": [
  {"chunk_id": "a7f0...", "doc_id": "c41e...", "content": "Article 12. New employees ...", "score": 0.032}
]}
```

Search combines keyword matching (BM25) and meaning (vector similarity), merged by rank.
`top_k` (1–100, default 10) sets how many hits come back. The scores rank hits within one
response; don't compare them across queries. Optional tuning fields (`bm25_weight`,
`vector_weight`, `rrf_k`, ...) are described in the reference.

## Chat

A chat session draws on one or more knowledge bases and keeps its history.

```bash
curl -s "$API/chat/sessions" "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"kb_ids": ["8b1d..."], "name": "HR questions", "system_prompt": "Answer briefly."}'
# -> {"id": "5e22...", "name": "HR questions", "system_prompt": "Answer briefly.", "kb_ids": ["8b1d..."], ...}
```

`system_prompt` is optional: extra instructions for every answer in the session.

### Asking, with the whole answer at once

```bash
curl -s "$API/chat/sessions/5e22.../messages" "${AUTH[@]}" -H 'Content-Type: application/json' \
  -d '{"content": "How many vacation days do new employees get?"}'
```

```json
{
  "id": "9d0b...", "role": "assistant",
  "content": "New employees get 20 vacation days a year (Article 12).",
  "citations": [{"chunk_id": "a7f0...", "doc_id": "c41e...", "kb_id": "8b1d...", "score": 0.032}],
  "created_at": "2026-11-27T10:15:02Z"
}
```

`citations` are the passages the answer was given; open them with `GET /chunks/{chunk_id}`.
`top_k` (1–20, default 6) sets how many passages are searched for.

### Asking, with the answer streamed

`POST /chat/sessions/{id}/messages/stream` takes the same body and answers with
[server-sent events](https://html.spec.whatwg.org/multipage/server-sent-events.html), so the
answer can be shown as it's written:

```bash
curl -sN "$API/chat/sessions/5e22.../messages/stream" "${AUTH[@]}" \
  -H 'Content-Type: application/json' -d '{"content": "And for part-time staff?"}'
```

```text
event: meta
data: {"user_message": {"id": "...", "role": "user", "content": "And for part-time staff?", ...}, "citations": [...]}

event: delta
data: {"text": "Part-time staff get "}

event: delta
data: {"text": "a pro-rated share."}

event: done
data: {"id": "...", "role": "assistant", "content": "Part-time staff get a pro-rated share.", "citations": [...], ...}
```

- `meta` comes first: your saved question and the citations.
- `delta` events carry the answer piece by piece; join their `text`.
- `done` carries the saved answer. If generation fails, an `error` event with `detail`
  comes instead, and no answer is saved.
- If you disconnect, the answer is still finished and saved; it appears in the history.
- Problems found before the answer starts (unknown session, invalid input) are ordinary
  HTTP errors, not events.

### History and sessions

| Request | Does |
|---|---|
| `GET /chat/sessions` | Lists sessions. |
| `GET /chat/sessions/{id}/messages?offset=0&limit=50` | Messages, oldest first. `?latest=true&limit=20` returns the newest 20. |
| `DELETE /chat/sessions/{id}` | Deletes a session and its messages. |

## Workspaces and members

These need a signed-in user (`Authorization: Bearer ...`), not an API key.

| Request | Does |
|---|---|
| `POST /tenants` with `{"name": "..."}` | Creates a workspace; you become its owner. |
| `PUT /tenants/{id}` / `DELETE /tenants/{id}` | Renames / deletes a workspace (owners). |
| `POST /tenants/{id}/members` with `{"user_id": "...", "role": "member"}` | Adds an existing user, or changes their role (owners). Roles: `member`, `owner`. |
| `PUT /tenants/{id}/members/{user_id}` with `{"role": "owner"}` | Changes a role (owners). |
| `DELETE /tenants/{id}/members/{user_id}` | Removes a member (owners). A workspace always keeps at least one owner. |
| `GET` / `PUT /tenants/{id}/model-settings` | The workspace's model settings; see the reference for the fields. |

## API keys

Also signed-in users only:

```bash
curl -s "$API/api-keys" -H "Authorization: Bearer $TOKEN" -H "X-Tenant-ID: 3f9c2a6e-..." \
  -H 'Content-Type: application/json' -d '{"name": "nightly-sync", "scopes": ["read"]}'
# -> {"id": "...", "api_key": "rk_..."}    shown only now: store it
```

`GET /api-keys` lists keys (never the key itself); `POST /api-keys/revoke` with
`{"id": "..."}` revokes one.

## Errors and limits

Errors come as JSON with a `detail` field:

| Status | Meaning |
|---|---|
| `400` | The request can't be done as asked (e.g. an unsupported file type). |
| `401` | Missing, expired or invalid token or API key. |
| `403` | Signed in, but not allowed: not a member of the workspace, or the API key lacks access. |
| `404` | Not found in this workspace. Other workspaces' data is reported as not found, not forbidden. |
| `409` | Conflicts with the current state (e.g. reprocessing a document that's being processed). |
| `413` | Upload too large. |
| `422` | Invalid input; `detail` lists each problem with its field (`loc`) and reason (`msg`). |
| `429` | Too many requests. Logins are limited to 20 and registrations to 10 a minute per address. |
| `503` | A dependency is unavailable, or a stored model API key can't be decrypted (`detail` says which). |
