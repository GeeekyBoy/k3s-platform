"""
Type definitions for K3s App configuration.

These dataclasses represent the apps.yaml v2 schema for traditional apps.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Environment(str, Enum):
    """Deployment environment."""
    LOCAL = "local"
    DEV = "dev"
    GCP = "gcp"


class ScalingType(str, Enum):
    """Type of autoscaling to use."""
    HPA = "hpa"
    KEDA_HTTP = "keda-http"
    KEDA_QUEUE = "keda-queue"
    KEDA_CRON = "keda-cron"
    NONE = "none"


class Visibility(str, Enum):
    """Network visibility/access control.

    Note: PUBLIC visibility is not available. External access is controlled
    through gateway routes in apps.yaml. All apps are internal by default.

    - INTERNAL: Accessible from any pod in any namespace
    - PRIVATE: Accessible only from pods in the same namespace
    - RESTRICTED: Accessible only from specific pods/namespaces (via allow_from)
    """
    INTERNAL = "internal"
    PRIVATE = "private"
    RESTRICTED = "restricted"


class PathType(str, Enum):
    """Ingress path matching type."""
    PREFIX = "Prefix"
    EXACT = "Exact"
    IMPLEMENTATION_SPECIFIC = "ImplementationSpecific"


class VolumeType(str, Enum):
    """Volume type."""
    EMPTY_DIR = "emptyDir"
    PVC = "pvc"
    SECRET = "secret"
    CONFIGMAP = "configmap"


class ProbeType(str, Enum):
    """Health check probe type."""
    HTTP = "http"
    TCP = "tcp"
    EXEC = "exec"


class SecretProvider(str, Enum):
    """Secret provider for external secrets."""
    GCP = "gcp"
    AWS = "aws"
    VAULT = "vault"
    AZURE = "azure"


@dataclass
class SecretRef:
    """Reference to an external secret.

    Used for runtime secret fetching via External Secrets Operator.
    """
    secret: str  # Secret name/path in provider
    provider: SecretProvider = SecretProvider.GCP
    version: str = "latest"
    key: Optional[str] = None  # For multi-value secrets (JSON key)

    @classmethod
    def from_dict(cls, data: Dict) -> "SecretRef":
        provider = data.get("provider", "gcp")
        return cls(
            secret=data["secret"],
            provider=SecretProvider(provider) if provider else SecretProvider.GCP,
            version=data.get("version", "latest"),
            key=data.get("key"),
        )


@dataclass
class EnvironmentValue:
    """Environment variable value - either literal string or secret reference.

    Supports three types:
    - Literal value: "info"
    - Variable reference: "${VAR}" or "${VAR:-default}"
    - Secret reference: {"secret": "secret-name", "provider": "gcp"}
    """
    value: Optional[str] = None  # Literal or ${VAR} reference
    secret_ref: Optional[SecretRef] = None  # Secret reference

    @classmethod
    def from_value(cls, data: Any) -> "EnvironmentValue":
        if isinstance(data, str):
            return cls(value=data)
        elif isinstance(data, dict) and "secret" in data:
            return cls(secret_ref=SecretRef.from_dict(data))
        else:
            raise ValueError(f"Invalid environment value: {data}")

    def is_secret(self) -> bool:
        """Check if this is a secret reference."""
        return self.secret_ref is not None


@dataclass
class CronSchedule:
    """Cron schedule for time-based scaling.

    Used with KEDA Cron scaler for predictable traffic patterns.
    """
    timezone: str = "UTC"
    start: str = "0 8 * * *"   # 8 AM
    end: str = "0 18 * * *"    # 6 PM
    replicas: int = 5

    @classmethod
    def from_dict(cls, data: Dict) -> "CronSchedule":
        return cls(
            timezone=data.get("timezone", "UTC"),
            start=data["start"],
            end=data["end"],
            replicas=data["replicas"],
        )


@dataclass
class ResourcesConfig:
    """Resource requests and limits."""
    memory: str = "256Mi"
    cpu: str = "100m"
    memory_limit: Optional[str] = None
    cpu_limit: Optional[str] = None
    ephemeral_storage: Optional[str] = None

    def __post_init__(self):
        if self.memory_limit is None:
            self.memory_limit = self.memory

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "ResourcesConfig":
        if not data:
            return cls()
        return cls(
            memory=data.get("memory", "256Mi"),
            cpu=data.get("cpu", "100m"),
            memory_limit=data.get("memory_limit"),
            cpu_limit=data.get("cpu_limit"),
            ephemeral_storage=data.get("ephemeral_storage"),
        )


@dataclass
class ScalingConfig:
    """Autoscaling configuration."""
    type: ScalingType = ScalingType.KEDA_HTTP
    min_instances: int = 0
    max_instances: int = 10
    target_pending_requests: int = 100
    queue_name: Optional[str] = None
    queue_length: int = 5
    target_cpu_percent: int = 80
    target_memory_percent: int = 80
    cooldown_period: int = 300
    scale_up_stabilization: int = 0
    scale_down_stabilization: int = 300
    cron_schedules: List[CronSchedule] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "ScalingConfig":
        if not data:
            return cls()
        scaling_type = data.get("type", "keda-http")
        cron_schedules = [
            CronSchedule.from_dict(s)
            for s in data.get("cron_schedules", [])
        ]
        return cls(
            type=ScalingType(scaling_type) if scaling_type else ScalingType.KEDA_HTTP,
            min_instances=data.get("min_instances", 0),
            max_instances=data.get("max_instances", 10),
            target_pending_requests=data.get("target_pending_requests", 100),
            queue_name=data.get("queue_name"),
            queue_length=data.get("queue_length", 5),
            target_cpu_percent=data.get("target_cpu_percent", 80),
            target_memory_percent=data.get("target_memory_percent", 80),
            cooldown_period=data.get("cooldown_period", 300),
            scale_up_stabilization=data.get("scale_up_stabilization", 0),
            scale_down_stabilization=data.get("scale_down_stabilization", 300),
            cron_schedules=cron_schedules,
        )


@dataclass
class ProbeConfig:
    """Health check probe configuration."""
    type: ProbeType = ProbeType.HTTP
    path: str = "/health"
    port: int = 8080
    command: Optional[List[str]] = None
    initial_delay: int = 0
    period: int = 10
    timeout: int = 1
    success_threshold: int = 1
    failure_threshold: int = 3

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["ProbeConfig"]:
        if not data:
            return None
        probe_type = data.get("type", "http")
        return cls(
            type=ProbeType(probe_type) if probe_type else ProbeType.HTTP,
            path=data.get("path", "/health"),
            port=data.get("port", 8080),
            command=data.get("command"),
            initial_delay=data.get("initial_delay", 0),
            period=data.get("period", 10),
            timeout=data.get("timeout", 1),
            success_threshold=data.get("success_threshold", 1),
            failure_threshold=data.get("failure_threshold", 3),
        )


@dataclass
class ProbesConfig:
    """Collection of health check probes."""
    startup: Optional[ProbeConfig] = None
    readiness: Optional[ProbeConfig] = None
    liveness: Optional[ProbeConfig] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "ProbesConfig":
        if not data:
            return cls()
        return cls(
            startup=ProbeConfig.from_dict(data.get("startup")),
            readiness=ProbeConfig.from_dict(data.get("readiness")),
            liveness=ProbeConfig.from_dict(data.get("liveness")),
        )


@dataclass
class TlsConfig:
    """TLS configuration for ingress."""
    enabled: bool = False
    secret: Optional[str] = None
    hosts: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["TlsConfig"]:
        if not data:
            return None
        return cls(
            enabled=data.get("enabled", False),
            secret=data.get("secret"),
            hosts=data.get("hosts", []),
        )


@dataclass
class TimeoutsConfig:
    """Timeout configuration for ingress."""
    connect: str = "10s"
    server: str = "180s"
    client: str = "180s"
    queue: str = "180s"

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "TimeoutsConfig":
        if not data:
            return cls()
        return cls(
            connect=data.get("connect", "10s"),
            server=data.get("server", "180s"),
            client=data.get("client", "180s"),
            queue=data.get("queue", "180s"),
        )


@dataclass
class IngressConfig:
    """Ingress configuration."""
    enabled: bool = False
    ingress_class: Optional[str] = None
    path: str = "/"
    path_type: PathType = PathType.PREFIX
    strip_prefix: bool = False
    rewrite_target: Optional[str] = None
    hosts: List[str] = field(default_factory=list)
    tls: Optional[TlsConfig] = None
    timeouts: TimeoutsConfig = field(default_factory=TimeoutsConfig)
    annotations: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "IngressConfig":
        if not data:
            return cls()
        path_type = data.get("path_type", "Prefix")
        return cls(
            enabled=data.get("enabled", False),
            ingress_class=data.get("class"),
            path=data.get("path", "/"),
            path_type=PathType(path_type) if path_type else PathType.PREFIX,
            strip_prefix=data.get("strip_prefix", False),
            rewrite_target=data.get("rewrite_target"),
            hosts=data.get("hosts", []),
            tls=TlsConfig.from_dict(data.get("tls")),
            timeouts=TimeoutsConfig.from_dict(data.get("timeouts")),
            annotations=data.get("annotations", {}),
        )


@dataclass
class NetworkPolicyRule:
    """Network policy rule for allow_from/allow_to."""
    namespace: Optional[str] = None
    pod_labels: Dict[str, str] = field(default_factory=dict)
    cidr: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["NetworkPolicyRule"]:
        if not data:
            return None
        return cls(
            namespace=data.get("namespace"),
            pod_labels=data.get("pod_labels", {}),
            cidr=data.get("cidr"),
        )


@dataclass
class NetworkPolicyConfig:
    """Network policy configuration."""
    enabled: bool = True
    allow_from: List[NetworkPolicyRule] = field(default_factory=list)
    allow_to: List[NetworkPolicyRule] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Any) -> "NetworkPolicyConfig":
        if data is None:
            return cls()
        if isinstance(data, bool):
            return cls(enabled=data)
        if isinstance(data, dict):
            allow_from = [
                NetworkPolicyRule.from_dict(r)
                for r in data.get("allow_from", [])
                if r
            ]
            allow_to = [
                NetworkPolicyRule.from_dict(r)
                for r in data.get("allow_to", [])
                if r
            ]
            return cls(
                enabled=data.get("enabled", True),
                allow_from=[r for r in allow_from if r],
                allow_to=[r for r in allow_to if r],
            )
        return cls()


@dataclass
class PodSecurityContext:
    """Pod security context."""
    run_as_non_root: bool = True
    run_as_user: Optional[int] = None
    run_as_group: Optional[int] = None
    fs_group: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["PodSecurityContext"]:
        if not data:
            return None
        return cls(
            run_as_non_root=data.get("run_as_non_root", True),
            run_as_user=data.get("run_as_user"),
            run_as_group=data.get("run_as_group"),
            fs_group=data.get("fs_group"),
        )


@dataclass
class ContainerSecurityContext:
    """Container security context."""
    allow_privilege_escalation: bool = False
    read_only_root_filesystem: bool = False
    capabilities_drop: List[str] = field(default_factory=list)
    capabilities_add: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["ContainerSecurityContext"]:
        if not data:
            return None
        caps = data.get("capabilities", {})
        return cls(
            allow_privilege_escalation=data.get("allow_privilege_escalation", False),
            read_only_root_filesystem=data.get("read_only_root_filesystem", False),
            capabilities_drop=caps.get("drop", []),
            capabilities_add=caps.get("add", []),
        )


@dataclass
class SecurityConfig:
    """Security configuration."""
    visibility: Visibility = Visibility.PRIVATE
    network_policy: NetworkPolicyConfig = field(default_factory=NetworkPolicyConfig)
    service_account: Optional[str] = None
    create_service_account: bool = False
    service_account_annotations: Dict[str, str] = field(default_factory=dict)
    pod_security_context: Optional[PodSecurityContext] = None
    container_security_context: Optional[ContainerSecurityContext] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "SecurityConfig":
        if not data:
            return cls()
        visibility = data.get("visibility", "private")
        return cls(
            visibility=Visibility(visibility) if visibility else Visibility.PRIVATE,
            network_policy=NetworkPolicyConfig.from_dict(data.get("network_policy")),
            service_account=data.get("service_account"),
            create_service_account=data.get("create_service_account", False),
            service_account_annotations=data.get("service_account_annotations", {}),
            pod_security_context=PodSecurityContext.from_dict(
                data.get("pod_security_context")
            ),
            container_security_context=ContainerSecurityContext.from_dict(
                data.get("container_security_context")
            ),
        )


@dataclass
class VolumeConfig:
    """Volume configuration."""
    name: str
    type: VolumeType
    mount_path: str
    read_only: bool = False
    medium: Optional[str] = None
    size_limit: Optional[str] = None
    size: Optional[str] = None
    storage_class: Optional[str] = None
    access_modes: List[str] = field(default_factory=lambda: ["ReadWriteOnce"])
    secret_name: Optional[str] = None
    configmap_name: Optional[str] = None
    items: List[Dict[str, str]] = field(default_factory=list)

    @classmethod
    def from_dict(cls, data: Dict) -> "VolumeConfig":
        vol_type = data.get("type", "emptyDir")
        return cls(
            name=data["name"],
            type=VolumeType(vol_type),
            mount_path=data["mount_path"],
            read_only=data.get("read_only", False),
            medium=data.get("medium"),
            size_limit=data.get("size_limit"),
            size=data.get("size"),
            storage_class=data.get("storage_class"),
            access_modes=data.get("access_modes", ["ReadWriteOnce"]),
            secret_name=data.get("secret_name"),
            configmap_name=data.get("configmap_name"),
            items=data.get("items", []),
        )


@dataclass
class EnvFromConfig:
    """Environment variable source reference."""
    type: str  # "secret" or "configmap"
    name: str
    prefix: str = ""
    optional: bool = False

    @classmethod
    def from_dict(cls, data: Dict) -> "EnvFromConfig":
        # Support both old format (secret/configmap key) and new format (type/name)
        if "type" in data:
            return cls(
                type=data["type"],
                name=data["name"],
                prefix=data.get("prefix", ""),
                optional=data.get("optional", False),
            )
        elif "secret" in data:
            return cls(
                type="secret",
                name=data["secret"],
                prefix=data.get("prefix", ""),
                optional=data.get("optional", False),
            )
        elif "configmap" in data:
            return cls(
                type="configmap",
                name=data["configmap"],
                prefix=data.get("prefix", ""),
                optional=data.get("optional", False),
            )
        else:
            raise ValueError(f"Invalid env_from config: {data}")


@dataclass
class PortConfig:
    """Container port configuration."""
    name: str = "http"
    container_port: int = 8080
    service_port: int = 80
    protocol: str = "TCP"

    @classmethod
    def from_dict(cls, data: Dict) -> "PortConfig":
        return cls(
            name=data.get("name", "http"),
            container_port=data.get("container_port", 8080),
            service_port=data.get("service_port", 80),
            protocol=data.get("protocol", "TCP"),
        )


@dataclass
class ContainerConfig:
    """Container configuration."""
    command: Optional[List[str]] = None
    args: Optional[List[str]] = None
    ports: List[PortConfig] = field(default_factory=list)
    working_dir: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "ContainerConfig":
        if not data:
            return cls()
        ports = [PortConfig.from_dict(p) for p in data.get("ports", [])]
        return cls(
            command=data.get("command"),
            args=data.get("args"),
            ports=ports if ports else [],
            working_dir=data.get("working_dir"),
        )


@dataclass
class BuildConfig:
    """Build configuration."""
    dockerfile: str = "Dockerfile"
    dockerfile_dev: Optional[str] = None
    context: str = "."
    target: Optional[str] = None
    args: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "BuildConfig":
        if not data:
            return cls()
        return cls(
            dockerfile=data.get("dockerfile", "Dockerfile"),
            dockerfile_dev=data.get("dockerfile_dev"),
            context=data.get("context", "."),
            target=data.get("target"),
            args=data.get("args", {}),
        )


@dataclass
class SyncConfig:
    """Live update sync configuration."""
    src: str
    dest: str

    @classmethod
    def from_dict(cls, data: Dict) -> "SyncConfig":
        return cls(src=data["src"], dest=data["dest"])


@dataclass
class PodDisruptionBudgetConfig:
    """Pod disruption budget configuration."""
    min_available: Optional[int] = None
    max_unavailable: Optional[int] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["PodDisruptionBudgetConfig"]:
        if not data:
            return None
        return cls(
            min_available=data.get("min_available"),
            max_unavailable=data.get("max_unavailable"),
        )


@dataclass
class AppEnvOverride:
    """Environment-specific configuration overrides."""
    enabled: Optional[bool] = None
    port: Optional[int] = None
    port_base: Optional[int] = None
    live_update: bool = False
    replicas: Optional[int] = None
    resources: Optional[ResourcesConfig] = None
    scaling: Optional[ScalingConfig] = None
    environment: Dict[str, str] = field(default_factory=dict)
    sync: List[SyncConfig] = field(default_factory=list)
    pod_disruption_budget: Optional[PodDisruptionBudgetConfig] = None
    ingress_annotations: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["AppEnvOverride"]:
        if not data:
            return None
        sync = [SyncConfig.from_dict(s) for s in data.get("sync", [])]
        return cls(
            enabled=data.get("enabled"),
            port=data.get("port"),
            port_base=data.get("port_base"),
            live_update=data.get("live_update", False),
            replicas=data.get("replicas"),
            resources=ResourcesConfig.from_dict(data.get("resources"))
            if data.get("resources")
            else None,
            scaling=ScalingConfig.from_dict(data.get("scaling"))
            if data.get("scaling")
            else None,
            environment=data.get("environment", {}),
            sync=sync,
            pod_disruption_budget=PodDisruptionBudgetConfig.from_dict(
                data.get("pod_disruption_budget")
            ),
            ingress_annotations=data.get("ingress_annotations", {}),
        )


@dataclass
class AppConfig:
    """Complete application configuration."""
    name: str
    path: str
    namespace: str = "apps"
    enabled: bool = True

    # Build
    build: BuildConfig = field(default_factory=BuildConfig)
    dockerfile: Optional[str] = None  # Legacy support
    dockerfile_dev: Optional[str] = None  # Legacy support

    # Container
    container: ContainerConfig = field(default_factory=ContainerConfig)

    # Resources & Scaling
    resources: ResourcesConfig = field(default_factory=ResourcesConfig)
    scaling: ScalingConfig = field(default_factory=ScalingConfig)

    # Health checks
    probes: ProbesConfig = field(default_factory=ProbesConfig)

    # Networking
    ingress: IngressConfig = field(default_factory=IngressConfig)

    # Security
    security: SecurityConfig = field(default_factory=SecurityConfig)

    # Environment (supports both string values and secret references)
    environment: Dict[str, EnvironmentValue] = field(default_factory=dict)
    env_from: List[EnvFromConfig] = field(default_factory=list)

    # Volumes
    volumes: List[VolumeConfig] = field(default_factory=list)

    # Environment overrides
    local: Optional[AppEnvOverride] = None
    dev: Optional[AppEnvOverride] = None
    gcp: Optional[AppEnvOverride] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "AppConfig":
        """Create AppConfig from dictionary."""
        env_from = [EnvFromConfig.from_dict(e) for e in data.get("env_from", [])]
        volumes = [VolumeConfig.from_dict(v) for v in data.get("volumes", [])]

        return cls(
            name=data["name"],
            path=data["path"],
            namespace=data.get("namespace", "apps"),
            enabled=data.get("enabled", True),
            build=BuildConfig.from_dict(data.get("build")),
            dockerfile=data.get("dockerfile"),
            dockerfile_dev=data.get("dockerfile_dev"),
            container=ContainerConfig.from_dict(data.get("container")),
            resources=ResourcesConfig.from_dict(data.get("resources")),
            scaling=ScalingConfig.from_dict(data.get("scaling")),
            probes=ProbesConfig.from_dict(data.get("probes")),
            ingress=IngressConfig.from_dict(data.get("ingress")),
            security=SecurityConfig.from_dict(data.get("security")),
            environment={
                k: EnvironmentValue.from_value(v)
                for k, v in data.get("environment", {}).items()
            },
            env_from=env_from,
            volumes=volumes,
            local=AppEnvOverride.from_dict(data.get("local")),
            dev=AppEnvOverride.from_dict(data.get("dev")),
            gcp=AppEnvOverride.from_dict(data.get("gcp")),
        )

    def get_env_override(self, env: Environment) -> Optional[AppEnvOverride]:
        """Get environment-specific override."""
        return getattr(self, env.value, None)

    def get_effective_scaling(self, env: Environment) -> ScalingConfig:
        """Get effective scaling config with environment override."""
        override = self.get_env_override(env)
        if override and override.scaling:
            return override.scaling
        return self.scaling

    def get_effective_resources(self, env: Environment) -> ResourcesConfig:
        """Get effective resources with environment override."""
        override = self.get_env_override(env)
        if override and override.resources:
            return override.resources
        return self.resources

    def get_effective_environment(self, env: Environment) -> Dict[str, EnvironmentValue]:
        """Get merged environment variables (EnvironmentValue objects)."""
        result = dict(self.environment)
        override = self.get_env_override(env)
        if override:
            # Override environment values are simple strings, wrap them
            for k, v in override.environment.items():
                result[k] = EnvironmentValue(value=v)
        return result

    def get_literal_env_vars(self, env: Environment) -> Dict[str, str]:
        """Get non-secret environment variables for Deployment.

        Returns only literal string values (not secret references).
        Performs ${VAR} and ${VAR:-default} substitution from os.environ.
        """
        import os
        import re

        def substitute_env_var(value: str) -> str:
            """Substitute ${VAR} and ${VAR:-default} patterns."""
            def replace(match: re.Match) -> str:
                var_name = match.group(1)
                default = match.group(3) if match.group(3) else ""
                return os.environ.get(var_name, default)

            pattern = r'\$\{([A-Z_][A-Z0-9_]*)(:-(.*?))?\}'
            return re.sub(pattern, replace, value)

        result = {}
        for key, val in self.get_effective_environment(env).items():
            if not val.is_secret() and val.value is not None:
                result[key] = substitute_env_var(val.value)
        return result

    def get_secret_refs(self) -> Dict[str, SecretRef]:
        """Get secret references for ExternalSecret generation.

        Returns a dict mapping env var names to their SecretRef objects.
        """
        result = {}
        for key, val in self.environment.items():
            if val.is_secret() and val.secret_ref is not None:
                result[key] = val.secret_ref
        return result

    def get_primary_port(self) -> PortConfig:
        """Get primary container port."""
        if self.container.ports:
            return self.container.ports[0]
        return PortConfig()


@dataclass
class DefaultsConfig:
    """Global defaults configuration."""
    namespace: str = "apps"
    registry: Dict[str, str] = field(default_factory=dict)
    ingress: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "DefaultsConfig":
        if not data:
            return cls()
        return cls(
            namespace=data.get("namespace", "apps"),
            registry=data.get("registry", {}),
            ingress=data.get("ingress", {}),
        )

    def get_registry(self, env: Environment) -> str:
        """Get registry URL for environment."""
        return self.registry.get(env.value, "")

    def get_ingress_type(self, env: Environment) -> str:
        """Get ingress type for environment."""
        return self.ingress.get(env.value, "traefik")


@dataclass
class EnvironmentSpecificConfig:
    """Environment-specific global settings."""
    domain: str = "localhost"
    tls: bool = False
    tls_secret: Optional[str] = None
    debug: bool = False

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "EnvironmentSpecificConfig":
        if not data:
            return cls()
        return cls(
            domain=data.get("domain", "localhost"),
            tls=data.get("tls", False),
            tls_secret=data.get("tls_secret"),
            debug=data.get("debug", False),
        )


@dataclass
class AppsYamlConfig:
    """Root apps.yaml configuration."""
    version: str = "2"
    defaults: DefaultsConfig = field(default_factory=DefaultsConfig)
    environments: Dict[str, EnvironmentSpecificConfig] = field(default_factory=dict)
    apps: List[AppConfig] = field(default_factory=list)
    repositories: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict) -> "AppsYamlConfig":
        """Create AppsYamlConfig from dictionary."""
        environments = {}
        for env_name, env_data in data.get("environments", {}).items():
            environments[env_name] = EnvironmentSpecificConfig.from_dict(env_data)

        apps = [AppConfig.from_dict(a) for a in data.get("apps", [])]

        return cls(
            version=data.get("version", "2"),
            defaults=DefaultsConfig.from_dict(data.get("defaults")),
            environments=environments,
            apps=apps,
            repositories=data.get("repositories", {}),
        )

    def get_environment_config(self, env: Environment) -> EnvironmentSpecificConfig:
        """Get environment-specific config."""
        return self.environments.get(env.value, EnvironmentSpecificConfig())

    def get_app(self, name: str) -> Optional[AppConfig]:
        """Get app config by name."""
        for app in self.apps:
            if app.name == name:
                return app
        return None
