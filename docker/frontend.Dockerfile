# syntax=docker/dockerfile:1
#
# RagNex frontend: builds the React app and serves it with nginx, which also proxies
# /api to the backend so the browser talks to a single origin (no CORS needed).
#
# Build from the repo root:
#   docker build -f docker/frontend.Dockerfile -t ragnex-frontend .
#
# Runtime settings (environment variables):
#   RAGNEX_API_UPSTREAM   backend host:port            (default api:8000)
#   RAGNEX_MAX_UPLOAD_MB  largest accepted upload, MB  (default 100; keep in line with
#                         the backend's MAX_UPLOAD_SIZE_MB)

FROM node:22-alpine AS build
WORKDIR /src
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
# Empty = same origin (nginx proxies /api). Only set this to call a different API origin.
ARG VITE_API_URL=""
ENV VITE_API_URL=${VITE_API_URL}
RUN npm run build

FROM nginx:1.27-alpine
ENV RAGNEX_API_UPSTREAM=api:8000 \
    RAGNEX_MAX_UPLOAD_MB=100
# Rendered with envsubst at container start by the official image's entrypoint.
COPY docker/nginx.conf.template /etc/nginx/templates/default.conf.template
COPY --from=build /src/dist /usr/share/nginx/html
EXPOSE 80
