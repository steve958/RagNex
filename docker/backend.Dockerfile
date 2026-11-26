# syntax=docker/dockerfile:1
#
# RagNex backend image: one image for the API, the Celery worker and migrations.
# Pick the role with the command:  api (default) | worker | migrate | <any command>
#
# Build from the repo root:
#   docker build -f docker/backend.Dockerfile -t ragnex-backend .
#
# EXTRAS selects optional dependency groups from backend/pyproject.toml (comma-separated).
# The default covers all document formats in scope; "deepdoc,deepdoc-vision" adds the
# OCR/layout stack (much larger image, and the models must be provided separately).

ARG PYTHON_VERSION=3.13

# --- Dependencies ---------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim AS deps

ARG EXTRAS="deepdoc"
ENV PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN python -m venv /opt/venv
ENV PATH=/opt/venv/bin:$PATH

# Only the dependency manifest, so code changes don't invalidate this layer. The project
# installs no modules of its own (py-modules = []), just its dependencies.
COPY backend/pyproject.toml /tmp/build/
RUN pip install "/tmp/build[${EXTRAS}]"

# --- Runtime ----------------------------------------------------------------------------
FROM python:${PYTHON_VERSION}-slim

ENV PATH=/opt/venv/bin:$PATH \
    PYTHONPATH=/app \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

RUN useradd --system --uid 10001 --user-group --home-dir /app --no-create-home ragnex

COPY --from=deps /opt/venv /opt/venv

WORKDIR /app
# Code is imported as `backend.app.*` and `deepdoc.*` relative to /app.
COPY backend/app ./backend/app
COPY backend/alembic ./backend/alembic
COPY backend/alembic.ini ./backend/alembic.ini
COPY deepdoc ./deepdoc
COPY docker/backend-entrypoint.sh /usr/local/bin/ragnex

# Strip CRLF in case the script was checked out on Windows, then fail the build early if
# the app, the Celery tasks or any document parser can't be imported. DeepDoc disables a
# parser silently when a dependency is missing, which would otherwise only show up as
# failed uploads in production.
RUN sed -i 's/\r$//' /usr/local/bin/ragnex && chmod 0755 /usr/local/bin/ragnex \
 && python -c "\
import backend.app.main; \
from backend.app.core.celery_app import celery_app; \
celery_app.loader.import_default_modules(); \
tasks = sorted(t for t in celery_app.tasks if t.startswith('backend.')); \
assert len(tasks) == 4, tasks; \
from deepdoc import parser as p; \
missing = [n for n in ('PdfParser', 'DocxParser', 'ExcelParser', 'PptParser', 'HtmlParser', 'JsonParser', 'MarkdownParser', 'TxtParser') if getattr(p, n, None) is None]; \
assert not missing, f'document parsers unavailable: {missing}'; \
print('import check ok:', tasks)"

USER ragnex
EXPOSE 8000
ENTRYPOINT ["ragnex"]
CMD ["api"]
