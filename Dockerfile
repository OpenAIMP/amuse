# amuse — options-lab screeners. Stdlib-only: no pip install needed.
FROM python:3.12-slim

WORKDIR /app
COPY . /app

# The repo's Public.com MCP shim authenticates from the environment
# (the local twin uses the Secure Vault instead).
ENV PUBLIC_MCP_CLI=/app/bin/public-mcp
ENV PYTHONUNBUFFERED=1

ENTRYPOINT ["python3"]
CMD ["--version"]
