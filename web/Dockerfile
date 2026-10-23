# HeartSignal Vue 화면 (nginx :80)
# Build context is the repository root (see web/docker-build.sh).
FROM --platform=$BUILDPLATFORM node:22-alpine AS frontend-build

WORKDIR /app
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/index.html web/vite.config.js ./
COPY web/src ./src
RUN npm run build

FROM nginx:alpine

RUN rm /etc/nginx/conf.d/default.conf
COPY web/default.conf /etc/nginx/conf.d/default.conf
COPY --from=frontend-build /app/dist/ /usr/share/nginx/html/

# Preserve the existing standalone project pages.
COPY intro_main.html external_index.html internal_index.html /usr/share/nginx/html/

EXPOSE 80

CMD ["nginx", "-g", "daemon off;"]
