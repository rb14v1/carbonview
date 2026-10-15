# syntax=docker/dockerfile:1
FROM node:20-alpine AS builder

WORKDIR /app

COPY package.json package-lock.json ./
RUN npm ci --legacy-peer-deps

COPY . .
RUN npm run build

FROM nginx:1.27-alpine

ENV PORT=8080

RUN mkdir -p /tmp/nginx-cache /tmp/nginx-client-body \
 && chown -R nginx:nginx /tmp/nginx-cache /tmp/nginx-client-body

RUN printf 'server {\n\
    listen 8080;\n\
    server_name _;\n\
    root /usr/share/nginx/html;\n\
    index index.html;\n\
    client_body_temp_path /tmp/nginx-client-body;\n\
    proxy_temp_path /tmp/nginx-cache;\n\
    fastcgi_temp_path /tmp/nginx-cache;\n\
    uwsgi_temp_path /tmp/nginx-cache;\n\
    scgi_temp_path /tmp/nginx-cache;\n\
\n\
    location /healthz {\n\
        access_log off;\n\
        return 200 "ok";\n\
        add_header Content-Type text/plain;\n\
    }\n\
\n\
    location / {\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

COPY --from=builder /app/dist /usr/share/nginx/html

RUN chown -R nginx:nginx /usr/share/nginx/html

RUN sed -i 's@^pid .*@pid /tmp/nginx.pid;@' /etc/nginx/nginx.conf \
 && sed -i '/^user /d' /etc/nginx/nginx.conf

USER nginx

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
  CMD wget -qO- http://localhost:8080/healthz || exit 1

CMD ["nginx", "-g", "daemon off;"]
