# agent-builder nginx Dockerfile
# Phase 1：双 server_block（80 公网 + 8080 内网管理端）
FROM nginx:1.25-alpine

COPY nginx.conf /etc/nginx/nginx.conf
COPY conf.d/ /etc/nginx/conf.d/
COPY snippets/ /etc/nginx/snippets/

EXPOSE 80 8080
CMD ["nginx", "-g", "daemon off;"]
