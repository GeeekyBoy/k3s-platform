"""
Runtime for K3s Functions

Creates a FastAPI application that routes requests to decorated functions.
Each function runs in its own pod with a different entrypoint.
"""

import asyncio
import inspect
import logging
import os
import uuid
from datetime import datetime
from typing import Any, Callable, Dict, Optional

from .decorators import FunctionRegistry
from .types import Context, FunctionMetadata, Request, Response, TriggerType

logger = logging.getLogger(__name__)


def create_app(
    title: str = "K3s Functions",
    version: str = "1.0.0",
    function_filter: Optional[str] = None,
):
    """
    Create a FastAPI application for running functions.

    Args:
        title: API title
        version: API version
        function_filter: If set, only run this specific function (for single-function pods)

    Returns:
        FastAPI application instance
    """
    try:
        from fastapi import FastAPI, HTTPException, Request as FastAPIRequest
        from fastapi.middleware.cors import CORSMiddleware
        from fastapi.responses import JSONResponse
    except ImportError:
        raise ImportError("FastAPI is required. Install with: pip install fastapi uvicorn")

    app = FastAPI(title=title, version=version)

    # Add CORS middleware
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # Get target function from environment or parameter
    target_function = function_filter or os.getenv("K3SFN_FUNCTION")

    # Health endpoints
    @app.get("/health")
    async def health():
        return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

    @app.get("/ready")
    async def ready():
        return {"ready": True}

    @app.get("/live")
    async def live():
        return {"alive": True}

    # Function info endpoint
    @app.get("/_functions")
    async def list_functions():
        functions = FunctionRegistry.get_all()
        return {
            "functions": [
                {
                    "name": f.name,
                    "trigger_type": f.trigger_type.value,
                    "path": f.http_trigger.path if f.http_trigger else None,
                    "methods": f.http_trigger.methods if f.http_trigger else None,
                }
                for f in functions.values()
                if target_function is None or f.name == target_function
            ]
        }

    # Register HTTP-triggered functions
    functions = FunctionRegistry.get_all()

    for func_meta in functions.values():
        if target_function and func_meta.name != target_function:
            continue

        if func_meta.trigger_type == TriggerType.HTTP and func_meta.http_trigger:
            _register_http_function(app, func_meta)

    return app


def _register_http_function(app: Any, func_meta: FunctionMetadata) -> None:
    """Register an HTTP-triggered function with FastAPI"""
    from fastapi import Request as FastAPIRequest
    from fastapi.responses import JSONResponse

    http_spec = func_meta.http_trigger
    if not http_spec:
        return

    path = http_spec.path
    methods = http_spec.methods

    async def handler(request: FastAPIRequest) -> JSONResponse:
        """Generic handler that invokes the function"""
        invocation_id = str(uuid.uuid4())[:8]

        # Build Request object
        body = None
        if request.method in ["POST", "PUT", "PATCH"]:
            try:
                body = await request.json()
            except Exception:
                body = await request.body()

        req = Request(
            method=request.method,
            path=str(request.url.path),
            headers=dict(request.headers),
            query_params=dict(request.query_params),
            body=body,
            path_params=dict(request.path_params),
        )

        # Build Context
        ctx = Context(
            function_name=func_meta.name,
            invocation_id=invocation_id,
            timestamp=datetime.utcnow().isoformat(),
            timeout_remaining=func_meta.timeout,
            environment=dict(os.environ),
        )

        try:
            # Call the function
            result = await _invoke_function(func_meta.handler, req, ctx)

            # Handle different return types
            if isinstance(result, Response):
                return JSONResponse(
                    content=result.body,
                    status_code=result.status_code,
                    headers=result.headers,
                )
            elif isinstance(result, dict):
                return JSONResponse(content=result)
            elif result is None:
                return JSONResponse(content={"status": "ok"})
            else:
                return JSONResponse(content={"result": str(result)})

        except Exception as e:
            logger.exception(f"Function {func_meta.name} failed: {e}")
            return JSONResponse(
                content={"error": str(e), "function": func_meta.name},
                status_code=500,
            )

    # Create a unique handler for this function
    handler.__name__ = f"handle_{func_meta.name}"

    # Register route for each method
    for method in methods:
        app.add_api_route(
            path,
            handler,
            methods=[method],
            name=f"{func_meta.name}_{method.lower()}",
            tags=[func_meta.name],
        )

    # Also register with path parameters for catch-all
    if not path.endswith("/{path:path}"):
        catch_all_path = path.rstrip("/") + "/{path:path}"
        for method in methods:
            app.add_api_route(
                catch_all_path,
                handler,
                methods=[method],
                name=f"{func_meta.name}_{method.lower()}_catchall",
                tags=[func_meta.name],
            )


async def _invoke_function(func: Callable, request: Request, context: Context) -> Any:
    """Invoke a function with proper argument handling"""
    sig = inspect.signature(func)
    params = list(sig.parameters.keys())

    # Determine what arguments to pass based on function signature
    kwargs: Dict[str, Any] = {}

    for param in params:
        if param in ("request", "req"):
            kwargs[param] = request
        elif param in ("context", "ctx"):
            kwargs[param] = context
        elif param == "body":
            kwargs[param] = request.body

    # Call the function
    if not params:
        result = func()
    elif len(params) == 1 and params[0] not in kwargs:
        result = func(request)
    else:
        result = func(**kwargs)

    # Always await if result is a coroutine (handles wrapped async functions)
    if asyncio.iscoroutine(result):
        return await result
    return result


def run_function(module_path: str, function_name: Optional[str] = None):
    """
    Run a function module as a standalone service.

    This is the entrypoint for function pods.

    Args:
        module_path: Python module path to import (e.g., "functions.hello")
        function_name: Specific function to run (optional)
    """
    import importlib
    import sys

    try:
        import uvicorn
    except ImportError:
        raise ImportError("uvicorn is required. Install with: pip install uvicorn")

    # Add current directory to path
    sys.path.insert(0, os.getcwd())

    # Import the module to register functions
    try:
        module = importlib.import_module(module_path)
        logger.info(f"Loaded module: {module_path}")
    except ImportError as e:
        logger.error(f"Failed to import module {module_path}: {e}")
        raise

    # Get function to run from environment or parameter
    target = function_name or os.getenv("K3SFN_FUNCTION")

    # Create and run app
    app = create_app(
        title=f"Function: {target or 'all'}",
        function_filter=target,
    )

    # Get port from environment
    port = int(os.getenv("PORT", "8080"))
    host = os.getenv("HOST", "0.0.0.0")

    logger.info(f"Starting function server on {host}:{port}")
    uvicorn.run(app, host=host, port=port)


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m k3sfn.runtime <module_path> [function_name]")
        sys.exit(1)

    module_path = sys.argv[1]
    function_name = sys.argv[2] if len(sys.argv) > 2 else None

    run_function(module_path, function_name)
