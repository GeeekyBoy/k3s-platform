"""
Decorators for K3s Functions SDK

Similar to Firebase Functions, these decorators add metadata to functions
that is extracted at build time to generate Kubernetes manifests.
"""

import functools
import inspect
from typing import Any, Callable, Dict, List, Optional, TypeVar

from .types import (
    AccessRule,
    FunctionMetadata,
    HttpTriggerSpec,
    QueueTriggerSpec,
    ResourceSpec,
    ScalingSpec,
    ScheduleTriggerSpec,
    TriggerType,
    Visibility,
)

F = TypeVar("F", bound=Callable[..., Any])

# Global function registry
_registry: Dict[str, FunctionMetadata] = {}


class FunctionRegistry:
    """Registry of all decorated functions"""

    @staticmethod
    def get_all() -> Dict[str, FunctionMetadata]:
        """Get all registered functions"""
        return _registry.copy()

    @staticmethod
    def get(name: str) -> Optional[FunctionMetadata]:
        """Get function by name"""
        return _registry.get(name)

    @staticmethod
    def register(metadata: FunctionMetadata) -> None:
        """Register a function"""
        _registry[metadata.name] = metadata

    @staticmethod
    def clear() -> None:
        """Clear registry (for testing)"""
        _registry.clear()

    @staticmethod
    def list_names() -> List[str]:
        """List all function names"""
        return list(_registry.keys())


def serverless(
    _func: Optional[F] = None,
    *,
    memory: str = "256Mi",
    cpu: str = "100m",
    memory_limit: Optional[str] = None,
    cpu_limit: Optional[str] = None,
    min_instances: int = 0,
    max_instances: int = 10,
    timeout: int = 30,
    environment: Optional[Dict[str, str]] = None,
    secrets: Optional[List[str]] = None,
    labels: Optional[Dict[str, str]] = None,
    visibility: str = "private",
    allow_from_namespaces: Optional[List[str]] = None,
    allow_from_pods: Optional[Dict[str, str]] = None,
) -> Callable[[F], F]:
    """
    Mark a function as serverless with resource specifications.

    This is the base decorator that must be applied to all functions.
    It configures resource allocation, scaling behavior, and access control.

    Args:
        memory: Memory request (e.g., "256Mi", "1Gi")
        cpu: CPU request (e.g., "100m", "1")
        memory_limit: Memory limit (defaults to memory request)
        cpu_limit: CPU limit (defaults to cpu request)
        min_instances: Minimum replicas (0 for scale-to-zero)
        max_instances: Maximum replicas
        timeout: Function timeout in seconds
        environment: Environment variables
        secrets: Secret names to mount
        labels: Additional Kubernetes labels
        visibility: Access control level:
            - "public": Exposed via ingress to internet
            - "internal": Accessible from any namespace in cluster
            - "private": Only accessible within same namespace (default)
            - "restricted": Only accessible from specific pods/namespaces
        allow_from_namespaces: For restricted visibility, namespaces that can access
        allow_from_pods: For restricted visibility, pod labels that can access

    Example:
        # Public API endpoint
        @serverless(memory="256Mi", visibility="public")
        @http_trigger(path="/api/hello")
        async def hello(request):
            return {"message": "Hello!"}

        # Internal service (cluster-only)
        @serverless(memory="512Mi", visibility="internal")
        @http_trigger(path="/internal/process")
        async def process(request):
            return {"status": "processed"}

        # Private function (same namespace only)
        @serverless(memory="256Mi", visibility="private")
        @http_trigger(path="/private/data")
        async def get_data(request):
            return {"data": "secret"}

        # Restricted to specific pods
        @serverless(
            memory="256Mi",
            visibility="restricted",
            allow_from_pods={"app": "frontend"}
        )
        @http_trigger(path="/api/admin")
        async def admin(request):
            return {"admin": True}
    """

    def decorator(func: F) -> F:
        # Get or create function metadata
        if not hasattr(func, "_k3sfn_metadata"):
            func._k3sfn_metadata = {}  # type: ignore

        func._k3sfn_metadata["resources"] = ResourceSpec(  # type: ignore
            memory=memory,
            cpu=cpu,
            memory_limit=memory_limit,
            cpu_limit=cpu_limit,
        )
        func._k3sfn_metadata["scaling"] = ScalingSpec(  # type: ignore
            min_instances=min_instances,
            max_instances=max_instances,
        )
        func._k3sfn_metadata["timeout"] = timeout  # type: ignore
        func._k3sfn_metadata["environment"] = environment or {}  # type: ignore
        func._k3sfn_metadata["secrets"] = secrets or []  # type: ignore
        func._k3sfn_metadata["labels"] = labels or {}  # type: ignore
        func._k3sfn_metadata["module"] = func.__module__  # type: ignore
        func._k3sfn_metadata["name"] = func.__name__  # type: ignore

        # Access control
        func._k3sfn_metadata["visibility"] = Visibility(visibility)  # type: ignore

        # Build access rules for restricted visibility
        if visibility == "restricted" and (allow_from_namespaces or allow_from_pods):
            func._k3sfn_metadata["access_rules"] = AccessRule(  # type: ignore
                namespaces=allow_from_namespaces or [],
                pod_labels=allow_from_pods or {},
            )
        else:
            func._k3sfn_metadata["access_rules"] = None  # type: ignore

        # Finalize registration now that serverless decorator has been applied
        # This ensures visibility and all other metadata is captured
        _finalize_registration(func)

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        # Copy metadata to wrapper
        wrapper._k3sfn_metadata = func._k3sfn_metadata  # type: ignore
        return wrapper  # type: ignore

    if _func is not None:
        return decorator(_func)
    return decorator


def http_trigger(
    _func: Optional[F] = None,
    *,
    path: str = "/",
    methods: Optional[List[str]] = None,
    auth: Optional[str] = None,
    cors: bool = True,
    rate_limit: Optional[int] = None,
) -> Callable[[F], F]:
    """
    Configure HTTP trigger for a function.

    Args:
        path: URL path for the function (e.g., "/api/users")
        methods: Allowed HTTP methods (default: ["GET", "POST"])
        auth: Authentication method ("none", "api_key", "jwt")
        cors: Enable CORS headers
        rate_limit: Rate limit in requests per minute

    Example:
        @serverless(memory="256Mi")
        @http_trigger(path="/hello", methods=["GET"])
        async def hello(request):
            name = request.query_params.get("name", "World")
            return {"message": f"Hello, {name}!"}
    """

    def decorator(func: F) -> F:
        if not hasattr(func, "_k3sfn_metadata"):
            func._k3sfn_metadata = {}  # type: ignore

        func._k3sfn_metadata["trigger_type"] = TriggerType.HTTP  # type: ignore
        func._k3sfn_metadata["http_trigger"] = HttpTriggerSpec(  # type: ignore
            path=path,
            methods=methods or ["GET", "POST"],
            auth=auth,
            cors=cors,
            rate_limit=rate_limit,
        )

        # Don't register here - let serverless decorator handle registration
        # This ensures all metadata (including visibility) is captured

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        wrapper._k3sfn_metadata = func._k3sfn_metadata  # type: ignore
        return wrapper  # type: ignore

    if _func is not None:
        return decorator(_func)
    return decorator


def queue_trigger(
    _func: Optional[F] = None,
    *,
    queue_name: str,
    batch_size: int = 1,
    visibility_timeout: int = 30,
) -> Callable[[F], F]:
    """
    Configure queue trigger for a function.

    The function will be invoked when messages arrive in the queue.
    Uses Valkey/Redis lists for queue implementation.

    Args:
        queue_name: Name of the queue (Valkey list key)
        batch_size: Number of messages to process at once
        visibility_timeout: Time before message becomes visible again

    Example:
        @serverless(memory="512Mi")
        @queue_trigger(queue_name="tasks", batch_size=5)
        async def process_tasks(messages, context):
            for msg in messages:
                await process(msg)
    """

    def decorator(func: F) -> F:
        if not hasattr(func, "_k3sfn_metadata"):
            func._k3sfn_metadata = {}  # type: ignore

        func._k3sfn_metadata["trigger_type"] = TriggerType.QUEUE  # type: ignore
        func._k3sfn_metadata["queue_trigger"] = QueueTriggerSpec(  # type: ignore
            queue_name=queue_name,
            batch_size=batch_size,
            visibility_timeout=visibility_timeout,
        )

        # Don't register here - let serverless decorator handle registration

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        wrapper._k3sfn_metadata = func._k3sfn_metadata  # type: ignore
        return wrapper  # type: ignore

    if _func is not None:
        return decorator(_func)
    return decorator


def schedule_trigger(
    _func: Optional[F] = None,
    *,
    cron: str,
    timezone: str = "UTC",
) -> Callable[[F], F]:
    """
    Configure schedule trigger for a function.

    The function will be invoked on a schedule defined by a cron expression.

    Args:
        cron: Cron expression (e.g., "0 */5 * * *" for every 5 hours)
        timezone: Timezone for cron evaluation

    Example:
        @serverless(memory="256Mi")
        @schedule_trigger(cron="0 0 * * *")  # Daily at midnight
        async def daily_cleanup(context):
            await cleanup_old_data()
    """

    def decorator(func: F) -> F:
        if not hasattr(func, "_k3sfn_metadata"):
            func._k3sfn_metadata = {}  # type: ignore

        func._k3sfn_metadata["trigger_type"] = TriggerType.SCHEDULE  # type: ignore
        func._k3sfn_metadata["schedule_trigger"] = ScheduleTriggerSpec(  # type: ignore
            cron=cron,
            timezone=timezone,
        )

        # Don't register here - let serverless decorator handle registration

        @functools.wraps(func)
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            return func(*args, **kwargs)

        wrapper._k3sfn_metadata = func._k3sfn_metadata  # type: ignore
        return wrapper  # type: ignore

    if _func is not None:
        return decorator(_func)
    return decorator


def _finalize_registration(func: Callable) -> None:
    """Finalize function registration after all decorators are applied"""
    meta = getattr(func, "_k3sfn_metadata", {})

    # Ensure required fields have defaults
    resources = meta.get("resources", ResourceSpec())
    scaling = meta.get("scaling", ScalingSpec())
    trigger_type = meta.get("trigger_type", TriggerType.HTTP)

    metadata = FunctionMetadata(
        name=meta.get("name", func.__name__),
        handler=func,
        module=meta.get("module", func.__module__),
        trigger_type=trigger_type,
        resources=resources,
        scaling=scaling,
        http_trigger=meta.get("http_trigger"),
        queue_trigger=meta.get("queue_trigger"),
        schedule_trigger=meta.get("schedule_trigger"),
        timeout=meta.get("timeout", 30),
        environment=meta.get("environment", {}),
        secrets=meta.get("secrets", []),
        labels=meta.get("labels", {}),
        visibility=meta.get("visibility", Visibility.PRIVATE),
        access_rules=meta.get("access_rules"),
    )

    FunctionRegistry.register(metadata)
