# Auto-generated Dockerfile for serverless-example
# Optimized for Google Cloud Build (runs from project root)

FROM python:3.12-slim as builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir hatchling

# Build and cache SDK wheel
COPY libs/k3sfn /app/libs/k3sfn
RUN pip wheel --no-deps --wheel-dir=/wheels /app/libs/k3sfn

# Build runtime dependency wheels
RUN pip wheel --no-deps --wheel-dir=/wheels fastapi uvicorn pydantic valkey pyyaml

# Runtime stage
FROM python:3.12-slim

WORKDIR /app

# Install from pre-built wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Copy function code
COPY apps/serverless-example/functions /app/functions

# Runtime configuration
ENV PORT=8080
EXPOSE 8080

# Run the function server (K3SFN_FUNCTION env var controls which function)
CMD ["python", "-m", "k3sfn.runtime", "functions"]
