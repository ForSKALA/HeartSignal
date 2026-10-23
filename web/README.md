# HeartSignal web frontend

The Vue 3 + Vite application is in this directory.

## Local development

```bash
cd web
npm ci
npm run dev
```

Open `http://localhost:5174`. Vue Router uses hash-based URLs so client-side pages do not conflict with the existing Ingress API paths. Vite proxies `/api` to the auth service on port 8080 and `/rag-query` to the RAG service on port 8001.

## Production image

Run `./web/docker-build.sh [VERSION]` from the repository root (or execute the script by path). The Docker build compiles the Vue app and serves its output through Nginx. Production API requests use same-origin `/api` and `/rag-query` paths, which Ingress routes to their respective backend services.

Set `VITE_AUTH_API_URL` and `VITE_RAG_API_URL` at build time only if the production APIs use different paths or origins.
