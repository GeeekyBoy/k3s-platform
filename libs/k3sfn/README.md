# k3sfn - Serverless Functions for Kubernetes

Firebase-style serverless functions that deploy to Kubernetes with automatic scale-to-zero using KEDA.

## Quick Start

### 1. Create a new serverless app

```bash
./scripts/new-serverless-app.sh my-api
```

### 2. Define functions with decorators

```python
from k3sfn import serverless, http_trigger, Request

@serverless(
    memory="256Mi",
    cpu="100m",
    min_instances=0,  # Scale to zero when idle
    max_instances=10,
)
@http_trigger(path="/api/hello", methods=["GET"])
async def hello(request: Request):
    name = request.query_params.get("name", "World")
    return {"message": f"Hello, {name}!"}
```

### 3. Add to apps.yaml

```yaml
serverless:
  - name: my-api
    path: apps/my-api
    namespace: apps
    enabled: true
```

### 4. Deploy

```bash
./scripts/deploy-apps.sh
```

## Decorator Reference

### @serverless

Base decorator for all functions. Configures resource allocation and scaling.

```python
@serverless(
    memory="256Mi",       # Memory request
    cpu="100m",           # CPU request
    memory_limit="512Mi", # Memory limit (optional)
    cpu_limit="200m",     # CPU limit (optional)
    min_instances=0,      # Minimum replicas (0 = scale to zero)
    max_instances=10,     # Maximum replicas
    timeout=30,           # Function timeout in seconds
    environment={},       # Environment variables
    secrets=[],           # Secret names to mount
    labels={},            # Additional Kubernetes labels
)
```

### @http_trigger

HTTP-triggered function. Creates a Deployment + HTTPScaledObject.

```python
@serverless(memory="256Mi")
@http_trigger(
    path="/api/users",    # URL path
    methods=["GET", "POST"],
    auth=None,            # "api_key", "jwt", or None
    cors=True,            # Enable CORS
    rate_limit=None,      # Requests per minute
)
async def get_users(request: Request):
    return {"users": []}
```

### @queue_trigger

Queue-triggered function. Scales based on Valkey/Redis queue depth.

```python
@serverless(memory="512Mi")
@queue_trigger(
    queue_name="tasks",      # Queue name (Valkey list key)
    batch_size=5,            # Messages per invocation
    visibility_timeout=60,   # Seconds before retry
)
async def process_tasks(messages, context):
    for msg in messages:
        await process(msg)
```

### @schedule_trigger

Scheduled function. Creates a Kubernetes CronJob.

```python
@serverless(memory="256Mi")
@schedule_trigger(
    cron="0 * * * *",     # Every hour
    timezone="UTC",
)
async def hourly_job(context):
    await collect_metrics()
```

## CLI Commands

### List functions

```bash
uv run python3 -m k3sfn.cli list ./apps/my-api
```

### Generate manifests

```bash
uv run python3 -m k3sfn.cli generate ./apps/my-api \
    --name my-api \
    --output ./generated \
    --namespace apps
```

### Run locally

```bash
uv run python3 -m k3sfn.cli run ./apps/my-api --port 8080
```

## Cold Start Behavior

When a function is scaled to zero and receives a request:

1. **KEDA Interceptor** receives the request and queues it
2. **KEDA** signals the deployment to scale up (0 → 1)
3. **Kubernetes** schedules the pod on a node
4. **Container** starts and application initializes
5. **Interceptor** forwards the queued request to the ready pod

**Typical cold start times:**
- Warm node (image cached): ~10-15 seconds
- Cold node (image pull needed): ~25-35 seconds

**Configuration:**
- `interceptor.replicas.waitTimeout`: Time to wait for pod (default: 120s)
- `interceptor.responseHeaderTimeout`: Time to wait for response (default: 60s)

**For critical workloads** (payments, etc.), use `min_instances=1` to avoid cold starts:

```python
@serverless(
    min_instances=1,  # Always keep 1 pod running - no cold start
    max_instances=10,
)
@http_trigger(path="/api/payment", methods=["POST"])
async def process_payment(request: Request):
    # This will never experience cold start latency
    ...
```

## Architecture

```
                    +---------------------------------------------+
                    |              Traefik Ingress                |
                    +----------------------+----------------------+
                                           |
                    +----------------------v----------------------+
                    |       KEDA HTTP Add-on Interceptor          |
                    |   (Queues requests, wakes scaled-to-zero)   |
                    +----------------------+----------------------+
                                           |
        +----------------+-----------------+------------------+
        |                |                                    |
        v                v                                    v
+---------------+ +---------------+                  +---------------+
|   hello_fn    | |  process_fn   |       ...        |   other_fn    |
|  Deployment   | |  Deployment   |                  |  Deployment   |
|   (scaled)    | |   (scaled)    |                  |   (scaled)    |
+---------------+ +---------------+                  +---------------+
        |                |                                    |
        v                v                                    v
+---------------+ +---------------+                  +---------------+
| HTTPScaled-   | | HTTPScaled-   |       ...        | HTTPScaled-   |
|    Object     | |    Object     |                  |    Object     |
+---------------+ +---------------+                  +---------------+
```

## Project Structure

```
apps/
+-- my-api/
|   +-- functions/
|       +-- __init__.py
|       +-- api.py          # HTTP functions
|       +-- workers.py      # Queue functions (optional)
|       +-- scheduled.py    # Cron functions (optional)

libs/
+-- k3sfn/                   # SDK
    +-- k3sfn/
    |   +-- __init__.py
    |   +-- decorators.py    # @serverless, @http_trigger, etc.
    |   +-- runtime.py       # FastAPI runtime
    |   +-- cli.py           # CLI tool
    |   +-- types.py         # Type definitions
    +-- pyproject.toml
```
