"""
K3s Functions SDK - Firebase-style serverless functions for Kubernetes

Usage:
    from k3sfn import serverless, http_trigger, queue_trigger, schedule_trigger

    @serverless(
        memory="256Mi",
        cpu="100m",
        max_instances=10,
        min_instances=0,
        timeout=30
    )
    @http_trigger(path="/hello", methods=["GET", "POST"])
    async def hello_world(request):
        return {"message": "Hello, World!"}
"""

from .decorators import (
    serverless,
    http_trigger,
    queue_trigger,
    schedule_trigger,
    FunctionRegistry,
)
from .runtime import create_app
from .types import Request, Response, Context

__version__ = "0.1.0"
__all__ = [
    "serverless",
    "http_trigger",
    "queue_trigger",
    "schedule_trigger",
    "create_app",
    "Request",
    "Response",
    "Context",
    "FunctionRegistry",
]
