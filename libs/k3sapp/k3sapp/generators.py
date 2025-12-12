"""
Kubernetes manifest generators for traditional apps.

Generates Deployment, Service, Ingress, HTTPScaledObject, NetworkPolicy, and PDB.
"""

from typing import Any, Dict, List, Optional

from .types import (
    AppConfig,
    AppsYamlConfig,
    Environment,
    IngressConfig,
    ProbeConfig,
    ProbeType,
    ScalingConfig,
    ScalingType,
    SecurityConfig,
    Visibility,
    VolumeConfig,
    VolumeType,
)


def _to_k8s_name(name: str) -> str:
    """Convert name to valid K8s resource name."""
    return name.replace("_", "-").lower()


def _build_probe(probe: ProbeConfig) -> Dict[str, Any]:
    """Build Kubernetes probe spec."""
    result: Dict[str, Any] = {
        "periodSeconds": probe.period,
        "timeoutSeconds": probe.timeout,
        "successThreshold": probe.success_threshold,
        "failureThreshold": probe.failure_threshold,
    }

    if probe.initial_delay > 0:
        result["initialDelaySeconds"] = probe.initial_delay

    if probe.type == ProbeType.HTTP:
        result["httpGet"] = {
            "path": probe.path,
            "port": probe.port,
        }
    elif probe.type == ProbeType.TCP:
        result["tcpSocket"] = {
            "port": probe.port,
        }
    elif probe.type == ProbeType.EXEC and probe.command:
        result["exec"] = {
            "command": probe.command,
        }

    return result


def _build_env_vars(
    app: AppConfig,
    env: Environment,
) -> List[Dict[str, Any]]:
    """Build environment variables list (literal values only, not secrets)."""
    env_vars = []

    # Get literal env vars (excludes secrets, performs ${VAR} substitution)
    for key, value in app.get_literal_env_vars(env).items():
        env_vars.append({"name": key, "value": value})

    return env_vars


def _build_env_from(app: AppConfig) -> List[Dict[str, Any]]:
    """Build envFrom list for secrets/configmaps."""
    env_from = []

    for ref in app.env_from:
        if ref.type == "secret":
            item = {"secretRef": {"name": ref.name}}
            if ref.prefix:
                item["prefix"] = ref.prefix
            if ref.optional:
                item["secretRef"]["optional"] = True
            env_from.append(item)
        elif ref.type == "configmap":
            item = {"configMapRef": {"name": ref.name}}
            if ref.prefix:
                item["prefix"] = ref.prefix
            if ref.optional:
                item["configMapRef"]["optional"] = True
            env_from.append(item)

    return env_from


def _build_volume(vol: VolumeConfig) -> Dict[str, Any]:
    """Build volume spec."""
    volume: Dict[str, Any] = {"name": vol.name}

    if vol.type == VolumeType.EMPTY_DIR:
        empty_dir: Dict[str, Any] = {}
        if vol.medium:
            empty_dir["medium"] = vol.medium
        if vol.size_limit:
            empty_dir["sizeLimit"] = vol.size_limit
        volume["emptyDir"] = empty_dir

    elif vol.type == VolumeType.PVC:
        volume["persistentVolumeClaim"] = {
            "claimName": vol.name,
        }

    elif vol.type == VolumeType.SECRET:
        secret_vol: Dict[str, Any] = {
            "secretName": vol.secret_name or vol.name,
        }
        if vol.items:
            secret_vol["items"] = vol.items
        volume["secret"] = secret_vol

    elif vol.type == VolumeType.CONFIGMAP:
        cm_vol: Dict[str, Any] = {
            "name": vol.configmap_name or vol.name,
        }
        if vol.items:
            cm_vol["items"] = vol.items
        volume["configMap"] = cm_vol

    return volume


def _build_volume_mount(vol: VolumeConfig) -> Dict[str, Any]:
    """Build volume mount spec."""
    mount: Dict[str, Any] = {
        "name": vol.name,
        "mountPath": vol.mount_path,
    }
    if vol.read_only:
        mount["readOnly"] = True
    return mount


def generate_deployment(
    app: AppConfig,
    env: Environment,
    image: str,
    config: AppsYamlConfig,
) -> Dict[str, Any]:
    """
    Generate Kubernetes Deployment manifest.

    Args:
        app: App configuration
        env: Target environment
        image: Container image URL
        config: Root apps.yaml config

    Returns:
        Deployment manifest dict
    """
    name = _to_k8s_name(app.name)
    resources = app.get_effective_resources(env)
    scaling = app.get_effective_scaling(env)
    primary_port = app.get_primary_port()

    # Get replicas based on scaling config
    replicas = scaling.min_instances if scaling.type != ScalingType.NONE else 1
    env_override = app.get_env_override(env)
    if env_override and env_override.replicas is not None:
        replicas = env_override.replicas

    # Container spec
    container: Dict[str, Any] = {
        "name": name,
        "image": image,
        "ports": [
            {
                "containerPort": p.container_port,
                "protocol": p.protocol,
                "name": p.name,
            }
            for p in app.container.ports
        ] if app.container.ports else [{"containerPort": primary_port.container_port}],
        "resources": {
            "requests": {
                "memory": resources.memory,
                "cpu": resources.cpu,
            },
            "limits": {
                "memory": resources.memory_limit,
            },
        },
    }

    # Optional CPU limit
    if resources.cpu_limit:
        container["resources"]["limits"]["cpu"] = resources.cpu_limit

    # Ephemeral storage
    if resources.ephemeral_storage:
        container["resources"]["requests"]["ephemeral-storage"] = resources.ephemeral_storage
        container["resources"]["limits"]["ephemeral-storage"] = resources.ephemeral_storage

    # Command/args
    if app.container.command:
        container["command"] = app.container.command
    if app.container.args:
        container["args"] = app.container.args

    # Environment
    env_vars = _build_env_vars(app, env)
    if env_vars:
        container["env"] = env_vars

    env_from = _build_env_from(app)

    # Add secretRef for ESO-synced secrets (non-local environments only)
    if env != Environment.LOCAL and app.get_secret_refs():
        env_from.append({
            "secretRef": {
                "name": f"{name}-secrets",
            }
        })

    if env_from:
        container["envFrom"] = env_from

    # Probes
    if app.probes.startup:
        container["startupProbe"] = _build_probe(app.probes.startup)
    if app.probes.readiness:
        container["readinessProbe"] = _build_probe(app.probes.readiness)
    if app.probes.liveness:
        container["livenessProbe"] = _build_probe(app.probes.liveness)

    # Volume mounts
    if app.volumes:
        container["volumeMounts"] = [_build_volume_mount(v) for v in app.volumes]

    # Container security context
    if app.security.container_security_context:
        sec_ctx = app.security.container_security_context
        container["securityContext"] = {
            "allowPrivilegeEscalation": sec_ctx.allow_privilege_escalation,
            "readOnlyRootFilesystem": sec_ctx.read_only_root_filesystem,
        }
        if sec_ctx.capabilities_drop or sec_ctx.capabilities_add:
            container["securityContext"]["capabilities"] = {}
            if sec_ctx.capabilities_drop:
                container["securityContext"]["capabilities"]["drop"] = sec_ctx.capabilities_drop
            if sec_ctx.capabilities_add:
                container["securityContext"]["capabilities"]["add"] = sec_ctx.capabilities_add

    # Pod spec
    pod_spec: Dict[str, Any] = {
        "containers": [container],
    }

    # Volumes
    if app.volumes:
        pod_spec["volumes"] = [_build_volume(v) for v in app.volumes]

    # Service account
    if app.security.service_account:
        pod_spec["serviceAccountName"] = app.security.service_account

    # Pod security context
    if app.security.pod_security_context:
        psc = app.security.pod_security_context
        pod_sec: Dict[str, Any] = {}
        if psc.run_as_non_root:
            pod_sec["runAsNonRoot"] = True
        if psc.run_as_user is not None:
            pod_sec["runAsUser"] = psc.run_as_user
        if psc.run_as_group is not None:
            pod_sec["runAsGroup"] = psc.run_as_group
        if psc.fs_group is not None:
            pod_sec["fsGroup"] = psc.fs_group
        if pod_sec:
            pod_spec["securityContext"] = pod_sec

    # Image pull secrets for GCP
    ingress_type = config.defaults.get_ingress_type(env)
    if "docker.pkg.dev" in image:
        pod_spec["imagePullSecrets"] = [{"name": "artifact-registry"}]

    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "replicas": replicas,
            "selector": {
                "matchLabels": {
                    "app": name,
                },
            },
            "template": {
                "metadata": {
                    "labels": {
                        "app": name,
                        "k3sapp.io/app": app.name,
                    },
                },
                "spec": pod_spec,
            },
        },
    }

    return deployment


def generate_service(
    app: AppConfig,
    env: Environment,
) -> Dict[str, Any]:
    """
    Generate Kubernetes Service manifest.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        Service manifest dict
    """
    name = _to_k8s_name(app.name)
    primary_port = app.get_primary_port()

    ports = []
    if app.container.ports:
        for p in app.container.ports:
            ports.append({
                "name": p.name,
                "port": p.service_port,
                "targetPort": p.container_port,
                "protocol": p.protocol,
            })
    else:
        ports.append({
            "name": "http",
            "port": primary_port.service_port,
            "targetPort": primary_port.container_port,
            "protocol": "TCP",
        })

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "selector": {
                "app": name,
            },
            "ports": ports,
        },
    }


def generate_httpscaledobject(
    app: AppConfig,
    env: Environment,
    config: AppsYamlConfig,
) -> Optional[Dict[str, Any]]:
    """
    Generate KEDA HTTPScaledObject manifest.

    Args:
        app: App configuration
        env: Target environment
        config: Root apps.yaml config

    Returns:
        HTTPScaledObject manifest dict or None if not using keda-http scaling
    """
    scaling = app.get_effective_scaling(env)
    if scaling.type != ScalingType.KEDA_HTTP:
        return None

    name = _to_k8s_name(app.name)
    primary_port = app.get_primary_port()

    # Host for KEDA routing
    routing_host = f"{name}.{app.namespace}"

    # Path from ingress config
    path_prefix = app.ingress.path if app.ingress.enabled else "/"

    return {
        "apiVersion": "http.keda.sh/v1alpha1",
        "kind": "HTTPScaledObject",
        "metadata": {
            "name": f"{name}-http",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "hosts": [routing_host],
            "pathPrefixes": [path_prefix],
            "scaleTargetRef": {
                "name": name,
                "kind": "Deployment",
                "apiVersion": "apps/v1",
                "service": name,
                "port": primary_port.service_port,
            },
            "replicas": {
                "min": scaling.min_instances,
                "max": scaling.max_instances,
            },
            "scalingMetric": {
                "requestRate": {
                    "granularity": "1s",
                    "targetValue": scaling.target_pending_requests,
                    "window": "1m",
                },
            },
            "scaledownPeriod": scaling.cooldown_period,
        },
    }


def generate_hpa(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate Kubernetes HorizontalPodAutoscaler manifest.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        HPA manifest dict or None if not using HPA scaling
    """
    scaling = app.get_effective_scaling(env)
    if scaling.type != ScalingType.HPA:
        return None

    name = _to_k8s_name(app.name)

    metrics = []
    if scaling.target_cpu_percent:
        metrics.append({
            "type": "Resource",
            "resource": {
                "name": "cpu",
                "target": {
                    "type": "Utilization",
                    "averageUtilization": scaling.target_cpu_percent,
                },
            },
        })
    if scaling.target_memory_percent:
        metrics.append({
            "type": "Resource",
            "resource": {
                "name": "memory",
                "target": {
                    "type": "Utilization",
                    "averageUtilization": scaling.target_memory_percent,
                },
            },
        })

    return {
        "apiVersion": "autoscaling/v2",
        "kind": "HorizontalPodAutoscaler",
        "metadata": {
            "name": name,
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "scaleTargetRef": {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "name": name,
            },
            "minReplicas": scaling.min_instances or 1,
            "maxReplicas": scaling.max_instances,
            "metrics": metrics,
            "behavior": {
                "scaleDown": {
                    "stabilizationWindowSeconds": scaling.scale_down_stabilization,
                },
                "scaleUp": {
                    "stabilizationWindowSeconds": scaling.scale_up_stabilization,
                },
            },
        },
    }


def generate_keda_route_service(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate per-route ExternalName service for KEDA interceptor.

    Required for HAProxy ingress to prevent backend merging.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        Service manifest dict or None if not using ingress
    """
    if not app.ingress.enabled:
        return None

    name = _to_k8s_name(app.name)

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": f"keda-route-{name}",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
                "k3sapp.io/component": "keda-route",
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
    app: AppConfig,
    env: Environment,
    config: AppsYamlConfig,
) -> Optional[Dict[str, Any]]:
    """
    Generate HAProxy Ingress manifest.

    Args:
        app: App configuration
        env: Target environment
        config: Root apps.yaml config

    Returns:
        Ingress manifest dict or None if not using ingress
    """
    if not app.ingress.enabled:
        return None

    name = _to_k8s_name(app.name)
    routing_host = f"{name}.{app.namespace}"

    # Build annotations
    annotations = {
        "haproxy-ingress.github.io/timeout-connect": app.ingress.timeouts.connect,
        "haproxy-ingress.github.io/timeout-server": app.ingress.timeouts.server,
        "haproxy-ingress.github.io/timeout-client": app.ingress.timeouts.client,
        "haproxy-ingress.github.io/timeout-queue": app.ingress.timeouts.queue,
        "haproxy-ingress.github.io/retry-on": "conn-failure,empty-response,response-timeout",
        "haproxy-ingress.github.io/retries": "3",
    }

    # Host header rewrite for KEDA routing
    config_backend = f"http-request set-header Host {routing_host}\n"

    # Strip prefix if configured
    if app.ingress.strip_prefix and app.ingress.path != "/":
        path = app.ingress.path.rstrip("/")
        config_backend += f"http-request set-path %[path,regsub(^{path}/,/),regsub(^{path}$,/)]\n"

    annotations["haproxy-ingress.github.io/config-backend"] = config_backend

    # Merge user annotations
    env_override = app.get_env_override(env)
    if env_override and env_override.ingress_annotations:
        annotations.update(env_override.ingress_annotations)
    annotations.update(app.ingress.annotations)

    ingress = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "Ingress",
        "metadata": {
            "name": f"{name}-haproxy",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
                "k3sapp.io/ingress": "haproxy",
            },
            "annotations": annotations,
        },
        "spec": {
            "ingressClassName": "haproxy",
            "rules": [
                {
                    "http": {
                        "paths": [
                            {
                                "path": app.ingress.path,
                                "pathType": app.ingress.path_type.value,
                                "backend": {
                                    "service": {
                                        "name": f"keda-route-{name}",
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

    # TLS
    if app.ingress.tls and app.ingress.tls.enabled:
        ingress["spec"]["tls"] = [
            {
                "secretName": app.ingress.tls.secret,
                "hosts": app.ingress.tls.hosts or app.ingress.hosts,
            }
        ]

    return ingress


def generate_traefik_ingress(
    app: AppConfig,
    env: Environment,
    config: AppsYamlConfig,
) -> Optional[Dict[str, Any]]:
    """
    Generate Traefik IngressRoute manifest.

    Args:
        app: App configuration
        env: Target environment
        config: Root apps.yaml config

    Returns:
        IngressRoute manifest dict or None if not using ingress
    """
    if not app.ingress.enabled:
        return None

    name = _to_k8s_name(app.name)
    routing_host = f"{name}.{app.namespace}"

    # Build match rule
    match = f"PathPrefix(`{app.ingress.path}`)"
    if app.ingress.hosts:
        host_match = " || ".join(f"Host(`{h}`)" for h in app.ingress.hosts)
        match = f"({host_match}) && {match}"

    return {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "IngressRoute",
        "metadata": {
            "name": f"{name}-routes",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "entryPoints": ["web", "websecure"],
            "routes": [
                {
                    "match": match,
                    "kind": "Rule",
                    "services": [
                        {
                            "name": "keda-interceptor-proxy",
                            "port": 8080,
                        }
                    ],
                    "middlewares": [
                        {"name": f"{name}-host-rewrite", "namespace": app.namespace},
                    ],
                }
            ],
        },
    }


def generate_traefik_middleware(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate Traefik Middleware for host header rewrite.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        Middleware manifest dict or None if not using ingress
    """
    if not app.ingress.enabled:
        return None

    name = _to_k8s_name(app.name)
    routing_host = f"{name}.{app.namespace}"

    return {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "Middleware",
        "metadata": {
            "name": f"{name}-host-rewrite",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
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


def generate_ingress(
    app: AppConfig,
    env: Environment,
    config: AppsYamlConfig,
) -> List[Dict[str, Any]]:
    """
    Generate ingress manifests based on environment.

    Args:
        app: App configuration
        env: Target environment
        config: Root apps.yaml config

    Returns:
        List of ingress-related manifests
    """
    if not app.ingress.enabled:
        return []

    ingress_type = config.defaults.get_ingress_type(env)
    manifests = []

    if ingress_type == "haproxy":
        # HAProxy: Route service + Ingress
        route_svc = generate_keda_route_service(app, env)
        if route_svc:
            manifests.append(route_svc)

        ing = generate_haproxy_ingress(app, env, config)
        if ing:
            manifests.append(ing)
    else:
        # Traefik: Middleware + IngressRoute
        middleware = generate_traefik_middleware(app, env)
        if middleware:
            manifests.append(middleware)

        route = generate_traefik_ingress(app, env, config)
        if route:
            manifests.append(route)

    return manifests


def generate_network_policy(
    app: AppConfig,
    env: Environment,
    config: AppsYamlConfig,
) -> Optional[Dict[str, Any]]:
    """
    Generate Kubernetes NetworkPolicy manifest with ingress and egress.

    Args:
        app: App configuration
        env: Target environment
        config: Root apps.yaml config

    Returns:
        NetworkPolicy manifest dict or None if network policy disabled
    """
    if not app.security.network_policy.enabled:
        return None

    name = _to_k8s_name(app.name)
    primary_port = app.get_primary_port()
    ingress_type = config.defaults.get_ingress_type(env)

    ingress_rules = []

    # Always allow KEDA for scaling (needed for scale-to-zero HTTP functions)
    ingress_rules.append({
        "from": [
            {
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": "keda",
                    },
                },
            },
        ],
        "ports": [{"protocol": "TCP", "port": primary_port.container_port}],
    })

    # Internal: allow from any namespace
    if app.security.visibility == Visibility.INTERNAL:
        ingress_rules.append({
            "from": [{"namespaceSelector": {}}],
            "ports": [{"protocol": "TCP", "port": primary_port.container_port}],
        })

    # Private: allow from same namespace
    elif app.security.visibility == Visibility.PRIVATE:
        ingress_rules.append({
            "from": [{"podSelector": {}}],
            "ports": [{"protocol": "TCP", "port": primary_port.container_port}],
        })

    # Custom allow_from rules
    for rule in app.security.network_policy.allow_from:
        from_spec: Dict[str, Any] = {}
        if rule.namespace:
            from_spec["namespaceSelector"] = {
                "matchLabels": {
                    "kubernetes.io/metadata.name": rule.namespace,
                },
            }
        if rule.pod_labels:
            from_spec["podSelector"] = {"matchLabels": rule.pod_labels}
        if rule.cidr:
            from_spec["ipBlock"] = {"cidr": rule.cidr}

        if from_spec:
            ingress_rules.append({
                "from": [from_spec],
                "ports": [{"protocol": "TCP", "port": primary_port.container_port}],
            })

    # Egress rules
    egress_rules = []
    policy_types = ["Ingress"]

    # Check if egress rules are needed
    if app.security.network_policy.allow_to:
        policy_types.append("Egress")

        # Always allow DNS (kube-dns) for service discovery
        egress_rules.append({
            "to": [
                {
                    "namespaceSelector": {},
                    "podSelector": {
                        "matchLabels": {
                            "k8s-app": "kube-dns",
                        },
                    },
                },
            ],
            "ports": [
                {"protocol": "UDP", "port": 53},
                {"protocol": "TCP", "port": 53},
            ],
        })

        # Custom allow_to rules
        for rule in app.security.network_policy.allow_to:
            to_spec: Dict[str, Any] = {}

            if rule.namespace:
                to_spec["namespaceSelector"] = {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": rule.namespace,
                    },
                }
            if rule.pod_labels:
                to_spec["podSelector"] = {"matchLabels": rule.pod_labels}
            if rule.cidr:
                to_spec["ipBlock"] = {"cidr": rule.cidr}

            if to_spec:
                egress_rules.append({
                    "to": [to_spec],
                })

    network_policy: Dict[str, Any] = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{name}-policy",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
                "k3sapp.io/visibility": app.security.visibility.value,
            },
        },
        "spec": {
            "podSelector": {
                "matchLabels": {
                    "app": name,
                },
            },
            "policyTypes": policy_types,
            "ingress": ingress_rules,
        },
    }

    # Add egress rules if present
    if egress_rules:
        network_policy["spec"]["egress"] = egress_rules

    return network_policy


def generate_pdb(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate Kubernetes PodDisruptionBudget manifest.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        PDB manifest dict or None if not configured
    """
    env_override = app.get_env_override(env)
    if not env_override or not env_override.pod_disruption_budget:
        return None

    pdb = env_override.pod_disruption_budget
    if pdb.min_available is None and pdb.max_unavailable is None:
        return None

    name = _to_k8s_name(app.name)

    spec: Dict[str, Any] = {
        "selector": {
            "matchLabels": {
                "app": name,
            },
        },
    }

    if pdb.min_available is not None:
        spec["minAvailable"] = pdb.min_available
    elif pdb.max_unavailable is not None:
        spec["maxUnavailable"] = pdb.max_unavailable

    return {
        "apiVersion": "policy/v1",
        "kind": "PodDisruptionBudget",
        "metadata": {
            "name": name,
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": spec,
    }


def generate_service_account(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate Kubernetes ServiceAccount manifest.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        ServiceAccount manifest dict or None if not creating service account
    """
    if not app.security.create_service_account:
        return None

    if not app.security.service_account:
        return None

    sa: Dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": app.security.service_account,
            "namespace": app.namespace,
            "labels": {
                "k3sapp.io/app": app.name,
            },
        },
    }

    # Add annotations (e.g., for GCP Workload Identity)
    if app.security.service_account_annotations:
        sa["metadata"]["annotations"] = app.security.service_account_annotations

    return sa


def generate_pvc(vol: VolumeConfig, namespace: str) -> Dict[str, Any]:
    """
    Generate PersistentVolumeClaim for PVC volumes.

    Args:
        vol: Volume configuration
        namespace: Namespace

    Returns:
        PVC manifest dict
    """
    return {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": vol.name,
            "namespace": namespace,
        },
        "spec": {
            "accessModes": vol.access_modes,
            "storageClassName": vol.storage_class or "standard",
            "resources": {
                "requests": {
                    "storage": vol.size or "1Gi",
                },
            },
        },
    }


def generate_trigger_authentication(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate KEDA TriggerAuthentication for Redis/Valkey queue scaling.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        TriggerAuthentication manifest dict or None if not using queue scaling
    """
    scaling = app.get_effective_scaling(env)
    if scaling.type != ScalingType.KEDA_QUEUE:
        return None

    name = _to_k8s_name(app.name)

    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "TriggerAuthentication",
        "metadata": {
            "name": f"{name}-redis-auth",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "secretTargetRef": [
                {
                    "parameter": "password",
                    "name": "valkey-secret",  # Platform-level secret
                    "key": "password",
                },
            ],
        },
    }


def generate_keda_scaledobject_queue(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate KEDA ScaledObject for Redis/Valkey queue scaling.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        ScaledObject manifest dict or None if not using queue scaling
    """
    scaling = app.get_effective_scaling(env)
    if scaling.type != ScalingType.KEDA_QUEUE:
        return None

    if not scaling.queue_name:
        return None

    name = _to_k8s_name(app.name)

    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": f"{name}-queue",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "scaleTargetRef": {
                "name": name,
                "kind": "Deployment",
            },
            "pollingInterval": 15,
            "cooldownPeriod": scaling.cooldown_period,
            "minReplicaCount": scaling.min_instances,
            "maxReplicaCount": scaling.max_instances,
            "triggers": [
                {
                    "type": "redis",
                    "metadata": {
                        "address": "valkey-master.valkey.svc.cluster.local:6379",
                        "listName": scaling.queue_name,
                        "listLength": str(scaling.queue_length),
                        "enableTLS": "false",
                        "databaseIndex": "0",
                    },
                    "authenticationRef": {
                        "name": f"{name}-redis-auth",
                    },
                },
            ],
        },
    }


def generate_keda_scaledobject_cron(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate KEDA ScaledObject for cron-based scaling.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        ScaledObject manifest dict or None if not using cron scaling
    """
    scaling = app.get_effective_scaling(env)
    if scaling.type != ScalingType.KEDA_CRON:
        return None

    name = _to_k8s_name(app.name)

    # Build cron triggers from configured schedules
    triggers = []
    if scaling.cron_schedules:
        # Use configured cron schedules
        for schedule in scaling.cron_schedules:
            triggers.append({
                "type": "cron",
                "metadata": {
                    "timezone": schedule.timezone,
                    "start": schedule.start,
                    "end": schedule.end,
                    "desiredReplicas": str(schedule.replicas),
                },
            })
    else:
        # Fallback to default schedule (8 AM - 6 PM UTC)
        triggers.append({
            "type": "cron",
            "metadata": {
                "timezone": "UTC",
                "start": "0 8 * * *",  # 8 AM
                "end": "0 18 * * *",   # 6 PM
                "desiredReplicas": str(scaling.max_instances),
            },
        })

    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": f"{name}-cron",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "scaleTargetRef": {
                "name": name,
                "kind": "Deployment",
            },
            "cooldownPeriod": scaling.cooldown_period,
            "minReplicaCount": scaling.min_instances,
            "maxReplicaCount": scaling.max_instances,
            "triggers": triggers,
        },
    }


def generate_external_secret(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate ExternalSecret for apps with secret references.

    Uses External Secrets Operator to fetch secrets from GCP Secret Manager
    (or other providers) at runtime.

    Args:
        app: App configuration
        env: Target environment

    Returns:
        ExternalSecret manifest dict or None if no secrets configured
    """
    from .types import SecretProvider

    secret_refs = app.get_secret_refs()
    if not secret_refs:
        return None

    # Skip for local environment - use .env files directly
    if env == Environment.LOCAL:
        return None

    name = _to_k8s_name(app.name)

    # Group secrets by provider - currently only GCP supported
    gcp_secrets = {
        k: v for k, v in secret_refs.items()
        if v.provider == SecretProvider.GCP
    }

    if not gcp_secrets:
        return None

    data = []
    for env_key, ref in gcp_secrets.items():
        entry: Dict[str, Any] = {
            "secretKey": env_key,
            "remoteRef": {
                "key": ref.secret,
            },
        }
        if ref.version != "latest":
            entry["remoteRef"]["version"] = ref.version
        if ref.key:
            entry["remoteRef"]["property"] = ref.key
        data.append(entry)

    return {
        "apiVersion": "external-secrets.io/v1beta1",
        "kind": "ExternalSecret",
        "metadata": {
            "name": f"{name}-secrets",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "refreshInterval": "1h",
            "secretStoreRef": {
                "kind": "ClusterSecretStore",
                "name": "gcp-secret-manager",
            },
            "target": {
                "name": f"{name}-secrets",
                "creationPolicy": "Owner",
            },
            "data": data,
        },
    }


def generate_all_manifests(
    app: AppConfig,
    env: Environment,
    config: AppsYamlConfig,
) -> List[Dict[str, Any]]:
    """
    Generate all Kubernetes manifests for an app.

    Args:
        app: App configuration
        env: Target environment
        config: Root apps.yaml config

    Returns:
        List of all manifest dicts
    """
    from .schema import resolve_registry_url

    manifests = []

    # Container image
    image = resolve_registry_url(app, env, config)

    # ExternalSecret (before Deployment so secrets are available)
    external_secret = generate_external_secret(app, env)
    if external_secret:
        manifests.append(external_secret)

    # ServiceAccount (before Deployment)
    if app.security.create_service_account:
        sa = generate_service_account(app, env)
        if sa:
            manifests.append(sa)

    # Core resources
    manifests.append(generate_deployment(app, env, image, config))
    manifests.append(generate_service(app, env))

    # Scaling
    scaling = app.get_effective_scaling(env)
    if scaling.type == ScalingType.KEDA_HTTP:
        httpso = generate_httpscaledobject(app, env, config)
        if httpso:
            manifests.append(httpso)
    elif scaling.type == ScalingType.HPA:
        hpa = generate_hpa(app, env)
        if hpa:
            manifests.append(hpa)
    elif scaling.type == ScalingType.KEDA_QUEUE:
        # TriggerAuthentication for Redis auth
        trigger_auth = generate_trigger_authentication(app, env)
        if trigger_auth:
            manifests.append(trigger_auth)
        # ScaledObject for queue-based scaling
        queue_so = generate_keda_scaledobject_queue(app, env)
        if queue_so:
            manifests.append(queue_so)
    elif scaling.type == ScalingType.KEDA_CRON:
        # ScaledObject for cron-based scaling
        cron_so = generate_keda_scaledobject_cron(app, env)
        if cron_so:
            manifests.append(cron_so)

    # Ingress
    manifests.extend(generate_ingress(app, env, config))

    # Network policy
    netpol = generate_network_policy(app, env, config)
    if netpol:
        manifests.append(netpol)

    # PDB
    pdb = generate_pdb(app, env)
    if pdb:
        manifests.append(pdb)

    # PVCs
    for vol in app.volumes:
        if vol.type == VolumeType.PVC:
            manifests.append(generate_pvc(vol, app.namespace))

    return manifests
