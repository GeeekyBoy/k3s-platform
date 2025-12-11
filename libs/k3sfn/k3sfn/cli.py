"""
CLI tool for K3s Functions

Discovers decorated functions and generates Kubernetes manifests.
"""

import argparse
import importlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .decorators import FunctionRegistry
from .types import FunctionMetadata, TriggerType, Visibility


# ============================================================================
# apps.yaml Integration (Phase 4)
# ============================================================================

def find_apps_yaml() -> Optional[Path]:
    """
    Find apps.yaml by searching up from current directory.

    Returns:
        Path to apps.yaml or None if not found
    """
    current = Path.cwd()
    for parent in [current] + list(current.parents):
        candidate = parent / "apps.yaml"
        if candidate.exists():
            return candidate
    return None


def load_apps_yaml(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load apps.yaml configuration.

    Args:
        path: Optional path to apps.yaml. If not provided, searches up from cwd.

    Returns:
        Parsed YAML content as dict

    Raises:
        FileNotFoundError: If apps.yaml not found
    """
    if path:
        apps_path = Path(path)
    else:
        apps_path = find_apps_yaml()

    if not apps_path or not apps_path.exists():
        raise FileNotFoundError("apps.yaml not found")

    with open(apps_path) as f:
        return yaml.safe_load(f)


def get_serverless_config(
    app_name: str,
    apps_yaml_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Get serverless function configuration from apps.yaml.

    Args:
        app_name: Name of the serverless app
        apps_yaml_path: Optional path to apps.yaml

    Returns:
        Serverless config dict or None if not found
    """
    try:
        config = load_apps_yaml(apps_yaml_path)
    except FileNotFoundError:
        return None

    for serverless in config.get("serverless", []):
        if serverless.get("name") == app_name:
            return serverless
    return None


def get_defaults_for_env(
    apps_yaml_path: Optional[str] = None,
    env: str = "local",
) -> Dict[str, Any]:
    """
    Get defaults from apps.yaml for an environment.

    Args:
        apps_yaml_path: Optional path to apps.yaml
        env: Environment name (local, dev, gcp)

    Returns:
        Dict with namespace, registry, ingress settings
    """
    try:
        config = load_apps_yaml(apps_yaml_path)
    except FileNotFoundError:
        return {
            "namespace": "apps",
            "registry": "",
            "ingress": "traefik",
        }

    defaults = config.get("defaults", {})
    return {
        "namespace": defaults.get("namespace", "apps"),
        "registry": defaults.get("registry", {}).get(env, ""),
        "ingress": defaults.get("ingress", {}).get(env, "traefik"),
    }


def get_enabled_serverless_apps(
    env: str = "local",
    apps_yaml_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Get list of enabled serverless apps for the given environment.

    Args:
        env: Target environment (local, dev, gcp)
        apps_yaml_path: Optional path to apps.yaml

    Returns:
        List of enabled serverless app configs
    """
    try:
        config = load_apps_yaml(apps_yaml_path)
    except FileNotFoundError:
        return []

    enabled = []
    for serverless in config.get("serverless", []):
        # Check base enabled flag
        if not serverless.get("enabled", True):
            continue

        # Check environment-specific enabled flag
        env_override = serverless.get(env, {})
        if env_override.get("enabled") is False:
            continue

        enabled.append(serverless)

    return enabled


def discover_functions(source_dir: str, module_name: str = "functions") -> List[FunctionMetadata]:
    """
    Discover all decorated functions in a source directory.

    Args:
        source_dir: Path to the source directory
        module_name: Name of the module to import

    Returns:
        List of discovered function metadata
    """
    # Add source directory to path
    sys.path.insert(0, source_dir)

    # Clear registry to avoid duplicates
    FunctionRegistry.clear()

    # Find all Python files in the functions directory
    functions_dir = Path(source_dir) / module_name
    if not functions_dir.exists():
        # Try treating module_name as a file
        module_file = Path(source_dir) / f"{module_name}.py"
        if module_file.exists():
            importlib.import_module(module_name)
        else:
            raise FileNotFoundError(f"Functions directory not found: {functions_dir}")
    else:
        # Import all Python files in the directory
        for py_file in functions_dir.glob("**/*.py"):
            if py_file.name.startswith("_"):
                continue

            # Convert file path to module path
            rel_path = py_file.relative_to(source_dir)
            module_path = str(rel_path.with_suffix("")).replace("/", ".")

            try:
                importlib.import_module(module_path)
            except Exception as e:
                print(f"Warning: Failed to import {module_path}: {e}")

    return list(FunctionRegistry.get_all().values())


def generate_dockerfile(
    app_name: str,
    app_path: str,
    base_image: str = "python:3.12-slim",
) -> str:
    """Generate a multi-stage Dockerfile optimized for Cloud Build"""
    return f"""# Auto-generated Dockerfile for {app_name}
# Optimized for Google Cloud Build (runs from project root)

FROM {base_image} as builder

WORKDIR /app

# Install build dependencies
RUN pip install --no-cache-dir hatchling

# Build and cache SDK wheel
COPY libs/k3sfn /app/libs/k3sfn
RUN pip wheel --no-deps --wheel-dir=/wheels /app/libs/k3sfn

# Build runtime dependency wheels
RUN pip wheel --no-deps --wheel-dir=/wheels fastapi uvicorn pydantic valkey pyyaml

# Runtime stage
FROM {base_image}

WORKDIR /app

# Install from pre-built wheels
COPY --from=builder /wheels /wheels
RUN pip install --no-cache-dir /wheels/*.whl && rm -rf /wheels

# Copy function code
COPY {app_path}/functions /app/functions

# Runtime configuration
ENV PORT=8080
EXPOSE 8080

# Run the function server (K3SFN_FUNCTION env var controls which function)
CMD ["python", "-m", "k3sfn.runtime", "functions"]
"""


def generate_deployment(
    func: FunctionMetadata,
    app_name: str,
    namespace: str = "apps",
    image: str = "",
    registry: str = "",
) -> Dict:
    """Generate Kubernetes Deployment for a function"""
    name = f"{app_name}-{func.name}".replace("_", "-").lower()
    full_image = f"{registry}/{app_name}:latest" if registry else f"{app_name}:latest"
    if image:
        full_image = image

    # Build environment variables
    env_vars = [
        {"name": "K3SFN_FUNCTION", "value": func.name},
        {"name": "PORT", "value": "8080"},
    ]

    for key, value in func.environment.items():
        env_vars.append({"name": key, "value": value})

    # Build command based on trigger type
    command = ["python", "-m", "k3sfn.runtime"]
    args = ["functions"]

    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3sfn.io/app": app_name,
                "k3sfn.io/function": func.name,
                "k3sfn.io/trigger": func.trigger_type.value,
                **func.labels,
            },
        },
        "spec": {
            "replicas": func.scaling.min_instances,
            "selector": {
                "matchLabels": {
                    "app": name,
                },
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": name,
                        "k3sfn.io/app": app_name,
                        "k3sfn.io/function": func.name,
                    },
                },
                "spec": {
                    "containers": [
                        {
                            "name": "function",
                            "image": full_image,
                            "command": command,
                            "args": args,
                            "ports": [{"containerPort": 8080}],
                            "env": env_vars,
                            "resources": {
                                "requests": {
                                    "memory": func.resources.memory,
                                    "cpu": func.resources.cpu,
                                },
                                "limits": {
                                    # Memory limit prevents OOM kills
                                    "memory": func.resources.memory_limit,
                                    # CPU limit intentionally omitted for burstable QoS
                                    # This allows CPU burst during cold start, reducing latency
                                },
                            },
                            # Startup probe: Allow up to 60s for cold start (30 attempts * 2s)
                            # This prevents liveness probe from killing pod during slow startup
                            "startupProbe": {
                                "httpGet": {
                                    "path": "/ready",
                                    "port": 8080,
                                },
                                "initialDelaySeconds": 1,
                                "periodSeconds": 2,
                                "failureThreshold": 30,
                            },
                            "readinessProbe": {
                                "httpGet": {
                                    "path": "/ready",
                                    "port": 8080,
                                },
                                "initialDelaySeconds": 1,
                                "periodSeconds": 2,
                            },
                            "livenessProbe": {
                                "httpGet": {
                                    "path": "/live",
                                    "port": 8080,
                                },
                                "initialDelaySeconds": 5,
                                "periodSeconds": 10,
                            },
                        }
                    ],
                    # Use imagePullSecrets if registry is GCP Artifact Registry
                    "imagePullSecrets": [{"name": "artifact-registry"}] if "docker.pkg.dev" in full_image else [],
                },
            },
        },
    }

    # Add secret volumes if specified
    if func.secrets:
        volumes = []
        volume_mounts = []
        for secret in func.secrets:
            vol_name = secret.replace("_", "-").lower()
            volumes.append({
                "name": vol_name,
                "secret": {"secretName": secret},
            })
            volume_mounts.append({
                "name": vol_name,
                "mountPath": f"/secrets/{secret}",
                "readOnly": True,
            })
        deployment["spec"]["template"]["spec"]["volumes"] = volumes
        deployment["spec"]["template"]["spec"]["containers"][0]["volumeMounts"] = volume_mounts

    return deployment


def generate_service(
    func: FunctionMetadata,
    app_name: str,
    namespace: str = "apps",
) -> Dict:
    """Generate Kubernetes Service for a function"""
    name = f"{app_name}-{func.name}".replace("_", "-").lower()

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3sfn.io/app": app_name,
                "k3sfn.io/function": func.name,
            },
        },
        "spec": {
            "selector": {
                "app": name,
            },
            "ports": [
                {
                    "port": 80,
                    "targetPort": 8080,
                    "protocol": "TCP",
                }
            ],
        },
    }


def generate_httpscaledobject(
    func: FunctionMetadata,
    app_name: str,
    namespace: str = "apps",
    host: Optional[str] = None,
) -> Dict:
    """Generate KEDA HTTPScaledObject for HTTP-triggered functions"""
    name = f"{app_name}-{func.name}".replace("_", "-").lower()

    # Use host-based routing: HAProxy rewrites Host header to {service}.{namespace}
    # This is required because KEDA HTTP Add-on doesn't support wildcard "*" host matching
    # The path comes from the http_trigger configuration
    path_prefix = func.http_trigger.path if func.http_trigger else f"/{name}"
    routing_host = f"{name}.{namespace}"

    spec = {
        "hosts": [routing_host],  # Match specific host (set by HAProxy host rewrite)
        "pathPrefixes": [path_prefix],  # Route by path prefix
        "scaleTargetRef": {
            "name": name,
            "kind": "Deployment",
            "apiVersion": "apps/v1",
            "service": name,
            "port": 80,
        },
        "replicas": {
            "min": func.scaling.min_instances,
            "max": func.scaling.max_instances,
        },
        "scalingMetric": {
            "requestRate": {
                "granularity": "1s",
                "targetValue": func.scaling.target_pending_requests,
                "window": "1m",
            }
        },
    }

    return {
        "apiVersion": "http.keda.sh/v1alpha1",
        "kind": "HTTPScaledObject",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3sfn.io/app": app_name,
                "k3sfn.io/function": func.name,
            },
        },
        "spec": spec,
    }


def generate_scaledobject(
    func: FunctionMetadata,
    app_name: str,
    namespace: str = "apps",
    valkey_address: str = "valkey.apps.svc.cluster.local:26379",
) -> Dict:
    """Generate KEDA ScaledObject for queue-triggered functions"""
    name = f"{app_name}-{func.name}".replace("_", "-").lower()

    if not func.queue_trigger:
        raise ValueError(f"Function {func.name} is not a queue trigger")

    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3sfn.io/app": app_name,
                "k3sfn.io/function": func.name,
            },
        },
        "spec": {
            "scaleTargetRef": {
                "name": name,
            },
            "minReplicaCount": func.scaling.min_instances,
            "maxReplicaCount": func.scaling.max_instances,
            "cooldownPeriod": func.scaling.cooldown_period,
            "pollingInterval": 30,
            "triggers": [
                {
                    "type": "redis-sentinel",
                    "metadata": {
                        "addresses": valkey_address,
                        "sentinelMaster": "myprimary",
                        "listName": f"queue:{func.queue_trigger.queue_name}",
                        "listLength": str(func.queue_trigger.batch_size * 5),
                        "databaseIndex": "0",
                        "enableTLS": "false",
                    },
                    "authenticationRef": {
                        "name": "valkey-auth",
                    },
                }
            ],
        },
    }


def generate_cronjob(
    func: FunctionMetadata,
    app_name: str,
    namespace: str = "apps",
    image: str = "",
    registry: str = "",
) -> Dict:
    """Generate Kubernetes CronJob for scheduled functions"""
    name = f"{app_name}-{func.name}".replace("_", "-").lower()
    full_image = f"{registry}/{app_name}:latest" if registry else f"{app_name}:latest"
    if image:
        full_image = image

    if not func.schedule_trigger:
        raise ValueError(f"Function {func.name} is not a schedule trigger")

    return {
        "apiVersion": "batch/v1",
        "kind": "CronJob",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3sfn.io/app": app_name,
                "k3sfn.io/function": func.name,
            },
        },
        "spec": {
            "schedule": func.schedule_trigger.cron,
            "timeZone": func.schedule_trigger.timezone,
            "jobTemplate": {
                "spec": {
                    "template": {
                        "spec": {
                            "restartPolicy": "OnFailure",
                            "imagePullSecrets": [{"name": "artifact-registry"}] if "docker.pkg.dev" in full_image else [],
                            "containers": [
                                {
                                    "name": "function",
                                    "image": full_image,
                                    "command": ["python", "-c"],
                                    "args": [
                                        f"from functions import *; import asyncio; asyncio.run({func.name}(None))"
                                    ],
                                    "env": [
                                        {"name": "K3SFN_FUNCTION", "value": func.name},
                                    ],
                                    "resources": {
                                        "requests": {
                                            "memory": func.resources.memory,
                                            "cpu": func.resources.cpu,
                                        },
                                        "limits": {
                                            # Memory limit prevents OOM kills
                                            "memory": func.resources.memory_limit,
                                            # CPU limit intentionally omitted for burstable QoS
                                        },
                                    },
                                }
                            ],
                        },
                    },
                },
            },
        },
    }


def generate_network_policy(
    func: FunctionMetadata,
    app_name: str,
    namespace: str = "apps",
) -> Dict:
    """
    Generate Kubernetes NetworkPolicy based on function visibility.

    - PUBLIC: Allow from ingress controller (Traefik) and KEDA
    - INTERNAL: Allow from any namespace in cluster
    - PRIVATE: Only allow from same namespace
    - RESTRICTED: Only allow from specific pods/namespaces
    """
    name = f"{app_name}-{func.name}".replace("_", "-").lower()

    # Base policy structure
    policy = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{name}-ingress",
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3sfn.io/app": app_name,
                "k3sfn.io/function": func.name,
                "k3sfn.io/visibility": func.visibility.value,
            },
        },
        "spec": {
            "podSelector": {
                "matchLabels": {
                    "app": name,
                },
            },
            "policyTypes": ["Ingress"],
            "ingress": [],
        },
    }

    # Always allow KEDA HTTP Add-on for HTTP functions (needed for scale-to-zero)
    keda_rule = {
        "from": [
            {
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": "keda",
                    },
                },
            },
        ],
        "ports": [{"protocol": "TCP", "port": 8080}],
    }

    if func.visibility == Visibility.PUBLIC:
        # Allow from ingress controller (Traefik in kube-system)
        policy["spec"]["ingress"].append({
            "from": [
                {
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": "kube-system",
                        },
                    },
                    "podSelector": {
                        "matchLabels": {
                            "app.kubernetes.io/name": "traefik",
                        },
                    },
                },
            ],
            "ports": [{"protocol": "TCP", "port": 8080}],
        })
        # Also allow KEDA for scaling
        policy["spec"]["ingress"].append(keda_rule)

    elif func.visibility == Visibility.INTERNAL:
        # Allow from any namespace in cluster
        policy["spec"]["ingress"].append({
            "from": [
                {"namespaceSelector": {}},  # Any namespace
            ],
            "ports": [{"protocol": "TCP", "port": 8080}],
        })

    elif func.visibility == Visibility.PRIVATE:
        # Only allow from same namespace
        policy["spec"]["ingress"].append({
            "from": [
                {"podSelector": {}},  # Any pod in same namespace
            ],
            "ports": [{"protocol": "TCP", "port": 8080}],
        })
        # Allow KEDA for scaling if HTTP
        if func.trigger_type == TriggerType.HTTP:
            policy["spec"]["ingress"].append(keda_rule)

    elif func.visibility == Visibility.RESTRICTED:
        # Only allow from specific pods/namespaces
        if func.access_rules:
            from_rules = []

            # Add namespace rules
            for ns in func.access_rules.namespaces:
                from_rules.append({
                    "namespaceSelector": {
                        "matchLabels": {
                            "kubernetes.io/metadata.name": ns,
                        },
                    },
                })

            # Add pod label rules
            if func.access_rules.pod_labels:
                from_rules.append({
                    "podSelector": {
                        "matchLabels": func.access_rules.pod_labels,
                    },
                })

            if from_rules:
                policy["spec"]["ingress"].append({
                    "from": from_rules,
                    "ports": [{"protocol": "TCP", "port": 8080}],
                })

        # Allow KEDA for scaling if HTTP
        if func.trigger_type == TriggerType.HTTP:
            policy["spec"]["ingress"].append(keda_rule)

    return policy


def generate_host_rewrite_middleware(
    func: FunctionMetadata,
    app_name: str,
    namespace: str = "apps",
) -> Dict:
    """Generate Traefik Middleware to rewrite Host header for KEDA HTTP add-on routing"""
    name = f"{app_name}-{func.name}".replace("_", "-").lower()
    routing_host = f"{name}.{namespace}"

    return {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "Middleware",
        "metadata": {
            "name": f"{name}-host-rewrite",
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3sfn.io/app": app_name,
                "k3sfn.io/function": func.name,
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


def generate_keda_interceptor_externalname(
    namespace: str = "apps",
) -> Dict:
    """
    Generate an ExternalName service to reference KEDA HTTP Add-on interceptor.

    This is needed because Traefik IngressRoute cannot reference services
    in other namespaces by default. This ExternalName service acts as a
    local proxy to the cross-namespace KEDA service.
    """
    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": "keda-interceptor-proxy",
            "namespace": namespace,
            "labels": {
                "k3sfn.io/component": "keda-proxy",
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


def generate_haproxy_route_service(
    func: FunctionMetadata,
    app_name: str,
    namespace: str = "apps",
) -> Dict:
    """
    Generate a per-route ExternalName service that points to KEDA interceptor.

    HAProxy Ingress merges backends that point to the same service, which
    breaks per-path config-backend annotations. By creating a unique service
    per function, each gets its own backend with its own Host header rewrite.

    Uses ExternalName for DNS-based resolution (no hardcoded IPs).
    """
    name = f"{app_name}-{func.name}".replace("_", "-").lower()
    service_name = f"keda-route-{name}"

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": service_name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3sfn.io/app": app_name,
                "k3sfn.io/function": func.name,
                "k3sfn.io/component": "keda-route",
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


def generate_haproxy_ingress(
    func: FunctionMetadata,
    app_name: str,
    namespace: str = "apps",
) -> Dict:
    """
    Generate HAProxy Ingress resource for a function.

    Uses per-path Ingress with config-backend annotation to rewrite
    the Host header for KEDA HTTP Add-on routing.

    Each function gets its own unique route service to prevent HAProxy
    from merging backends (which would break per-path Host header rewriting).
    """
    name = f"{app_name}-{func.name}".replace("_", "-").lower()
    service_name = f"keda-route-{name}"

    if not func.http_trigger:
        raise ValueError(f"Function {func.name} is not an HTTP trigger")

    path = func.http_trigger.path
    routing_host = f"{name}.{namespace}"

    return {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": f"{name}-haproxy",
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3sfn.io/app": app_name,
                "k3sfn.io/function": func.name,
                "k3sfn.io/ingress": "haproxy",
            },
            "annotations": {
                "haproxy-ingress.github.io/timeout-connect": "10s",
                "haproxy-ingress.github.io/timeout-server": "180s",
                "haproxy-ingress.github.io/timeout-client": "180s",
                "haproxy-ingress.github.io/timeout-queue": "180s",
                "haproxy-ingress.github.io/retry-on": "conn-failure,empty-response,response-timeout",
                "haproxy-ingress.github.io/retries": "3",
                # Rewrite Host header for KEDA routing
                "haproxy-ingress.github.io/config-backend": f"http-request set-header Host {routing_host}\n",
            },
        },
        "spec": {
            "ingressClassName": "haproxy",
            "rules": [
                {
                    "http": {
                        "paths": [
                            {
                                "path": path,
                                "pathType": "Prefix",
                                "backend": {
                                    "service": {
                                        # Use per-function service to prevent HAProxy backend merging
                                        "name": service_name,
                                        "port": {"number": 8080},
                                    },
                                },
                            }
                        ],
                    },
                }
            ],
        },
    }


def generate_haproxy_keda_proxy_service(namespace: str = "apps") -> List[Dict]:
    """
    Generate Service and Endpoints to proxy to KEDA interceptor.

    Uses headless service with EndpointSlice to dynamically track the
    KEDA interceptor IP without hardcoding. This is achieved via a
    ClusterIP service that uses a selector-less design with an
    ExternalName type for DNS-based resolution.

    HAProxy doesn't support ExternalName services directly in Ingress,
    so we use a regular ClusterIP service with dynamic endpoint discovery.
    """
    # ExternalName service for DNS-based resolution (used by other components)
    external_svc = {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": "keda-interceptor-proxy",
            "namespace": namespace,
            "labels": {
                "k3sfn.io/component": "keda-proxy",
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

    return [external_svc]


def generate_ingress_routes(
    functions: List[FunctionMetadata],
    app_name: str,
    namespace: str = "apps",
    host: Optional[str] = None,
) -> tuple[Optional[Dict], List[Dict], Optional[Dict]]:
    """
    Generate Traefik IngressRoute for PUBLIC HTTP functions only.

    Only functions with visibility="public" get exposed via ingress.
    Returns tuple of (IngressRoute, list of Middlewares, ExternalName Service)
    """
    routes = []
    middlewares = []

    for func in functions:
        # Only include public HTTP functions in ingress
        if func.trigger_type != TriggerType.HTTP or not func.http_trigger:
            continue
        if func.visibility != Visibility.PUBLIC:
            continue

        name = f"{app_name}-{func.name}".replace("_", "-").lower()
        path = func.http_trigger.path

        # Generate host rewrite middleware for KEDA routing
        middleware = generate_host_rewrite_middleware(func, app_name, namespace)
        middlewares.append(middleware)

        # Create route match
        match = f"PathPrefix(`{path}`)"
        if host:
            match = f"Host(`{host}`) && {match}"

        # Use local ExternalName service instead of cross-namespace reference
        # This avoids Traefik's "service not in parent resource namespace" error
        routes.append({
            "match": match,
            "kind": "Rule",
            "services": [
                {
                    "name": "keda-interceptor-proxy",
                    "port": 8080,
                }
            ],
            "middlewares": [
                {"name": f"{name}-host-rewrite", "namespace": namespace},
            ],
        })

    # Return None if no public routes
    if not routes:
        return None, [], None

    ingress_route = {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "IngressRoute",
        "metadata": {
            "name": f"{app_name}-routes",
            "namespace": namespace,
            "labels": {
                "k3sfn.io/app": app_name,
            },
        },
        "spec": {
            "entryPoints": ["web", "websecure"],
            "routes": routes,
        },
    }

    # Generate ExternalName service for cross-namespace KEDA access
    external_svc = generate_keda_interceptor_externalname(namespace)

    return ingress_route, middlewares, external_svc


def generate_all_manifests(
    source_dir: str,
    app_name: str,
    output_dir: str,
    namespace: str = "apps",
    registry: str = "",
    host: Optional[str] = None,
    app_path: Optional[str] = None,
    ingress_type: str = "traefik",
) -> None:
    """Generate all Kubernetes manifests for an app

    Args:
        source_dir: Path to source directory containing functions
        app_name: Application name
        output_dir: Output directory for generated manifests
        namespace: Kubernetes namespace
        registry: Container registry URL
        host: Ingress host
        app_path: Path to app directory (relative to project root)
        ingress_type: Ingress controller type - "traefik" (local) or "haproxy" (GCP)
    """
    # Discover functions
    functions = discover_functions(source_dir)

    if not functions:
        print(f"No functions found in {source_dir}")
        return

    print(f"Discovered {len(functions)} functions:")
    for func in functions:
        print(f"  - {func.name} ({func.trigger_type.value})")

    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Determine app path for Dockerfile (relative path from project root)
    if app_path is None:
        # Try to infer from source_dir
        source_path = Path(source_dir).resolve()
        # Look for apps/ in path to determine relative path
        parts = source_path.parts
        if "apps" in parts:
            apps_idx = parts.index("apps")
            app_path = "/".join(parts[apps_idx:])
        else:
            app_path = f"apps/{app_name}"

    # Generate Dockerfile
    dockerfile = generate_dockerfile(app_name, app_path)
    (output_path / "Dockerfile").write_text(dockerfile)

    # Generate manifests for each function
    all_manifests = []

    for func in functions:
        if func.trigger_type == TriggerType.SCHEDULE:
            # Scheduled functions only need CronJob, no Deployment/Service
            cj = generate_cronjob(func, app_name, namespace, registry=registry)
            all_manifests.append(cj)
        else:
            # HTTP and Queue functions need Deployment + Service + Scaler
            deployment = generate_deployment(func, app_name, namespace, registry=registry)
            service = generate_service(func, app_name, namespace)
            all_manifests.extend([deployment, service])

            if func.trigger_type == TriggerType.HTTP:
                httpso = generate_httpscaledobject(func, app_name, namespace, host)
                all_manifests.append(httpso)
            elif func.trigger_type == TriggerType.QUEUE:
                so = generate_scaledobject(func, app_name, namespace)
                all_manifests.append(so)

            # Generate NetworkPolicy for each function (not CronJobs)
            netpol = generate_network_policy(func, app_name, namespace)
            all_manifests.append(netpol)

    # Generate ingress resources based on ingress type
    if ingress_type == "haproxy":
        # HAProxy ingress for GCP deployment
        # Generate per-function route services and ingresses
        # Each function gets its own ExternalName service pointing to KEDA interceptor
        # This prevents HAProxy from merging backends (which breaks per-path Host rewriting)
        haproxy_route_count = 0
        for func in functions:
            if func.trigger_type == TriggerType.HTTP and func.visibility == Visibility.PUBLIC:
                # Generate per-route ExternalName service
                route_svc = generate_haproxy_route_service(func, app_name, namespace)
                all_manifests.append(route_svc)
                # Generate HAProxy Ingress
                haproxy_ing = generate_haproxy_ingress(func, app_name, namespace)
                all_manifests.append(haproxy_ing)
                haproxy_route_count += 1

        if haproxy_route_count > 0:
            print(f"  Generated {haproxy_route_count} HAProxy route services (ExternalName, DNS-based)")
            print(f"  Generated {haproxy_route_count} HAProxy Ingress resources")
    else:
        # Traefik IngressRoute for local development
        ingress, middlewares, external_svc = generate_ingress_routes(functions, app_name, namespace, host)
        if middlewares:
            all_manifests.extend(middlewares)
        if ingress:
            all_manifests.append(ingress)
            print(f"  Generated IngressRoute for public functions")
        if external_svc:
            all_manifests.append(external_svc)
            print(f"  Generated ExternalName service for KEDA cross-namespace access")

    # Write all manifests to a single file
    manifest_content = yaml.dump_all(all_manifests, default_flow_style=False)
    (output_path / "manifests.yaml").write_text(manifest_content)

    # Generate function config (for reference)
    config = {
        "app_name": app_name,
        "namespace": namespace,
        "functions": [
            {
                "name": f.name,
                "trigger_type": f.trigger_type.value,
                "visibility": f.visibility.value,
                "path": f.http_trigger.path if f.http_trigger else None,
                "resources": {
                    "memory": f.resources.memory,
                    "cpu": f.resources.cpu,
                },
                "scaling": {
                    "min": f.scaling.min_instances,
                    "max": f.scaling.max_instances,
                },
            }
            for f in functions
        ],
    }
    (output_path / "k3sfn.json").write_text(json.dumps(config, indent=2))

    print(f"\nGenerated manifests in {output_dir}:")
    print(f"  - Dockerfile")
    print(f"  - manifests.yaml")
    print(f"  - k3sfn.json")


def main():
    """CLI entry point"""
    parser = argparse.ArgumentParser(
        description="K3s Functions CLI - Generate Kubernetes manifests from decorated functions"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate Kubernetes manifests")
    gen_parser.add_argument("source_dir", nargs="?", help="Source directory containing functions")
    gen_parser.add_argument("--name", "-n", help="Application name")
    gen_parser.add_argument("--output", "-o", default="./generated", help="Output directory")
    gen_parser.add_argument("--namespace", default=None, help="Kubernetes namespace")
    gen_parser.add_argument("--registry", default=None, help="Container registry URL")
    gen_parser.add_argument("--host", default=None, help="Ingress host")
    gen_parser.add_argument(
        "--ingress", "-i",
        default=None,
        choices=["traefik", "haproxy"],
        help="Ingress controller type: traefik (local/dev) or haproxy (GCP)"
    )
    gen_parser.add_argument(
        "--from-apps-yaml",
        action="store_true",
        help="Read configuration from apps.yaml serverless entry"
    )
    gen_parser.add_argument(
        "--apps-yaml",
        default=None,
        help="Path to apps.yaml (default: auto-detect)"
    )
    gen_parser.add_argument(
        "--env", "-e",
        default="local",
        choices=["local", "dev", "gcp"],
        help="Target environment for defaults (default: local)"
    )

    # Generate-all command
    gen_all_parser = subparsers.add_parser(
        "generate-all",
        help="Generate manifests for all enabled serverless apps from apps.yaml"
    )
    gen_all_parser.add_argument("--output", "-o", required=True, help="Output directory")
    gen_all_parser.add_argument(
        "--env", "-e",
        default="local",
        choices=["local", "dev", "gcp"],
        help="Target environment (default: local)"
    )
    gen_all_parser.add_argument(
        "--apps-yaml",
        default=None,
        help="Path to apps.yaml (default: auto-detect)"
    )

    # List command
    list_parser = subparsers.add_parser("list", help="List discovered functions")
    list_parser.add_argument("source_dir", nargs="?", help="Source directory containing functions")
    list_parser.add_argument(
        "--from-apps-yaml",
        action="store_true",
        help="List serverless apps from apps.yaml"
    )
    list_parser.add_argument(
        "--apps-yaml",
        default=None,
        help="Path to apps.yaml (default: auto-detect)"
    )
    list_parser.add_argument(
        "--env", "-e",
        default="local",
        choices=["local", "dev", "gcp"],
        help="Target environment (default: local)"
    )

    # Run command
    run_parser = subparsers.add_parser("run", help="Run functions locally")
    run_parser.add_argument("source_dir", help="Source directory containing functions")
    run_parser.add_argument("--function", "-f", help="Specific function to run")
    run_parser.add_argument("--port", "-p", type=int, default=8080, help="Port to listen on")

    args = parser.parse_args()

    if args.command == "generate":
        if args.from_apps_yaml:
            # Read configuration from apps.yaml
            if not args.name:
                print("Error: --name is required when using --from-apps-yaml")
                sys.exit(1)

            serverless_config = get_serverless_config(args.name, args.apps_yaml)
            if not serverless_config:
                print(f"Error: Serverless app '{args.name}' not found in apps.yaml")
                sys.exit(1)

            # Get defaults for the environment
            defaults = get_defaults_for_env(args.apps_yaml, args.env)

            # Get environment-specific override
            env_override = serverless_config.get(args.env, {})

            # Determine source_dir
            source_dir = args.source_dir
            if not source_dir:
                source_dir = serverless_config.get("path")
            if not source_dir:
                print("Error: source_dir is required (or set 'path' in apps.yaml)")
                sys.exit(1)

            # Resolve settings with priority: CLI args > env override > serverless config > defaults
            namespace = (
                args.namespace
                or serverless_config.get("namespace")
                or defaults["namespace"]
            )
            registry = args.registry if args.registry is not None else defaults["registry"]
            ingress = args.ingress or defaults["ingress"]

            print(f"Generating manifests for '{args.name}' (env: {args.env})")
            print(f"  Source: {source_dir}")
            print(f"  Namespace: {namespace}")
            print(f"  Registry: {registry or '(none)'}")
            print(f"  Ingress: {ingress}")

            generate_all_manifests(
                source_dir=source_dir,
                app_name=args.name,
                output_dir=args.output,
                namespace=namespace,
                registry=registry,
                host=args.host,
                ingress_type=ingress,
            )
        else:
            # Legacy mode: direct CLI args
            if not args.source_dir:
                print("Error: source_dir is required")
                sys.exit(1)
            if not args.name:
                print("Error: --name is required")
                sys.exit(1)

            generate_all_manifests(
                source_dir=args.source_dir,
                app_name=args.name,
                output_dir=args.output,
                namespace=args.namespace or "apps",
                registry=args.registry or "",
                host=args.host,
                ingress_type=args.ingress or "traefik",
            )

    elif args.command == "generate-all":
        # Generate manifests for all enabled serverless apps
        enabled_apps = get_enabled_serverless_apps(args.env, args.apps_yaml)

        if not enabled_apps:
            print(f"No enabled serverless apps found for environment '{args.env}'")
            sys.exit(0)

        # Get defaults for the environment
        defaults = get_defaults_for_env(args.apps_yaml, args.env)

        print(f"Generating manifests for {len(enabled_apps)} serverless apps (env: {args.env})")

        for app_config in enabled_apps:
            app_name = app_config["name"]
            source_dir = app_config.get("path")

            if not source_dir:
                print(f"  Skipping {app_name}: no path defined")
                continue

            # Get app-specific overrides
            namespace = app_config.get("namespace") or defaults["namespace"]
            registry = defaults["registry"]
            ingress = defaults["ingress"]

            # Output to app-specific subdirectory
            output_dir = os.path.join(args.output, app_name)

            print(f"\n  {app_name}:")
            print(f"    Source: {source_dir}")
            print(f"    Output: {output_dir}")

            try:
                generate_all_manifests(
                    source_dir=source_dir,
                    app_name=app_name,
                    output_dir=output_dir,
                    namespace=namespace,
                    registry=registry,
                    host=None,
                    ingress_type=ingress,
                )
            except Exception as e:
                print(f"    Error: {e}")

        print(f"\nGenerated manifests in {args.output}")

    elif args.command == "list":
        if args.from_apps_yaml:
            # List serverless apps from apps.yaml
            enabled_apps = get_enabled_serverless_apps(args.env, args.apps_yaml)
            if not enabled_apps:
                print(f"No enabled serverless apps found for environment '{args.env}'")
            else:
                print(f"Enabled serverless apps for '{args.env}':")
                for app in enabled_apps:
                    path = app.get("path", "(no path)")
                    print(f"  {app['name']}: {path}")
        else:
            # List functions from source directory
            if not args.source_dir:
                print("Error: source_dir is required (or use --from-apps-yaml)")
                sys.exit(1)
            functions = discover_functions(args.source_dir)
            for func in functions:
                trigger_info = ""
                if func.http_trigger:
                    trigger_info = f" -> {func.http_trigger.path}"
                elif func.queue_trigger:
                    trigger_info = f" -> queue:{func.queue_trigger.queue_name}"
                elif func.schedule_trigger:
                    trigger_info = f" -> cron:{func.schedule_trigger.cron}"
                print(f"{func.name} ({func.trigger_type.value}){trigger_info}")

    elif args.command == "run":
        os.environ["PORT"] = str(args.port)
        if args.function:
            os.environ["K3SFN_FUNCTION"] = args.function

        from .runtime import run_function

        run_function(args.source_dir, args.function)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
