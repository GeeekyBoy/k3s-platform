"""
Type definitions for k3scompose.

These dataclasses represent Docker Compose and apps.yaml compose configuration.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class Environment(str, Enum):
    """Deployment environment."""
    LOCAL = "local"
    DEV = "dev"
    GCP = "gcp"


class RestartPolicy(str, Enum):
    """Container restart policy."""
    ALWAYS = "always"
    ON_FAILURE = "on-failure"
    UNLESS_STOPPED = "unless-stopped"
    NO = "no"


@dataclass
class PortMapping:
    """Port mapping configuration."""
    host_port: Optional[int]
    container_port: int
    protocol: str = "TCP"

    @classmethod
    def parse(cls, port_spec: str | int | dict) -> "PortMapping":
        """Parse port specification from docker-compose format."""
        if isinstance(port_spec, int):
            return cls(host_port=port_spec, container_port=port_spec)

        if isinstance(port_spec, dict):
            return cls(
                host_port=port_spec.get("published"),
                container_port=port_spec["target"],
                protocol=port_spec.get("protocol", "TCP").upper(),
            )

        # String format: "8080:80" or "80" or "8080:80/udp"
        port_str = str(port_spec)
        protocol = "TCP"
        if "/" in port_str:
            port_str, protocol = port_str.rsplit("/", 1)
            protocol = protocol.upper()

        if ":" in port_str:
            parts = port_str.split(":")
            if len(parts) == 2:
                return cls(
                    host_port=int(parts[0]),
                    container_port=int(parts[1]),
                    protocol=protocol,
                )
            elif len(parts) == 3:
                # IP:host:container
                return cls(
                    host_port=int(parts[1]) if parts[1] else None,
                    container_port=int(parts[2]),
                    protocol=protocol,
                )
        else:
            return cls(
                host_port=None,
                container_port=int(port_str),
                protocol=protocol,
            )


@dataclass
class VolumeMount:
    """Volume mount configuration."""
    source: str
    target: str
    read_only: bool = False
    type: str = "bind"  # bind, volume, tmpfs

    @classmethod
    def parse(cls, volume_spec: str | dict) -> "VolumeMount":
        """Parse volume specification from docker-compose format."""
        if isinstance(volume_spec, dict):
            return cls(
                source=volume_spec.get("source", ""),
                target=volume_spec["target"],
                read_only=volume_spec.get("read_only", False),
                type=volume_spec.get("type", "bind"),
            )

        # String format: "source:target" or "source:target:ro"
        parts = volume_spec.split(":")
        read_only = False

        if len(parts) >= 2:
            source = parts[0]
            target = parts[1]
            if len(parts) >= 3 and parts[2] == "ro":
                read_only = True
        else:
            source = parts[0]
            target = parts[0]

        # Determine type
        vol_type = "bind"
        if source.startswith("/") or source.startswith("./") or source.startswith("../"):
            vol_type = "bind"
        elif source == "":
            vol_type = "tmpfs"
        else:
            vol_type = "volume"

        return cls(source=source, target=target, read_only=read_only, type=vol_type)


@dataclass
class HealthCheck:
    """Container health check configuration."""
    test: List[str]
    interval: str = "30s"
    timeout: str = "30s"
    retries: int = 3
    start_period: str = "0s"

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["HealthCheck"]:
        """Parse from docker-compose healthcheck format."""
        if not data:
            return None

        test = data.get("test", [])
        if isinstance(test, str):
            test = ["CMD-SHELL", test]

        return cls(
            test=test,
            interval=data.get("interval", "30s"),
            timeout=data.get("timeout", "30s"),
            retries=data.get("retries", 3),
            start_period=data.get("start_period", "0s"),
        )


@dataclass
class ResourceLimits:
    """Resource limits configuration."""
    cpus: Optional[str] = None
    memory: Optional[str] = None

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> Optional["ResourceLimits"]:
        """Parse from docker-compose deploy.resources format."""
        if not data:
            return None

        return cls(
            cpus=str(data.get("cpus")) if data.get("cpus") else None,
            memory=data.get("memory"),
        )


@dataclass
class DeployConfig:
    """Deployment configuration from docker-compose."""
    replicas: int = 1
    limits: Optional[ResourceLimits] = None
    reservations: Optional[ResourceLimits] = None
    restart_policy: RestartPolicy = RestartPolicy.ALWAYS

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "DeployConfig":
        """Parse from docker-compose deploy format."""
        if not data:
            return cls()

        resources = data.get("resources", {})
        restart = data.get("restart_policy", {})
        restart_condition = restart.get("condition", "any")

        # Map docker-compose restart conditions to our enum
        restart_map = {
            "any": RestartPolicy.ALWAYS,
            "on-failure": RestartPolicy.ON_FAILURE,
            "none": RestartPolicy.NO,
        }

        return cls(
            replicas=data.get("replicas", 1),
            limits=ResourceLimits.from_dict(resources.get("limits")),
            reservations=ResourceLimits.from_dict(resources.get("reservations")),
            restart_policy=restart_map.get(restart_condition, RestartPolicy.ALWAYS),
        )


@dataclass
class ComposeService:
    """Parsed docker-compose service."""
    name: str
    image: Optional[str] = None
    build: Optional[Dict[str, Any]] = None
    command: Optional[List[str]] = None
    entrypoint: Optional[List[str]] = None
    environment: Dict[str, str] = field(default_factory=dict)
    env_file: List[str] = field(default_factory=list)
    ports: List[PortMapping] = field(default_factory=list)
    volumes: List[VolumeMount] = field(default_factory=list)
    depends_on: List[str] = field(default_factory=list)
    healthcheck: Optional[HealthCheck] = None
    deploy: DeployConfig = field(default_factory=DeployConfig)
    labels: Dict[str, str] = field(default_factory=dict)
    networks: List[str] = field(default_factory=list)
    working_dir: Optional[str] = None
    user: Optional[str] = None
    restart: RestartPolicy = RestartPolicy.ALWAYS

    @classmethod
    def from_dict(cls, name: str, data: Dict) -> "ComposeService":
        """Parse from docker-compose service definition."""
        # Parse ports
        ports = []
        for p in data.get("ports", []):
            ports.append(PortMapping.parse(p))

        # Parse volumes
        volumes = []
        for v in data.get("volumes", []):
            volumes.append(VolumeMount.parse(v))

        # Parse environment
        env = {}
        env_data = data.get("environment", {})
        if isinstance(env_data, list):
            for item in env_data:
                if "=" in item:
                    k, v = item.split("=", 1)
                    env[k] = v
                else:
                    env[item] = ""
        else:
            env = dict(env_data)

        # Parse command
        command = data.get("command")
        if isinstance(command, str):
            command = command.split()

        # Parse entrypoint
        entrypoint = data.get("entrypoint")
        if isinstance(entrypoint, str):
            entrypoint = [entrypoint]

        # Parse depends_on
        depends_on = data.get("depends_on", [])
        if isinstance(depends_on, dict):
            depends_on = list(depends_on.keys())

        # Parse restart
        restart_str = data.get("restart", "always")
        restart_map = {
            "always": RestartPolicy.ALWAYS,
            "on-failure": RestartPolicy.ON_FAILURE,
            "unless-stopped": RestartPolicy.UNLESS_STOPPED,
            "no": RestartPolicy.NO,
        }
        restart = restart_map.get(restart_str, RestartPolicy.ALWAYS)

        return cls(
            name=name,
            image=data.get("image"),
            build=data.get("build") if isinstance(data.get("build"), dict) else
                  {"context": data.get("build")} if data.get("build") else None,
            command=command,
            entrypoint=entrypoint,
            environment=env,
            env_file=data.get("env_file", []) if isinstance(data.get("env_file"), list)
                     else [data.get("env_file")] if data.get("env_file") else [],
            ports=ports,
            volumes=volumes,
            depends_on=depends_on,
            healthcheck=HealthCheck.from_dict(data.get("healthcheck")),
            deploy=DeployConfig.from_dict(data.get("deploy")),
            labels=data.get("labels", {}),
            networks=data.get("networks", []) if isinstance(data.get("networks"), list)
                     else list(data.get("networks", {}).keys()),
            working_dir=data.get("working_dir"),
            user=data.get("user"),
            restart=restart,
        )


@dataclass
class ComposeVolume:
    """Docker Compose volume definition."""
    name: str
    driver: str = "local"
    driver_opts: Dict[str, str] = field(default_factory=dict)
    external: bool = False

    @classmethod
    def from_dict(cls, name: str, data: Optional[Dict]) -> "ComposeVolume":
        """Parse from docker-compose volume definition."""
        if not data:
            return cls(name=name)

        return cls(
            name=name,
            driver=data.get("driver", "local"),
            driver_opts=data.get("driver_opts", {}),
            external=data.get("external", False),
        )


@dataclass
class ComposeProject:
    """Parsed docker-compose project."""
    name: str
    path: str
    services: List[ComposeService] = field(default_factory=list)
    volumes: Dict[str, ComposeVolume] = field(default_factory=dict)
    networks: List[str] = field(default_factory=list)

    @classmethod
    def from_dict(cls, name: str, path: str, data: Dict) -> "ComposeProject":
        """Parse from docker-compose.yaml content."""
        services = []
        for svc_name, svc_data in data.get("services", {}).items():
            services.append(ComposeService.from_dict(svc_name, svc_data))

        volumes = {}
        for vol_name, vol_data in data.get("volumes", {}).items():
            volumes[vol_name] = ComposeVolume.from_dict(vol_name, vol_data)

        networks = list(data.get("networks", {}).keys())

        return cls(
            name=name,
            path=path,
            services=services,
            volumes=volumes,
            networks=networks,
        )


@dataclass
class ComposeOverrides:
    """apps.yaml compose project overrides."""
    namespace: str = "apps"
    enabled: bool = True
    ingress_path: Optional[str] = None
    replicas: Optional[int] = None
    resources: Optional[Dict[str, str]] = None
    scaling: Optional[Dict[str, Any]] = None
    environment: Dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Optional[Dict]) -> "ComposeOverrides":
        """Parse from apps.yaml compose project config."""
        if not data:
            return cls()

        return cls(
            namespace=data.get("namespace", "apps"),
            enabled=data.get("enabled", True),
            ingress_path=data.get("ingress_path"),
            replicas=data.get("replicas"),
            resources=data.get("resources"),
            scaling=data.get("scaling"),
            environment=data.get("environment", {}),
        )


@dataclass
class ComposeConfig:
    """apps.yaml compose project configuration."""
    name: str
    path: str
    file: str = "docker-compose.yaml"
    namespace: str = "apps"
    enabled: bool = True

    # Environment-specific overrides
    local: Optional[ComposeOverrides] = None
    dev: Optional[ComposeOverrides] = None
    gcp: Optional[ComposeOverrides] = None

    @classmethod
    def from_dict(cls, data: Dict) -> "ComposeConfig":
        """Parse from apps.yaml compose entry."""
        return cls(
            name=data["name"],
            path=data["path"],
            file=data.get("file", "docker-compose.yaml"),
            namespace=data.get("namespace", "apps"),
            enabled=data.get("enabled", True),
            local=ComposeOverrides.from_dict(data.get("local")),
            dev=ComposeOverrides.from_dict(data.get("dev")),
            gcp=ComposeOverrides.from_dict(data.get("gcp")),
        )

    def get_env_override(self, env: Environment) -> Optional[ComposeOverrides]:
        """Get environment-specific override."""
        return getattr(self, env.value, None)

    def get_effective_namespace(self, env: Environment) -> str:
        """Get namespace with environment override."""
        override = self.get_env_override(env)
        if override and override.namespace:
            return override.namespace
        return self.namespace

    def is_enabled(self, env: Environment) -> bool:
        """Check if enabled for environment."""
        # First check if globally disabled
        if not self.enabled:
            return False
        # Then check for environment-specific override
        override = self.get_env_override(env)
        # Only consider override.enabled if it was explicitly set to False
        if override and not override.enabled:
            return False
        return True
