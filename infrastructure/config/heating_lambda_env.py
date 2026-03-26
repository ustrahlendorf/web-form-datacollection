"""Default environment values for Lambdas that use the installable ``backend`` package."""

# Lambda extracts the asset under /var/task; backend code lives at backend/src/backend/.
BACKEND_PYTHONPATH = "backend/src"

# Lambda filesystem is read-only except /tmp; token cache must use a writable path.
VIESSMANN_TOKEN_CACHE_PATH = "/tmp/viessmann/tokens.json"
