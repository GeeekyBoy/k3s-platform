"""
Kubernetes manifest generators for Docker Compose projects.

Converts docker-compose services to Kubernetes Deployment, Service, ConfigMap, etc.
"""

import re
from typing import Any, Dict, List, Optional

from .types import (
    ComposeConfig,
    ComposeOverrides,
    ComposeProject,
    ComposeService,
    ComposeVolume,
    EgressRule,
    Environment,
    NetworkPolicyConfig,
    RestartPolicy,
    SecretProvider,
    SecretRef,
    SecurityConfig,
    VolumeMount,
)


def _to_k8s_name(name: str) -> str:
    """Convert name to valid K8s resource name."""
    # Replace underscores and invalid chars
    name = re.sub(r"[^a-z0-9-]", "-", name.lower())
    # Remove leading/trailing dashes
    name = name.strip("-")
    # Collapse multiple dashes
    name = re.sub(r"-+", "-", name)
    return name[:63]  # K8s name limit


def _parse_duration(duration: str) -> int:
    """Parse docker-compose duration to seconds."""
    if not duration:
        return 0

    total = 0
    match = re.match(r"(\d+)(s|m|h)?", duration)
    if match:
        value = int(match.group(1))
        unit = match.group(2) or "s"
        if unit == "m":
            total = value * 60
        elif unit == "h":
            total = value * 3600
        else:
            total = value
    return total


def _convert_memory(memory: str) -> str:
    """Convert docker-compose memory format to K8s format."""
    if not memory:
        return "256Mi"

    # Already in K8s format
    if memory.endswith(("Mi", "Gi", "Ki")):
        return memory

    # Docker format: 512m, 1g, etc
    memory = memory.lower()
    if memory.endswith("g"):
        return f"{memory[:-1]}Gi"
    elif memory.endswith("m"):
        return f"{memory[:-1]}Mi"
    elif memory.endswith("k"):
        return f"{memory[:-1]}Ki"
    return memory


def _convert_cpu(cpus: str) -> str:
    """Convert docker-compose CPU format to K8s format."""
    if not cpus:
        return "100m"

    # Already in K8s format
    if cpus.endswith("m"):
        return cpus

    # Docker format: 0.5, 1.0, etc (cores)
    try:
        cores = float(cpus)
        return f"{int(cores * 1000)}m"
    except ValueError:
        return cpus


def generate_deployment(
    service: ComposeService,
    project: ComposeProject,
    namespace: str,
    registry: Optional[str] = None,
    overrides: Optional[ComposeOverrides] = None,
) -> Dict[str, Any]:
    """
    Generate Kubernetes Deployment from compose service.

    Args:
        service: Compose service
        project: Parent compose project
        namespace: Target namespace
        registry: Optional container registry prefix
        overrides: Optional configuration overrides

    Returns:
        Deployment manifest dict
    """
    name = _to_k8s_name(service.name)
    project_name = _to_k8s_name(project.name)

    # Determine image
    if service.image:
        image = service.image
    elif service.build:
        # Build context - need to use registry
        if registry:
            image = f"{registry}/{project_name}-{name}:latest"
        else:
            image = f"{project_name}-{name}:latest"
    else:
        raise ValueError(f"Service {service.name} has no image or build context")

    # Determine replicas
    replicas = service.deploy.replicas
    if overrides and overrides.replicas:
        replicas = overrides.replicas

    # Build container spec
    container: Dict[str, Any] = {
        "name": name,
        "image": image,
    }

    # Ports
    if service.ports:
        container["ports"] = [
            {
                "containerPort": p.container_port,
                "protocol": p.protocol,
            }
            for p in service.ports
        ]

    # Command/entrypoint
    if service.entrypoint:
        container["command"] = service.entrypoint
    if service.command:
        container["args"] = service.command

    # Working directory
    if service.working_dir:
        container["workingDir"] = service.working_dir

    # Environment variables
    env_vars = []
    for key, value in service.environment.items():
        env_vars.append({"name": key, "value": str(value)})

    # Merge overrides environment
    if overrides and overrides.environment:
        for key, value in overrides.environment.items():
            # Remove existing if overriding
            env_vars = [e for e in env_vars if e["name"] != key]
            env_vars.append({"name": key, "value": str(value)})

    if env_vars:
        container["env"] = env_vars

    # Resources
    resources = _build_resources(service, overrides)
    if resources:
        container["resources"] = resources

    # Health checks
    if service.healthcheck:
        probe = _build_probe(service.healthcheck)
        if probe:
            container["livenessProbe"] = probe
            container["readinessProbe"] = probe

    # Volume mounts
    volume_mounts = []
    for vol in service.volumes:
        if vol.type == "volume" or vol.type == "bind":
            mount = {
                "name": _to_k8s_name(vol.source) if vol.source else f"vol-{len(volume_mounts)}",
                "mountPath": vol.target,
            }
            if vol.read_only:
                mount["readOnly"] = True
            volume_mounts.append(mount)

    if volume_mounts:
        container["volumeMounts"] = volume_mounts

    # User
    security_context = {}
    if service.user:
        try:
            user_parts = service.user.split(":")
            if user_parts[0].isdigit():
                security_context["runAsUser"] = int(user_parts[0])
            if len(user_parts) > 1 and user_parts[1].isdigit():
                security_context["runAsGroup"] = int(user_parts[1])
        except (ValueError, IndexError):
            pass

    if security_context:
        container["securityContext"] = security_context

    # Pod spec
    pod_spec: Dict[str, Any] = {
        "containers": [container],
    }

    # Volumes
    volumes = _build_volumes(service, project)
    if volumes:
        pod_spec["volumes"] = volumes

    # Restart policy (for Jobs, not Deployments)
    # Deployments always restart

    deployment = {
        "apiVersion": "apps/v1",
        "kind": "Deployment",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3scompose.io/project": project_name,
                "k3scompose.io/service": service.name,
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
                        "k3scompose.io/project": project_name,
                        "k3scompose.io/service": service.name,
                    },
                },
                "spec": pod_spec,
            },
        },
    }

    return deployment


def _build_resources(
    service: ComposeService,
    overrides: Optional[ComposeOverrides] = None,
) -> Dict[str, Any]:
    """Build resource requests and limits."""
    resources: Dict[str, Any] = {}

    # From deploy config
    if service.deploy.limits:
        limits: Dict[str, str] = {}
        if service.deploy.limits.memory:
            limits["memory"] = _convert_memory(service.deploy.limits.memory)
        if service.deploy.limits.cpus:
            limits["cpu"] = _convert_cpu(service.deploy.limits.cpus)
        if limits:
            resources["limits"] = limits

    if service.deploy.reservations:
        requests: Dict[str, str] = {}
        if service.deploy.reservations.memory:
            requests["memory"] = _convert_memory(service.deploy.reservations.memory)
        if service.deploy.reservations.cpus:
            requests["cpu"] = _convert_cpu(service.deploy.reservations.cpus)
        if requests:
            resources["requests"] = requests

    # Override from apps.yaml
    if overrides and overrides.resources:
        res = overrides.resources
        if "memory" in res or "cpu" in res:
            if "requests" not in resources:
                resources["requests"] = {}
            if res.get("memory"):
                resources["requests"]["memory"] = res["memory"]
            if res.get("cpu"):
                resources["requests"]["cpu"] = res["cpu"]

        if "memory_limit" in res or "cpu_limit" in res:
            if "limits" not in resources:
                resources["limits"] = {}
            if res.get("memory_limit"):
                resources["limits"]["memory"] = res["memory_limit"]
            elif res.get("memory"):
                resources["limits"]["memory"] = res["memory"]
            if res.get("cpu_limit"):
                resources["limits"]["cpu"] = res["cpu_limit"]

    return resources


def _build_probe(healthcheck) -> Optional[Dict[str, Any]]:
    """Build Kubernetes probe from docker-compose healthcheck."""
    if not healthcheck or not healthcheck.test:
        return None

    probe: Dict[str, Any] = {
        "periodSeconds": _parse_duration(healthcheck.interval) or 30,
        "timeoutSeconds": _parse_duration(healthcheck.timeout) or 30,
        "failureThreshold": healthcheck.retries,
    }

    start_period = _parse_duration(healthcheck.start_period)
    if start_period > 0:
        probe["initialDelaySeconds"] = start_period

    test = healthcheck.test
    if len(test) > 0:
        if test[0] == "CMD":
            probe["exec"] = {"command": test[1:]}
        elif test[0] == "CMD-SHELL":
            probe["exec"] = {"command": ["/bin/sh", "-c", " ".join(test[1:])]}
        elif test[0] == "NONE":
            return None
        else:
            # Assume it's a command
            probe["exec"] = {"command": test}

    return probe


def _build_volumes(
    service: ComposeService,
    project: ComposeProject,
) -> List[Dict[str, Any]]:
    """Build volume specs for pod."""
    volumes = []
    seen = set()

    for vol in service.volumes:
        if vol.type == "volume":
            vol_name = _to_k8s_name(vol.source)
            if vol_name in seen:
                continue
            seen.add(vol_name)

            # Named volume -> PVC
            volumes.append({
                "name": vol_name,
                "persistentVolumeClaim": {
                    "claimName": vol_name,
                },
            })
        elif vol.type == "bind":
            # Bind mount -> hostPath (not recommended in production)
            vol_name = _to_k8s_name(vol.source) or f"bind-{len(volumes)}"
            if vol_name in seen:
                continue
            seen.add(vol_name)

            volumes.append({
                "name": vol_name,
                "hostPath": {
                    "path": vol.source,
                    "type": "DirectoryOrCreate",
                },
            })
        elif vol.type == "tmpfs":
            vol_name = f"tmpfs-{len(volumes)}"
            volumes.append({
                "name": vol_name,
                "emptyDir": {
                    "medium": "Memory",
                },
            })

    return volumes


def generate_service(
    service: ComposeService,
    project: ComposeProject,
    namespace: str,
) -> Optional[Dict[str, Any]]:
    """
    Generate Kubernetes Service from compose service.

    Args:
        service: Compose service
        project: Parent compose project
        namespace: Target namespace

    Returns:
        Service manifest dict or None if no ports
    """
    if not service.ports:
        return None

    name = _to_k8s_name(service.name)
    project_name = _to_k8s_name(project.name)

    ports = []
    for i, p in enumerate(service.ports):
        port_name = f"port-{i}" if i > 0 else "http"
        ports.append({
            "name": port_name,
            "port": p.host_port or p.container_port,
            "targetPort": p.container_port,
            "protocol": p.protocol,
        })

    return {
        "apiVersion": "v1",
        "kind": "Service",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3scompose.io/project": project_name,
                "k3scompose.io/service": service.name,
            },
        },
        "spec": {
            "selector": {
                "app": name,
            },
            "ports": ports,
        },
    }


def generate_configmap(
    service: ComposeService,
    project: ComposeProject,
    namespace: str,
    env_file_content: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Generate ConfigMap for service environment from env_file.

    Args:
        service: Compose service
        project: Parent compose project
        namespace: Target namespace
        env_file_content: Parsed env file content

    Returns:
        ConfigMap manifest dict or None if no env files
    """
    if not env_file_content:
        return None

    name = _to_k8s_name(service.name)
    project_name = _to_k8s_name(project.name)

    return {
        "apiVersion": "v1",
        "kind": "ConfigMap",
        "metadata": {
            "name": f"{name}-env",
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3scompose.io/project": project_name,
                "k3scompose.io/service": service.name,
            },
        },
        "data": env_file_content,
    }


def generate_secret(
    name: str,
    namespace: str,
    data: Dict[str, str],
    project_name: str,
) -> Dict[str, Any]:
    """
    Generate Secret manifest.

    Args:
        name: Secret name
        namespace: Target namespace
        data: Secret data (will be base64 encoded by K8s)
        project_name: Project name for labels

    Returns:
        Secret manifest dict
    """
    return {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "k3scompose.io/project": project_name,
            },
        },
        "type": "Opaque",
        "stringData": data,
    }


def generate_pvc(
    volume: ComposeVolume,
    namespace: str,
    project_name: str,
    storage_class: Optional[str] = None,
    size: str = "1Gi",
) -> Dict[str, Any]:
    """
    Generate PersistentVolumeClaim for named volume.

    Args:
        volume: Compose volume definition
        namespace: Target namespace
        project_name: Project name for labels
        storage_class: Optional storage class
        size: Volume size (default: 1Gi)

    Returns:
        PVC manifest dict
    """
    name = _to_k8s_name(volume.name)

    pvc: Dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "PersistentVolumeClaim",
        "metadata": {
            "name": name,
            "namespace": namespace,
            "labels": {
                "k3scompose.io/project": project_name,
                "k3scompose.io/volume": volume.name,
            },
        },
        "spec": {
            "accessModes": ["ReadWriteOnce"],
            "resources": {
                "requests": {
                    "storage": size,
                },
            },
        },
    }

    if storage_class:
        pvc["spec"]["storageClassName"] = storage_class

    return pvc


def generate_service_account(
    config: ComposeConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate Kubernetes ServiceAccount manifest.

    Args:
        config: Compose config with security settings
        env: Target environment

    Returns:
        ServiceAccount manifest dict or None if not needed
    """
    security = config.get_effective_security(env)

    if not security.create_service_account:
        return None

    if not security.service_account:
        return None

    namespace = config.get_effective_namespace(env)
    project_name = _to_k8s_name(config.name)

    sa: Dict[str, Any] = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": security.service_account,
            "namespace": namespace,
            "labels": {
                "k3scompose.io/project": project_name,
            },
        },
    }

    # Add annotations (e.g., for GCP Workload Identity)
    if security.service_account_annotations:
        sa["metadata"]["annotations"] = security.service_account_annotations

    return sa


def generate_network_policy(
    service: ComposeService,
    project: ComposeProject,
    config: ComposeConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """
    Generate Kubernetes NetworkPolicy manifest with ingress and egress rules.

    Args:
        service: Compose service
        project: Parent compose project
        config: Compose config with security settings
        env: Target environment

    Returns:
        NetworkPolicy manifest dict or None if not enabled
    """
    security = config.get_effective_security(env)

    if not security.network_policy.enabled:
        return None

    namespace = config.get_effective_namespace(env)
    name = _to_k8s_name(service.name)
    project_name = _to_k8s_name(project.name)

    # Determine primary port
    primary_port = 80
    if service.ports:
        primary_port = service.ports[0].container_port

    # Build ingress rules - allow from same namespace by default
    ingress_rules = [
        {
            "from": [{"podSelector": {}}],  # Any pod in same namespace
            "ports": [{"protocol": "TCP", "port": primary_port}],
        }
    ]

    # Build egress rules
    egress_rules: List[Dict[str, Any]] = []
    policy_types = ["Ingress"]

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

    # Add custom allow_to rules
    if security.network_policy.allow_to:
        policy_types.append("Egress")

        for rule in security.network_policy.allow_to:
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
            "namespace": namespace,
            "labels": {
                "app": name,
                "k3scompose.io/project": project_name,
                "k3scompose.io/service": service.name,
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

    if "Egress" in policy_types:
        network_policy["spec"]["egress"] = egress_rules

    return network_policy


def generate_external_secret(
    config: ComposeConfig,
    env: Environment,
    secret_refs: Dict[str, SecretRef],
) -> Optional[Dict[str, Any]]:
    """
    Generate ExternalSecret for compose projects with secret references.

    Args:
        config: Compose config
        env: Target environment
        secret_refs: Dict of env var name to SecretRef

    Returns:
        ExternalSecret manifest dict or None if no secrets
    """
    if not secret_refs:
        return None

    # Skip for local environment (use .env files directly)
    if env == Environment.LOCAL:
        return None

    namespace = config.get_effective_namespace(env)
    name = _to_k8s_name(config.name)

    # Group secrets by provider (currently only GCP supported)
    gcp_secrets = {k: v for k, v in secret_refs.items() if v.provider == SecretProvider.GCP}

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
            "namespace": namespace,
            "labels": {
                "k3scompose.io/project": name,
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
    project: ComposeProject,
    config: ComposeConfig,
    env: Environment,
    registry: Optional[str] = None,
    secret_refs: Optional[Dict[str, SecretRef]] = None,
) -> List[Dict[str, Any]]:
    """
    Generate all Kubernetes manifests for a compose project.

    Args:
        project: Parsed compose project
        config: apps.yaml compose config
        env: Target environment
        registry: Optional container registry
        secret_refs: Optional dict of env var name to SecretRef for secrets

    Returns:
        List of all manifest dicts
    """
    manifests = []
    namespace = config.get_effective_namespace(env)
    overrides = config.get_env_override(env)
    project_name = _to_k8s_name(project.name)
    security = config.get_effective_security(env)

    # ServiceAccount (create first, before Deployment references it)
    sa = generate_service_account(config, env)
    if sa:
        manifests.append(sa)

    # ExternalSecret (create before Deployment references it)
    if secret_refs:
        es = generate_external_secret(config, env, secret_refs)
        if es:
            manifests.append(es)

    # Generate PVCs for named volumes
    for vol_name, vol in project.volumes.items():
        if not vol.external:
            pvc = generate_pvc(vol, namespace, project_name)
            manifests.append(pvc)

    # Generate resources for each service
    for service in project.services:
        # Deployment
        deploy = generate_deployment(
            service, project, namespace, registry, overrides
        )

        # Add ServiceAccount reference if configured
        if security.service_account:
            deploy["spec"]["template"]["spec"]["serviceAccountName"] = security.service_account

        # Add envFrom for secrets if configured
        if secret_refs and env != Environment.LOCAL:
            name = _to_k8s_name(config.name)
            env_from = deploy["spec"]["template"]["spec"]["containers"][0].get("envFrom", [])
            env_from.append({
                "secretRef": {
                    "name": f"{name}-secrets",
                }
            })
            deploy["spec"]["template"]["spec"]["containers"][0]["envFrom"] = env_from

        manifests.append(deploy)

        # Service (if has ports)
        svc = generate_service(service, project, namespace)
        if svc:
            manifests.append(svc)

        # NetworkPolicy (if enabled)
        if security.network_policy.enabled:
            netpol = generate_network_policy(service, project, config, env)
            if netpol:
                manifests.append(netpol)

    return manifests
