"""
Type definitions for K3s Gateway configuration.

These dataclasses represent the gateway section of apps.yaml v2.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class RouteTimeoutsConfig:
    """Timeout configuration for a gateway route."""
    connect: str = "10s"
    server: str = "180s"
    client: str = "180s"

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "RouteTimeoutsConfig":
        if not data:
            return cls()
        return cls(
            connect=data.get("connect", "10s"),
            server=data.get("server", "180s"),
            client=data.get("client", "180s"),
        )


@dataclass
class RouteRateLimitConfig:
    """Per-route rate limiting configuration."""
    requests_per_second: int = 100
    burst: int = 200

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["RouteRateLimitConfig"]:
        if not data:
            return None
        return cls(
            requests_per_second=data.get("requests_per_second", 100),
            burst=data.get("burst", 200),
        )


@dataclass
class RouteAuthConfig:
    """Authentication configuration for a route."""
    enabled: bool = False
    type: str = "none"  # "none", "basic", "bearer", "api_key"

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["RouteAuthConfig"]:
        if not data:
            return None
        return cls(
            enabled=data.get("enabled", False),
            type=data.get("type", "none"),
        )


@dataclass
class GatewayRoute:
    """A route mapping an external path to an internal service."""
    path: str
    service: str
    port: int = 80
    strip_prefix: bool = False
    rewrite_to: Optional[str] = None
    methods: Optional[List[str]] = None
    timeouts: RouteTimeoutsConfig = field(default_factory=RouteTimeoutsConfig)
    rate_limit: Optional[RouteRateLimitConfig] = None
    auth: Optional[RouteAuthConfig] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "GatewayRoute":
        return cls(
            path=data["path"],
            service=data["service"],
            port=data.get("port", 80),
            strip_prefix=data.get("strip_prefix", False),
            rewrite_to=data.get("rewrite_to"),
            methods=data.get("methods"),
            timeouts=RouteTimeoutsConfig.from_dict(data.get("timeouts")),
            rate_limit=RouteRateLimitConfig.from_dict(data.get("rate_limit")),
            auth=RouteAuthConfig.from_dict(data.get("auth")),
        )

    @property
    def service_name(self) -> str:
        """Extract service name from service reference (e.g., 'fastapi.apps' -> 'fastapi')."""
        return self.service.split(".")[0]

    @property
    def service_namespace(self) -> str:
        """Extract namespace from service reference (e.g., 'fastapi.apps' -> 'apps')."""
        parts = self.service.split(".")
        return parts[1] if len(parts) > 1 else "apps"


@dataclass
class RateLimitConfig:
    """Global rate limiting configuration."""
    enabled: bool = False
    requests_per_second: int = 100
    burst: int = 200

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "RateLimitConfig":
        if not data:
            return cls()
        return cls(
            enabled=data.get("enabled", False),
            requests_per_second=data.get("requests_per_second", 100),
            burst=data.get("burst", 200),
        )


@dataclass
class CorsConfig:
    """Global CORS configuration."""
    enabled: bool = True
    allow_origins: List[str] = field(default_factory=lambda: ["*"])
    allow_methods: List[str] = field(default_factory=lambda: ["GET", "POST", "PUT", "DELETE", "OPTIONS"])
    allow_headers: List[str] = field(default_factory=lambda: ["*"])
    expose_headers: List[str] = field(default_factory=list)
    max_age: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "CorsConfig":
        if not data:
            return cls()
        return cls(
            enabled=data.get("enabled", True),
            allow_origins=data.get("allow_origins", ["*"]),
            allow_methods=data.get("allow_methods", ["GET", "POST", "PUT", "DELETE", "OPTIONS"]),
            allow_headers=data.get("allow_headers", ["*"]),
            expose_headers=data.get("expose_headers", []),
            max_age=data.get("max_age"),
        )


@dataclass
class WafConfig:
    """Web Application Firewall configuration."""
    enabled: bool = False
    rules: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "WafConfig":
        if not data:
            return cls()
        return cls(
            enabled=data.get("enabled", False),
            rules=data.get("rules", []),
        )


@dataclass
class GatewayConfig:
    """Complete gateway configuration from apps.yaml."""
    routes: List[GatewayRoute] = field(default_factory=list)
    rate_limit: RateLimitConfig = field(default_factory=RateLimitConfig)
    cors: CorsConfig = field(default_factory=CorsConfig)
    waf: WafConfig = field(default_factory=WafConfig)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "GatewayConfig":
        if not data:
            return cls()
        routes = [GatewayRoute.from_dict(r) for r in data.get("routes", [])]
        return cls(
            routes=routes,
            rate_limit=RateLimitConfig.from_dict(data.get("rate_limit")),
            cors=CorsConfig.from_dict(data.get("cors")),
            waf=WafConfig.from_dict(data.get("waf")),
        )

    def get_routes_for_service(self, service_name: str) -> List[GatewayRoute]:
        """Get all routes for a specific service."""
        return [r for r in self.routes if r.service_name == service_name]
