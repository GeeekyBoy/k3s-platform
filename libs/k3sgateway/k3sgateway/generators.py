"""
Kubernetes manifest generators for K3s Gateway.

Generates Ingress resources for HAProxy (GCP) and Traefik (local/dev).
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .types import GatewayConfig, GatewayRoute, CorsConfig


def generate_haproxy_ingress(
    route: GatewayRoute,
    gateway_config: GatewayConfig,
    domain: Optional[str] = None,
    tls_enabled: bool = False,
    tls_secret: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Generate HAProxy Ingress resource for a gateway route.

    HAProxy routes external traffic to internal services. For KEDA-managed
    services, the route should point to the KEDA interceptor with Host header
    rewriting. For regular services, it routes directly.

    Args:
        route: Gateway route configuration
        gateway_config: Global gateway configuration
        domain: Ingress host domain
        tls_enabled: Whether to enable TLS
        tls_secret: Name of TLS secret

    Returns:
        Kubernetes Ingress manifest as dict
    """
    # Create a unique name for this route based on path
    route_name = route.path.strip("/").replace("/", "-") or "root"
    name = f"gateway-{route_name}"

    # Build annotations
    annotations: Dict[str, str] = {
        "haproxy-ingress.github.io/timeout-connect": route.timeouts.connect,
        "haproxy-ingress.github.io/timeout-server": route.timeouts.server,
        "haproxy-ingress.github.io/timeout-client": route.timeouts.client,
        "haproxy-ingress.github.io/timeout-queue": route.timeouts.server,
    }

    # Add retry configuration
    annotations["haproxy-ingress.github.io/retry-on"] = "conn-failure,empty-response,response-timeout"
    annotations["haproxy-ingress.github.io/retries"] = "3"

    # Rate limiting
    rate_limit = route.rate_limit or (
        gateway_config.rate_limit if gateway_config.rate_limit.enabled else None
    )
    if rate_limit:
        rps = rate_limit.requests_per_second
        annotations["haproxy-ingress.github.io/limit-rps"] = str(rps)
        annotations["haproxy-ingress.github.io/limit-connections"] = str(rate_limit.burst)

    # CORS configuration for HAProxy
    if gateway_config.cors.enabled:
        cors = gateway_config.cors
        # HAProxy Ingress CORS annotations
        annotations["haproxy-ingress.github.io/cors-enable"] = "true"
        annotations["haproxy-ingress.github.io/cors-allow-origin"] = ",".join(cors.allow_origins) if cors.allow_origins else "*"
        annotations["haproxy-ingress.github.io/cors-allow-methods"] = ",".join(cors.allow_methods)
        annotations["haproxy-ingress.github.io/cors-allow-headers"] = ",".join(cors.allow_headers)
        if cors.expose_headers:
            annotations["haproxy-ingress.github.io/cors-expose-headers"] = ",".join(cors.expose_headers)
        if cors.max_age:
            annotations["haproxy-ingress.github.io/cors-max-age"] = str(cors.max_age)

    # Determine the target service
    # For KEDA-managed services, we need to route through the interceptor
    # and set the Host header for proper routing
    service_name = route.service_name
    service_namespace = route.service_namespace
    service_port = route.port

    # Build config-backend annotation for Host header rewriting
    # This tells HAProxy to rewrite Host header for KEDA routing
    routing_host = f"{service_name}.{service_namespace}"
    config_backend = f"http-request set-header Host {routing_host}\n"

    # Handle path stripping
    if route.strip_prefix:
        # Strip the path prefix before forwarding
        rewrite_path = route.rewrite_to or "/"
        config_backend += f"http-request replace-path {route.path}(.*) {rewrite_path}\\1\n"

    annotations["haproxy-ingress.github.io/config-backend"] = config_backend

    # Build ingress spec
    ingress: Dict[str, Any] = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": name,
            "namespace": "haproxy-ingress",  # Gateway ingresses go in haproxy-ingress namespace
            "labels": {
                "k3sgateway.io/route": route_name,
                "k3sgateway.io/component": "gateway",
            },
            "annotations": annotations,
        },
        "spec": {
            "ingressClassName": "haproxy",
            "rules": [],
        },
    }

    # Build the HTTP rule
    http_rule: Dict[str, Any] = {
        "http": {
            "paths": [
                {
                    "path": route.path,
                    "pathType": "Prefix",
                    "backend": {
                        "service": {
                            "name": f"keda-route-{route_name}",
                            "port": {"number": 8080},
                        },
                    },
                }
            ],
        },
    }

    # Add host if domain is specified
    if domain:
        http_rule["host"] = domain
        ingress["spec"]["rules"].append(http_rule)
    else:
        # Wildcard - no host specified
        ingress["spec"]["rules"].append(http_rule)

    # Add TLS if enabled
    if tls_enabled and tls_secret:
        tls_config = {"secretName": tls_secret}
        if domain:
            tls_config["hosts"] = [domain]
        ingress["spec"]["tls"] = [tls_config]

    return ingress


def generate_haproxy_route_service(route: GatewayRoute) -> Dict[str, Any]:
    """
    Generate ExternalName service for HAProxy gateway route.

    Each route gets its own ExternalName service pointing to KEDA interceptor.
    This prevents HAProxy from merging backends (which would break per-path
    Host header rewriting).

    Args:
        route: Gateway route configuration

    Returns:
        Kubernetes Service manifest as dict
    """
    route_name = route.path.strip("/").replace("/", "-") or "root"

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"keda-route-{route_name}",
            "namespace": "haproxy-ingress",
            "labels": {
                "k3sgateway.io/route": route_name,
                "k3sgateway.io/component": "keda-route",
            },
        },
        "spec": {
            "type": "ExternalName",
            "externalName": "keda-add-ons-http-interceptor-proxy.keda.svc.cluster.local",
            "ports": [
                {
                    "port": 8080,
                    "targetPort": 8080,
                    "protocol": "TCP",
                }
            ],
        },
    }


def generate_traefik_ingressroute(
    gateway_config: GatewayConfig,
    namespace: str = "apps",
    domain: Optional[str] = None,
) -> tuple[Optional[Dict[str, Any]], List[Dict[str, Any]], Optional[Dict[str, Any]]]:
    """
    Generate Traefik IngressRoute for all gateway routes.

    For local/dev environments using Traefik.

    Args:
        gateway_config: Complete gateway configuration
        namespace: Namespace for the IngressRoute
        domain: Ingress host domain

    Returns:
        Tuple of (IngressRoute, list of Middlewares, ExternalName Service)
    """
    if not gateway_config.routes:
        return None, [], None

    routes: List[Dict[str, Any]] = []
    middlewares: List[Dict[str, Any]] = []

    for route in gateway_config.routes:
        route_name = route.path.strip("/").replace("/", "-") or "root"
        service_name = route.service_name
        service_namespace = route.service_namespace
        routing_host = f"{service_name}.{service_namespace}"

        # Generate host rewrite middleware
        middleware_name = f"gateway-{route_name}-host-rewrite"
        middleware = {
            "apiVersion": "traefik.io/v1alpha1",
            "kind": "Middleware",
            "metadata": {
                "name": middleware_name,
                "namespace": namespace,
                "labels": {
                    "k3sgateway.io/route": route_name,
                    "k3sgateway.io/component": "middleware",
                },
            },
            "spec": {
                "headers": {
                    "customRequestHeaders": {
                        "Host": routing_host,
                    },
                },
            },
        }
        middlewares.append(middleware)

        # Build route match
        match = f"PathPrefix(`{route.path}`)"
        if domain:
            match = f"Host(`{domain}`) && {match}"

        # Build middlewares list for the route
        route_middlewares = [{"name": middleware_name, "namespace": namespace}]

        # Add rate limiting middleware if configured
        ratelimit_mw = generate_ratelimit_middleware(route, gateway_config, namespace)
        if ratelimit_mw:
            middlewares.append(ratelimit_mw)
            route_middlewares.append({"name": ratelimit_mw["metadata"]["name"], "namespace": namespace})

        # Add basic auth middleware if configured
        auth_mw = generate_basicauth_middleware(route, namespace)
        if auth_mw:
            middlewares.append(auth_mw)
            route_middlewares.append({"name": auth_mw["metadata"]["name"], "namespace": namespace})

        # Add strip prefix middleware if needed
        if route.strip_prefix:
            strip_middleware_name = f"gateway-{route_name}-strip-prefix"
            strip_middleware = {
                "apiVersion": "traefik.io/v1alpha1",
                "kind": "Middleware",
                "metadata": {
                    "name": strip_middleware_name,
                    "namespace": namespace,
                    "labels": {
                        "k3sgateway.io/route": route_name,
                        "k3sgateway.io/component": "middleware",
                    },
                },
                "spec": {
                    "stripPrefix": {
                        "prefixes": [route.path],
                    },
                },
            }
            middlewares.append(strip_middleware)
            route_middlewares.append({"name": strip_middleware_name, "namespace": namespace})

        routes.append({
            "match": match,
            "kind": "Rule",
            "services": [
                {
                    "name": "keda-interceptor-proxy",
                    "port": 8080,
                }
            ],
            "middlewares": route_middlewares,
        })

    # Build IngressRoute
    ingress_route = {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "IngressRoute",
        "metadata": {
            "name": "gateway-routes",
            "namespace": namespace,
            "labels": {
                "k3sgateway.io/component": "gateway",
            },
        },
        "spec": {
            "entryPoints": ["web", "websecure"],
            "routes": routes,
        },
    }

    # Generate ExternalName service for KEDA cross-namespace access
    external_svc = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": "keda-interceptor-proxy",
            "namespace": namespace,
            "labels": {
                "k3sgateway.io/component": "keda-proxy",
            },
        },
        "spec": {
            "type": "ExternalName",
            "externalName": "keda-add-ons-http-interceptor-proxy.keda.svc.cluster.local",
            "ports": [
                {
                    "port": 8080,
                    "targetPort": 8080,
                    "protocol": "TCP",
                }
            ],
        },
    }

    return ingress_route, middlewares, external_svc


def generate_ratelimit_middleware(
    route: GatewayRoute,
    gateway_config: GatewayConfig,
    namespace: str = "apps",
) -> Optional[Dict[str, Any]]:
    """
    Generate Traefik RateLimit Middleware for a route.

    Args:
        route: Gateway route configuration
        gateway_config: Global gateway configuration
        namespace: Namespace for the middleware

    Returns:
        Traefik RateLimit Middleware manifest or None if no rate limiting configured
    """
    rate_limit = route.rate_limit or (
        gateway_config.rate_limit if gateway_config.rate_limit.enabled else None
    )

    if not rate_limit:
        return None

    route_name = route.path.strip("/").replace("/", "-") or "root"

    return {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "Middleware",
        "metadata": {
            "name": f"gateway-{route_name}-ratelimit",
            "namespace": namespace,
            "labels": {
                "k3sgateway.io/route": route_name,
                "k3sgateway.io/component": "ratelimit",
            },
        },
        "spec": {
            "rateLimit": {
                "average": rate_limit.requests_per_second,
                "burst": rate_limit.burst,
            },
        },
    }


def generate_basicauth_middleware(
    route: GatewayRoute,
    namespace: str = "apps",
) -> Optional[Dict[str, Any]]:
    """
    Generate Traefik BasicAuth Middleware for a route.

    Args:
        route: Gateway route configuration
        namespace: Namespace for the middleware

    Returns:
        Traefik BasicAuth Middleware manifest or None if no auth configured
    """
    if not route.auth or not route.auth.enabled or route.auth.type != "basic":
        return None

    route_name = route.path.strip("/").replace("/", "-") or "root"

    return {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "Middleware",
        "metadata": {
            "name": f"gateway-{route_name}-basicauth",
            "namespace": namespace,
            "labels": {
                "k3sgateway.io/route": route_name,
                "k3sgateway.io/component": "auth",
            },
        },
        "spec": {
            "basicAuth": {
                "secret": f"gateway-{route_name}-auth",  # User must create this secret
            },
        },
    }


def generate_cors_middleware(
    cors_config: CorsConfig,
    namespace: str = "haproxy-ingress",
) -> Dict[str, Any]:
    """
    Generate CORS middleware/configuration.

    For HAProxy, CORS is typically handled via annotations on the ingress.
    This function is for Traefik which uses CRD-based middleware.

    Args:
        cors_config: CORS configuration
        namespace: Namespace for the middleware

    Returns:
        Traefik CORS Middleware manifest
    """
    spec: Dict[str, Any] = {
        "accessControlAllowMethods": cors_config.allow_methods,
        "accessControlAllowHeaders": cors_config.allow_headers,
        "accessControlExposeHeaders": cors_config.expose_headers,
        "addVaryHeader": True,
    }

    # Handle allow origins
    if cors_config.allow_origins == ["*"]:
        spec["accessControlAllowOriginList"] = ["*"]
    else:
        spec["accessControlAllowOriginList"] = cors_config.allow_origins

    if cors_config.max_age:
        spec["accessControlMaxAge"] = cors_config.max_age

    return {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "Middleware",
        "metadata": {
            "name": "gateway-cors",
            "namespace": namespace,
            "labels": {
                "k3sgateway.io/component": "cors",
            },
        },
        "spec": {
            "headers": spec,
        },
    }


def generate_all_manifests(
    gateway_config: GatewayConfig,
    output_dir: str,
    ingress_type: str = "haproxy",
    domain: Optional[str] = None,
    tls_enabled: bool = False,
    tls_secret: Optional[str] = None,
    namespace: str = "apps",
) -> None:
    """
    Generate all gateway manifests and write to output directory.

    Args:
        gateway_config: Complete gateway configuration
        output_dir: Output directory for manifests
        ingress_type: Ingress controller type ("haproxy" or "traefik")
        domain: Ingress host domain
        tls_enabled: Whether to enable TLS
        tls_secret: Name of TLS secret
        namespace: Namespace for Traefik resources
    """
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    all_manifests: List[Dict[str, Any]] = []

    if ingress_type == "haproxy":
        # Generate HAProxy Ingress resources
        for route in gateway_config.routes:
            # Generate ExternalName service for KEDA routing
            route_svc = generate_haproxy_route_service(route)
            all_manifests.append(route_svc)

            # Generate Ingress resource
            ingress = generate_haproxy_ingress(
                route=route,
                gateway_config=gateway_config,
                domain=domain,
                tls_enabled=tls_enabled,
                tls_secret=tls_secret,
            )
            all_manifests.append(ingress)

        print(f"Generated {len(gateway_config.routes)} HAProxy gateway routes")

    else:
        # Generate Traefik IngressRoute
        ingress_route, middlewares, external_svc = generate_traefik_ingressroute(
            gateway_config=gateway_config,
            namespace=namespace,
            domain=domain,
        )

        if middlewares:
            all_manifests.extend(middlewares)
        if external_svc:
            all_manifests.append(external_svc)
        if ingress_route:
            all_manifests.append(ingress_route)

        # Add CORS middleware if enabled
        if gateway_config.cors.enabled:
            cors_middleware = generate_cors_middleware(
                gateway_config.cors, namespace=namespace
            )
            all_manifests.append(cors_middleware)

        print(f"Generated Traefik IngressRoute with {len(gateway_config.routes)} routes")

    # Write manifests
    if all_manifests:
        manifest_content = yaml.dump_all(all_manifests, default_flow_style=False)
        (output_path / "gateway-manifests.yaml").write_text(manifest_content)
        print(f"Wrote manifests to {output_path / 'gateway-manifests.yaml'}")
    else:
        print("No gateway routes to generate")
