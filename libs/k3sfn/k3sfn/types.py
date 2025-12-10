"""
Type definitions for K3s Functions SDK
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Callable
from enum import Enum


class TriggerType(Enum):
    HTTP = "http"
    QUEUE = "queue"
    SCHEDULE = "schedule"
    EVENT = "event"


class Visibility(Enum):
    """Access control visibility for functions"""
    PUBLIC = "public"          # Exposed via ingress to internet
    INTERNAL = "internal"      # Only accessible within cluster (any namespace)
    PRIVATE = "private"        # Only accessible within same namespace
    RESTRICTED = "restricted"  # Only accessible from specific pods/namespaces


@dataclass
class AccessRule:
    """Define who can access a restricted function"""
    namespaces: List[str] = field(default_factory=list)  # Allow from these namespaces
    pod_labels: Dict[str, str] = field(default_factory=dict)  # Allow pods with these labels
    service_accounts: List[str] = field(default_factory=list)  # Allow these service accounts


@dataclass
class ResourceSpec:
    """Resource specifications for a function"""
    memory: str = "256Mi"
    cpu: str = "100m"
    memory_limit: Optional[str] = None
    cpu_limit: Optional[str] = None

    def __post_init__(self):
        # Default limits to 2x requests if not specified
        if self.memory_limit is None:
            self.memory_limit = self.memory
        if self.cpu_limit is None:
            self.cpu_limit = self.cpu


@dataclass
class ScalingSpec:
    """Scaling specifications for a function"""
    min_instances: int = 0
    max_instances: int = 10
    target_pending_requests: int = 100
    cooldown_period: int = 300  # seconds
    scale_up_stabilization: int = 0  # seconds
    scale_down_stabilization: int = 300  # seconds


@dataclass
class HttpTriggerSpec:
    """HTTP trigger configuration"""
    path: str
    methods: List[str] = field(default_factory=lambda: ["GET", "POST"])
    auth: Optional[str] = None  # "none", "api_key", "jwt"
    cors: bool = True
    rate_limit: Optional[int] = None  # requests per minute


@dataclass
class QueueTriggerSpec:
    """Queue trigger configuration"""
    queue_name: str
    batch_size: int = 1
    visibility_timeout: int = 30


@dataclass
class ScheduleTriggerSpec:
    """Schedule trigger configuration (cron)"""
    cron: str
    timezone: str = "UTC"


@dataclass
class FunctionMetadata:
    """Complete function metadata extracted from decorators"""
    name: str
    handler: Callable
    module: str
    trigger_type: TriggerType
    resources: ResourceSpec
    scaling: ScalingSpec
    http_trigger: Optional[HttpTriggerSpec] = None
    queue_trigger: Optional[QueueTriggerSpec] = None
    schedule_trigger: Optional[ScheduleTriggerSpec] = None
    timeout: int = 30
    environment: Dict[str, str] = field(default_factory=dict)
    secrets: List[str] = field(default_factory=list)
    labels: Dict[str, str] = field(default_factory=dict)
    visibility: Visibility = Visibility.PRIVATE  # Default to private (secure by default)
    access_rules: Optional[AccessRule] = None  # For RESTRICTED visibility


@dataclass
class Request:
    """Incoming request object passed to HTTP functions"""
    method: str
    path: str
    headers: Dict[str, str]
    query_params: Dict[str, str]
    body: Any
    path_params: Dict[str, str] = field(default_factory=dict)

    @property
    def json(self) -> Any:
        """Get JSON body"""
        return self.body if isinstance(self.body, (dict, list)) else None


@dataclass
class Response:
    """Response object returned from functions"""
    body: Any
    status_code: int = 200
    headers: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def json(cls, data: Any, status_code: int = 200) -> "Response":
        """Create JSON response"""
        return cls(body=data, status_code=status_code)

    @classmethod
    def error(cls, message: str, status_code: int = 500) -> "Response":
        """Create error response"""
        return cls(body={"error": message}, status_code=status_code)


@dataclass
class Context:
    """Execution context passed to functions"""
    function_name: str
    invocation_id: str
    timestamp: str
    timeout_remaining: int
    environment: Dict[str, str] = field(default_factory=dict)


@dataclass
class QueueMessage:
    """Message received from queue trigger"""
    id: str
    body: Any
    receipt_handle: str
    attempt: int = 1
