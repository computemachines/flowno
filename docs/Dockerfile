# Minimal image for serving pre-built Sphinx documentation
#
# The HTML must be built before building this image.
# CI/CD workflow: 1) make html, 2) docker build
#
# Build: cd docs && make html && docker build -t ghcr.io/computemachines/flowno-docs:latest .
# Run:   docker run -p 8080:80 ghcr.io/computemachines/flowno-docs:latest
#        Then visit http://localhost:8080/docs/

FROM nginx:alpine

# Copy pre-built docs (build/html must exist from prior sphinx build)
COPY build/html /usr/share/nginx/html/docs

# Custom nginx config to handle /docs/ routing
COPY nginx.conf /etc/nginx/conf.d/default.conf

EXPOSE 80
