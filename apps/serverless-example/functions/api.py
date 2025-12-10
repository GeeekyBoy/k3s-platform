"""
HTTP-triggered API Functions

These functions handle HTTP requests and scale to zero when idle.
Each function becomes a separate Kubernetes deployment with its own
HTTPScaledObject for independent scaling.
"""

import os
from datetime import datetime
from typing import Any, Dict

from k3sfn import serverless, http_trigger, Request, Response


@serverless(
    memory="256Mi",
    cpu="100m",
    min_instances=0,  # Scale to zero when idle
    max_instances=10,
    timeout=30,
    visibility="public",  # Exposed via ingress to internet
)
@http_trigger(
    path="/api/hello",
    methods=["GET"],
)
async def hello_world(request: Request) -> Dict[str, Any]:
    """
    Simple hello world function.

    Access at: /api/hello?name=World
    Scales to zero when no requests for 5 minutes.
    Visibility: PUBLIC - accessible from internet via ingress.
    """
    name = request.query_params.get("name", "World")
    return {
        "message": f"Hello, {name}!",
        "timestamp": datetime.utcnow().isoformat(),
        "function": "hello_world",
    }


@serverless(
    memory="512Mi",  # More memory for data processing
    cpu="200m",
    min_instances=0,
    max_instances=20,
    timeout=60,
    visibility="internal",  # Accessible from any namespace in cluster
)
@http_trigger(
    path="/api/process",
    methods=["POST"],
)
async def process_data(request: Request) -> Dict[str, Any]:
    """
    Data processing function.

    Accepts JSON payload and processes it.
    Higher resource allocation for compute-intensive work.
    Visibility: INTERNAL - only accessible within the cluster.
    """
    body = request.body or {}

    # Simulate data processing
    items = body.get("items", [])
    processed = [item.upper() if isinstance(item, str) else item for item in items]

    return {
        "processed": processed,
        "count": len(processed),
        "timestamp": datetime.utcnow().isoformat(),
        "function": "process_data",
    }


@serverless(
    memory="1Gi",  # High memory for image/ML work
    cpu="500m",
    min_instances=0,
    max_instances=5,  # Limit due to resource usage
    timeout=120,
    visibility="restricted",  # Only accessible from specific pods
    allow_from_pods={"app": "fastapi"},  # Only FastAPI can call this
)
@http_trigger(
    path="/api/analyze",
    methods=["POST"],
)
async def analyze_content(request: Request) -> Dict[str, Any]:
    """
    Content analysis function.

    Simulates ML/AI content analysis with higher resource requirements.
    Limited max instances due to resource intensity.
    Visibility: RESTRICTED - only FastAPI pods can call this function.
    """
    body = request.body or {}
    content = body.get("content", "")

    # Simulate analysis
    word_count = len(content.split())
    char_count = len(content)

    return {
        "analysis": {
            "word_count": word_count,
            "char_count": char_count,
            "avg_word_length": char_count / word_count if word_count > 0 else 0,
        },
        "sentiment": "neutral",  # Would be ML-based in real implementation
        "timestamp": datetime.utcnow().isoformat(),
        "function": "analyze_content",
    }


@serverless(
    memory="128Mi",
    cpu="50m",
    min_instances=0,  # Scale to zero
    max_instances=10,
    timeout=10,
    visibility="public",
)
@http_trigger(
    path="/api/animal",
    methods=["GET"],
)
async def random_animal(request: Request) -> Dict[str, Any]:
    """
    Returns a random animal.

    Access at: /api/animal
    Scales to zero when idle.
    """
    import random

    animals = [
        {"name": "Dog", "emoji": "🐕", "sound": "Woof!"},
        {"name": "Cat", "emoji": "🐈", "sound": "Meow!"},
        {"name": "Cow", "emoji": "🐄", "sound": "Moo!"},
        {"name": "Pig", "emoji": "🐷", "sound": "Oink!"},
        {"name": "Lion", "emoji": "🦁", "sound": "Roar!"},
        {"name": "Elephant", "emoji": "🐘", "sound": "Trumpet!"},
        {"name": "Duck", "emoji": "🦆", "sound": "Quack!"},
        {"name": "Owl", "emoji": "🦉", "sound": "Hoot!"},
        {"name": "Fox", "emoji": "🦊", "sound": "Ring-ding-ding!"},
        {"name": "Penguin", "emoji": "🐧", "sound": "Honk!"},
    ]

    animal = random.choice(animals)
    return {
        "animal": animal,
        "timestamp": datetime.utcnow().isoformat(),
        "function": "random_animal",
    }


@serverless(
    memory="256Mi",
    cpu="100m",
    min_instances=1,  # Always keep at least 1 instance (no cold start)
    max_instances=50,
    timeout=10,
    visibility="public",  # Health checks need to be accessible
)
@http_trigger(
    path="/api/health",
    methods=["GET"],
)
async def health_check(request: Request) -> Dict[str, Any]:
    """
    Health check endpoint.

    Keeps min_instances=1 to avoid cold starts for critical health checks.
    This endpoint is used by load balancers and monitoring.
    Visibility: PUBLIC - accessible from internet for health checks.
    """
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "environment": os.getenv("ENVIRONMENT", "production"),
        "version": os.getenv("APP_VERSION", "1.0.0"),
    }
