# syntax=docker/dockerfile:1
# The web app for the cloud server (ADR-023): the Vite build, served by nginx. Build from web/:
#   docker build -t scheduling-agent-web web
#
# Static files only. Traefik sends /api to the api service, so the browser sees one origin
# (the session cookie works, no CORS), the same as Vite's dev proxy. Base images are pinned
# by digest (T20).

# ---- Stage 1: build ---------------------------------------------------------------
FROM node:24.22.1-alpine@sha256:06d7adf3e0ef61a13f1d28682726366f97a15aa1888c934d3ecec86c33918b53 AS build
WORKDIR /web
# Dependencies from the lockfile only, so this layer is reused until they change.
COPY package.json package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY . .
RUN npm run build

# ---- Stage 2: serve ---------------------------------------------------------------
# nginx's own unprivileged image: no root, listens on 8080. Its writable paths are moved
# to /tmp (nginx/nginx.conf), so the root filesystem can be read-only (T21).
FROM nginxinc/nginx-unprivileged:1.30.6-alpine-slim@sha256:5d8bb9437d74a600ec5dbf90c035451c724dc33eac8d3a71078f6f8612c345f6
COPY nginx/nginx.conf /etc/nginx/nginx.conf
COPY nginx/security-headers.conf /etc/nginx/security-headers.conf
COPY --from=build /web/dist /usr/share/nginx/html
EXPOSE 8080
