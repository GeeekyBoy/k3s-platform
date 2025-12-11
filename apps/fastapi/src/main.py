"""
FastAPI Application with Valkey Integration
Supports Sentinel-based HA connection
"""

import os
import asyncio
import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Optional

from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
import valkey.asyncio as valkey
from valkey.asyncio.sentinel import Sentinel

# Logging configuration
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Helper function to parse port from env (handles Kubernetes service discovery format)
def parse_port(env_var: str, default: int) -> int:
    """Parse port from environment variable.

    Handles Kubernetes service discovery format like 'tcp://10.43.27.255:6379'
    as well as plain port numbers.
    """
    value = os.getenv(env_var, str(default))
    if value.startswith("tcp://"):
        # Kubernetes service discovery format: tcp://ip:port
        return int(value.split(":")[-1])
    return int(value)

# Environment configuration
VALKEY_SENTINEL_ENABLED = os.getenv("VALKEY_SENTINEL_ENABLED", "true").lower() == "true"
VALKEY_SENTINEL_HOST = os.getenv("VALKEY_SENTINEL_HOST", "valkey")
VALKEY_SENTINEL_PORT = parse_port("VALKEY_SENTINEL_PORT", 26379)
VALKEY_SENTINEL_MASTER = os.getenv("VALKEY_SENTINEL_MASTER", "myprimary")
VALKEY_HOST = os.getenv("VALKEY_HOST", "valkey")
VALKEY_PORT = parse_port("VALKEY_PORT", 6379)
VALKEY_PASSWORD = os.getenv("VALKEY_PASSWORD", "")
VALKEY_DB = parse_port("VALKEY_DB", 0)

# Global connection pool
valkey_pool: Optional[valkey.ConnectionPool] = None
sentinel: Optional[Sentinel] = None


async def get_valkey_connection():
    """Get Valkey connection - uses Sentinel if enabled"""
    global valkey_pool, sentinel
    
    if VALKEY_SENTINEL_ENABLED:
        if sentinel is None:
            logger.info(f"Connecting to Valkey via Sentinel at {VALKEY_SENTINEL_HOST}:{VALKEY_SENTINEL_PORT}")
            sentinel = Sentinel(
                [(VALKEY_SENTINEL_HOST, VALKEY_SENTINEL_PORT)],
                socket_timeout=5.0,
                password=VALKEY_PASSWORD if VALKEY_PASSWORD else None,
                sentinel_kwargs={"password": VALKEY_PASSWORD} if VALKEY_PASSWORD else None
            )
        # Get master connection from Sentinel
        return sentinel.master_for(
            VALKEY_SENTINEL_MASTER,
            password=VALKEY_PASSWORD if VALKEY_PASSWORD else None,
            db=VALKEY_DB
        )
    else:
        if valkey_pool is None:
            logger.info(f"Connecting to Valkey directly at {VALKEY_HOST}:{VALKEY_PORT}")
            valkey_pool = valkey.ConnectionPool(
                host=VALKEY_HOST,
                port=VALKEY_PORT,
                password=VALKEY_PASSWORD if VALKEY_PASSWORD else None,
                db=VALKEY_DB,
                decode_responses=True,
                max_connections=10
            )
        return valkey.Valkey(connection_pool=valkey_pool)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan manager"""
    logger.info("Starting application...")
    
    # Test Valkey connection on startup
    try:
        client = await get_valkey_connection()
        await client.ping()
        logger.info("Valkey connection successful")
    except Exception as e:
        logger.warning(f"Valkey not available on startup: {e}")
    
    yield
    
    # Cleanup on shutdown
    logger.info("Shutting down...")
    global valkey_pool, sentinel
    if valkey_pool:
        await valkey_pool.disconnect()
    if sentinel:
        # Sentinel cleanup
        pass


# FastAPI app initialization
app = FastAPI(
    title="K3s Platform API",
    description="FastAPI service with Valkey HA integration",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models
class HealthResponse(BaseModel):
    status: str
    timestamp: str
    valkey_connected: bool
    version: str = "1.0.0"


class CacheItem(BaseModel):
    value: str
    ttl: Optional[int] = None  # TTL in seconds


class CacheResponse(BaseModel):
    key: str
    value: Optional[str]
    exists: bool


class QueueMessage(BaseModel):
    message: str


class StatsResponse(BaseModel):
    keys_count: int
    memory_used: str
    connected_clients: int
    uptime_seconds: int


# Health endpoints
@app.get("/health", response_model=HealthResponse, tags=["Health"])
async def health_check():
    """Overall health check"""
    valkey_ok = False
    try:
        client = await get_valkey_connection()
        await client.ping()
        valkey_ok = True
    except Exception:
        pass
    
    return HealthResponse(
        status="healthy" if valkey_ok else "degraded",
        timestamp=datetime.utcnow().isoformat(),
        valkey_connected=valkey_ok
    )


@app.get("/ready", tags=["Health"])
async def readiness_check():
    """Kubernetes readiness probe"""
    try:
        client = await get_valkey_connection()
        await client.ping()
        return {"ready": True}
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"Not ready: {e}")


@app.get("/live", tags=["Health"])
async def liveness_check():
    """Kubernetes liveness probe"""
    return {"alive": True}


# Cache operations
@app.post("/cache/{key}", response_model=CacheResponse, tags=["Cache"])
async def set_cache(key: str, item: CacheItem):
    """Set a cache item"""
    try:
        client = await get_valkey_connection()
        if item.ttl:
            await client.setex(key, item.ttl, item.value)
        else:
            await client.set(key, item.value)
        return CacheResponse(key=key, value=item.value, exists=True)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/cache/{key}", response_model=CacheResponse, tags=["Cache"])
async def get_cache(key: str):
    """Get a cache item"""
    try:
        client = await get_valkey_connection()
        value = await client.get(key)
        return CacheResponse(key=key, value=value, exists=value is not None)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/cache/{key}", tags=["Cache"])
async def delete_cache(key: str):
    """Delete a cache item"""
    try:
        client = await get_valkey_connection()
        deleted = await client.delete(key)
        return {"key": key, "deleted": deleted > 0}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Queue operations (for KEDA scaling demo)
@app.post("/queue/{name}", tags=["Queue"])
async def push_to_queue(name: str, message: QueueMessage):
    """Push message to queue (triggers KEDA scaling)"""
    try:
        client = await get_valkey_connection()
        length = await client.rpush(f"queue:{name}", message.message)
        return {"queue": name, "message": message.message, "length": length}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/queue/{name}", tags=["Queue"])
async def pop_from_queue(name: str):
    """Pop message from queue"""
    try:
        client = await get_valkey_connection()
        message = await client.lpop(f"queue:{name}")
        length = await client.llen(f"queue:{name}")
        return {"queue": name, "message": message, "remaining": length}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/queue/{name}/length", tags=["Queue"])
async def get_queue_length(name: str):
    """Get queue length (used by KEDA scaler)"""
    try:
        client = await get_valkey_connection()
        length = await client.llen(f"queue:{name}")
        return {"queue": name, "length": length}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Background task demo
async def process_task(task_id: str, data: str):
    """Simulated background task"""
    logger.info(f"Processing task {task_id}: {data}")
    await asyncio.sleep(2)  # Simulate work
    
    try:
        client = await get_valkey_connection()
        await client.set(f"task:{task_id}:status", "completed")
        await client.set(f"task:{task_id}:result", f"Processed: {data}")
        logger.info(f"Task {task_id} completed")
    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}")


@app.post("/tasks", tags=["Tasks"])
async def create_task(data: str, background_tasks: BackgroundTasks):
    """Create a background task"""
    import uuid
    task_id = str(uuid.uuid4())[:8]
    
    try:
        client = await get_valkey_connection()
        await client.set(f"task:{task_id}:status", "pending")
    except Exception:
        pass
    
    background_tasks.add_task(process_task, task_id, data)
    return {"task_id": task_id, "status": "pending"}


@app.get("/tasks/{task_id}", tags=["Tasks"])
async def get_task_status(task_id: str):
    """Get task status"""
    try:
        client = await get_valkey_connection()
        status = await client.get(f"task:{task_id}:status")
        result = await client.get(f"task:{task_id}:result")
        return {"task_id": task_id, "status": status or "unknown", "result": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Stats endpoint
@app.get("/stats", response_model=StatsResponse, tags=["Stats"])
async def get_stats():
    """Get Valkey stats"""
    try:
        client = await get_valkey_connection()
        info = await client.info()
        keys = await client.dbsize()
        
        return StatsResponse(
            keys_count=keys,
            memory_used=info.get("used_memory_human", "unknown"),
            connected_clients=info.get("connected_clients", 0),
            uptime_seconds=info.get("uptime_in_seconds", 0)
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Sentinel info (when using HA mode)
@app.get("/sentinel/info", tags=["Sentinel"])
async def get_sentinel_info():
    """Get Sentinel master info"""
    if not VALKEY_SENTINEL_ENABLED:
        return {"sentinel_enabled": False}
    
    try:
        global sentinel
        if sentinel is None:
            await get_valkey_connection()
        
        master_info = await sentinel.discover_master(VALKEY_SENTINEL_MASTER)
        slaves_info = await sentinel.discover_slaves(VALKEY_SENTINEL_MASTER)
        
        return {
            "sentinel_enabled": True,
            "master": {"host": master_info[0], "port": master_info[1]},
            "replicas": [{"host": s[0], "port": s[1]} for s in slaves_info]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# Root endpoint
@app.get("/", tags=["Root"])
async def root():
    """API root"""
    return {
        "name": "K3s Platform API",
        "version": "1.0.0",
        "docs": "/docs",
        "health": "/health"
    }


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8000,
        reload=os.getenv("ENV", "production") == "development"
    )
