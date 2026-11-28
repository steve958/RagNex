# Extending RagNex

Step-by-step for the changes people make most often. Each lists every place that needs to
change, including the easy-to-miss ones (the web app, the docs, the build's import check).
[architecture.md](architecture.md) explains how the pieces fit; [development.md](development.md)
covers running and testing.

## A chat model provider

Example: `services/llm_anthropic.py` (Claude).

1. **Implement `LLMService`** (`backend/app/services/llm.py`): `generate(messages)` returns
   an `LLMResult`; `generate_stream(messages)` yields text fragments. Messages are
   `LLMMessage(role, content)` with roles `system`, `user`, `assistant`; RagNex sends its
   system prompt, retrieved context and conversation summary as leading `system`
   messages. Put a provider with its own SDK in its own module.
2. **Raise `LLMRefusal`** when the model declines; chat shows it as a clear message.
3. **Register it**: add the name to `LLMConfig.provider` and to `create_llm_service` in
   `llm.py`, and to `LLMProvider` in `services/model_settings.py`. If it's a paid hosted
   service, add it to `_PAID_PROVIDERS` there, so a workspace must bring its own key.
4. **Settings** for its credentials: see [A setting](#a-setting).
5. **Web app**: add it to `LLM_PROVIDERS` in
   `frontend/src/components/settings/modelSettingsForm.tsx` and to `LlmProvider` in
   `frontend/src/services/modelSettingsApi.ts`.
6. **Dependencies**: add its SDK to `backend/pyproject.toml` and run `uv lock`.
7. **Tests**: drive the real SDK or HTTP client against a mocked transport
   (`tests/test_llm_anthropic.py` replays the provider's streamed response format).
8. **Docs**: `docs/configuration.md` (Models) and the user guide's Settings section.

## An embedding provider

1. **Implement `EmbeddingService`** in `backend/app/services/embeddings.py`: `embed(texts)`
   returns an `EmbeddingResult` with one vector per text. Callers use `embed_cached`, which
   adds the Redis cache and rate limit around it.
2. **Register it** in `create_embedding_service` and in `Provider` in
   `services/model_settings.py` (that list is the embedding one; chat providers are
   `LLMProvider`).
3. **Web app**: add it to `PROVIDERS` in `modelSettingsForm.tsx` (used for embeddings; the
   chat model list extends it).
4. **Vector size**: the index's vector size is `EMBEDDING_DIMENSION`. Changing a workspace's
   embedding model is refused while it has indexed documents, and a new model is
   test-called to check its vector size (`merge_embedding_update`).

## A file type

1. **Parser**: a DeepDoc parser in `deepdoc/parser/`, exported from
   `deepdoc/parser/__init__.py` (imports there are guarded, so a missing dependency
   disables a parser instead of breaking the import; the backend image's build check in
   `docker/backend.Dockerfile` fails the build if a parser it lists is unavailable, so add
   yours to that list).
2. **Routing**: add the extension to `SUPPORTED_EXTENSIONS` and a branch to
   `parse_document_binary` in `backend/app/services/parsing.py`, returning text sections.
   Upload checks use `SUPPORTED_EXTENSIONS`.
3. **Web app**: the upload form's file picker list (`SUPPORTED_UPLOAD_TYPES` in
   `frontend/src/components/documents/DocumentUploadForm.tsx`).
4. **Tests**: add a sample to `backend/tests/format_samples.py`.
   `tests/test_parsing_formats.py` fails until there is one, runs every supported
   extension through parsing and chunking, and checks the picker's list matches
   `SUPPORTED_EXTENSIONS`.
5. **Docs**: the user guide's supported files list.

## A chunking template

1. **Chunker** in `backend/app/services/chunking/`, next to `general.py`, `laws.py` and
   `paper.py`: takes the parsed document and a config, returns chunks.
2. **Register it**: add the name to `Template` in `backend/app/api/v1/knowledgebases.py`,
   and a branch where `tasks/parsing.py` picks the chunker by template.
3. **Web app**: the template lists in
   `frontend/src/components/kb/KnowledgeBaseCreateModal.tsx` and
   `frontend/src/pages/KnowledgeBaseSettingsPage.tsx`.
4. **Docs**: the user guide's Templates table.

## A re-ranker API format

`backend/app/services/rerank.py` speaks two formats (`cohere`, `tei`). A new one needs a
request body in `rerank()`, a response branch in `_parse()`, the name in
`Settings.rerank_provider`, and a test in `tests/test_rerank.py` with a mocked transport.

## A setting

1. **Field** on `Settings` in `backend/app/core/config.py` (environment variable = the field
   name in capitals). Validate it there if a bad value would fail later in a confusing way
   (see `JWT_SECRET`, `RAGNEX_ENCRYPTION_KEY`).
2. **Docs**: a row in `docs/configuration.md`. `tests/test_docs.py` fails if a setting is
   missing there.
3. **Production**: pass it through in `docker-compose.prod.yml` (`x-backend` →
   `environment`); only listed variables reach the containers. Add it to
   `.env.prod.example` if operators are likely to set it.

## An API endpoint

1. **Router** in `backend/app/api/v1/`, registered in `backend/app/api/router.py`.
2. **Access**, as a dependency (`backend/app/core/deps.py`):
   - `require_tenant_membership` for workspace data: checks the `X-Tenant-ID` header,
     membership, and for API keys their workspace and access (`GET` needs `read`, other
     methods `write`);
   - `require_tenant_read` for a `POST` that only reads (like search), so a read key may
     call it;
   - `require_session_user` for account management that API keys must not do.
3. **Input**: Pydantic models with the constrained types in `core/validation.py` (`Name()`,
   `Text(n)`, `NewPassword`). Filter every query by `tenant_id`, and answer 404 for other
   workspaces' data.
4. **Tests** next to the area's existing ones; if the API guide should show it, add the
   example to `docs/api.md` and to `tests/test_api_guide.py`, which runs the guide's
   examples.

## A database change

1. Change the model in `backend/app/models/`.
2. Add a migration in `backend/alembic/versions/`, numbered after the last one
   (`0007_...py` → `0008_...py`, `revision = "0008"`, `down_revision = "0007"`). Write
   `downgrade()` too.
3. Data migrations can import from `backend.app` (see `0006_encrypt_tenant_api_keys.py`).
4. The test suite applies migrations at the start of each run; deployments apply them
   before the API starts.
