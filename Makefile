.PHONY: docs docker dev clean

# Build Sphinx documentation
docs:
	uv run --group docs sphinx-build -M html docs/source docs/build

# Build Docker image for documentation (requires docs to be built first)
docker: docs
	cd docs && docker build -t ghcr.io/computemachines/flowno-docs:latest .

# Run docs locally at http://localhost:8080/docs/
dev: docker
	docker compose -f docker-compose.dev.yml up

# Clean build artifacts
clean:
	rm -rf docs/build dist package-root
