# Troubleshooting and FAQ

Common problems, what causes them, and how to fix them. Some fixes need the server
administrator; those are marked **(admin)**. Commands assume the production setup in
[deployment.md](deployment.md); with `docker compose`, add the same
`-f docker-compose.prod.yml --env-file .env.prod` options as there.

## Documents

### A document failed

Its error is shown in the document list, under the file name. Then:

| Error mentions | Cause | Fix |
|---|---|---|
| `HTTPStatusError` and `/api/embeddings`, or `ConnectError` | The embedding model isn't available: not downloaded, or its server is down. | **(admin)** For Ollama: `ollama pull bge-m3` (or the model in `EMBEDDING_MODEL`), and check `OLLAMA_BASE_URL`. Then **Reprocess**. |
| `can't be decrypted` | The workspace's stored model API key can't be read since the server's encryption key changed. | A workspace owner enters the key again in **Settings**, then **Reprocess**. |
| Anything else | | **Reprocess** once. If it fails again, **(admin)** check the worker log: `docker compose logs worker`. |

**Reprocess N failed** retries all failed documents in a knowledge base at once.

### A document stays in `pending` or `parsing`

Nothing is processing documents.

- **(admin)** Check that the worker is running and look at its log:
  `docker compose ps worker` and `docker compose logs --tail 100 worker`.
- Large PDFs can take several minutes; the progress shown should still move.
- A document stuck for over 30 minutes can be reprocessed. Before that, **Reprocess**
  answers that it's still being processed, so it isn't processed twice at once.

### A scanned PDF has no text

Scanned PDFs are images of pages and need OCR (text recognition), which the standard image
doesn't include. Use a PDF with a text layer: most scanners and PDF tools can add one.
**(admin)** OCR can be enabled by building the backend image with the `deepdoc-vision` extra.

### The upload is rejected: unsupported file type

The format isn't supported; the message lists the ones that are. For the older Office
formats (`.doc`, `.ppt`, `.xls`), save the file as `.docx`, `.pptx` or `.xlsx` and upload
that.

### The upload is rejected as too large

The limit is `MAX_UPLOAD_SIZE_MB` (100 MB by default). **(admin)** A reverse proxy in front
of RagNex needs a limit at least as large, or it refuses the upload first.

## Answers

### Answers ignore my documents, or say they don't know

- **Is the document `indexed`?** Others aren't searched yet.
- **Does the chat use the right knowledge base?** A chat keeps the knowledge bases it was
  created with; start a new chat to use others.
- **Does search find it?** Open the document, search its passages for the words you'd
  expect; or ask with the words the document uses.
- **(admin)** **Is `LLM_CONTEXT_WINDOW` right?** If it's set smaller than the model's real
  context size, fewer passages fit in each question. If larger, long chats fail.

### Answers got worse, or the API log says "Re-ranking failed"

**(admin)** The re-ranker can't be reached or returns errors, so search is using its normal
order. Check the service (`docker compose --profile rerank ps reranker` and its log) and
`RERANK_BASE_URL`. On its first start the bundled re-ranker is still downloading its model.

### The answer appears all at once instead of word by word

**(admin)** A reverse proxy in front of RagNex is buffering responses. With nginx, set
`proxy_buffering off` for `/api/`; see [deployment.md](deployment.md#reverse-proxy-and-tls).

### Chat says a stored API key can't be decrypted

The server's encryption key (`RAGNEX_ENCRYPTION_KEY`) changed after the workspace's model
API key was saved. A workspace owner enters the key again under **Settings → LLM** (or
**Embeddings**). **(admin)** To avoid this when changing the encryption key, follow
[the rotation steps](deployment.md#rotating-the-encryption-key).

### "Generation failed" or "The model returned an empty response"

The chat model couldn't be reached or returned nothing. **(admin)** Check that the model in
`LLM_MODEL` is available (`ollama pull llama3` for the default) and that `OLLAMA_BASE_URL`
(or the OpenAI or vLLM settings) is right; the API log has the details:
`docker compose logs --tail 100 api`. Your question was saved; ask again once it's fixed.

## Accounts and settings

### There's no Register link

Sign-up is closed on this server, or limited to certain email domains. Ask the
administrator for an account. **(admin)** See
[Creating accounts](deployment.md#creating-accounts).

### "Too many requests"

Logins (20 a minute) and registrations (10 a minute) are limited per address. Wait a
minute. **(admin)** If everyone behind a proxy hits the limit together, the proxy's address
is being counted instead of each user's: set `RAGNEX_TRUSTED_PROXY`
([deployment.md](deployment.md#client-addresses-and-ragnex_trusted_proxy)).

### I can't change the embedding model

It's locked while the workspace has processed documents: documents prepared with one model
can't be searched with another. Delete the documents, change the model, and upload them
again.

### I can't change model settings at all

Only workspace owners can; members see them read-only.

### The web app shows the wrong workspace

The web app works in the first workspace you belong to; it can't switch yet. Use the
[API](api.md#choosing-the-workspace) for other workspaces.

## For administrators

### Checking the services

```bash
docker compose ps                                  # all should be running / healthy
docker compose exec api python -c "import urllib.request; print(urllib.request.urlopen('http://localhost:8000/health/ready').read().decode())"
```

`/health/ready` reports Postgres, Redis, MinIO and OpenSearch separately (`"ok": false`
for any that's down). The interactive API reference is at `/api/docs`.

### The backend won't start

Its log (`docker compose logs api`) names the setting:

- `JWT_SECRET must be set...`: set a random value of at least 32 bytes.
- `RAGNEX_ENCRYPTION_KEY must be set...` or `...must be 32 random bytes in base64`: set
  one with `openssl rand -base64 32`. If the server ran before with a different key, use
  that one, or stored workspace API keys become unreadable.

### Searches return nothing after changing `EMBEDDING_DIMENSION` or the embedding model

Existing search indices were built for the old size and model. Delete the workspaces'
documents and upload them again (or delete the indices and reprocess every document).
