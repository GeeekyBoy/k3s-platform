"""
K3s Gateway - Generate ingress manifests from apps.yaml gateway configuration.

This tool reads the gateway section from apps.yaml and generates Kubernetes
Ingress resources that route external paths to internal services.
"""

from .types import (
    GatewayConfig,
    GatewayRoute,
    RateLimitConfig,
    CorsConfig,
    WafConfig,
    RouteTimeoutsConfig,
    RouteAuthConfig,
)
from .generators import (
    generate_haproxy_ingress,
    generate_traefik_ingressroute,
    generate_all_manifests,
)

__version__ = "0.1.0"
__all__ = [
    "GatewayConfig",
    "GatewayRoute",
    "RateLimitConfig",
    "CorsConfig",
    "WafConfig",
    "RouteTimeoutsConfig",
    "RouteAuthConfig",
    "generate_haproxy_ingress",
    "generate_traefik_ingressroute",
    "generate_all_manifests",
]
