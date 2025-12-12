# K3s Platform Schema Generator Refactoring Plan

A comprehensive plan to refactor the four Python libraries (k3sapp, k3sfn, k3sgateway, k3scompose) into a unified, modular, OOP-based architecture using modern Python 3.12 features.

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Current State Analysis](#2-current-state-analysis)
3. [Target Architecture](#3-target-architecture)
4. [Core Design Patterns](#4-core-design-patterns)
5. [Module Structure](#5-module-structure)
6. [Abstract Base Classes](#6-abstract-base-classes)
7. [Manifest Generators](#7-manifest-generators)
8. [Environment Strategy Pattern](#8-environment-strategy-pattern)
9. [App Type Implementations](#9-app-type-implementations)
10. [Plugin System](#10-plugin-system)
11. [Configuration Schema](#11-configuration-schema)
12. [CLI Architecture](#12-cli-architecture)
13. [Testing Strategy](#13-testing-strategy)
14. [Migration Strategy](#14-migration-strategy)
15. [Implementation Checklist](#15-implementation-checklist)

---

## 1. Executive Summary

### Goals

1. **Unified Codebase**: Single library (`k3sgen`) replacing four separate libraries
2. **Clean OOP Architecture**: Abstract base classes with concrete implementations per app type
3. **Strategy Pattern for Environments**: Pluggable environment strategies (local, dev, gcp)
4. **Extensible Manifest Generators**: Each K8s resource type as a separate generator class
5. **Modern Python 3.12**: Type hints, dataclasses, protocols, pattern matching, `|` union types
6. **Plugin System**: Easy addition of new app types, environments, and manifest types
7. **100% Test Coverage**: Comprehensive unit and integration tests

### Key Benefits

- **Maintainability**: Single source of truth, DRY principles
- **Extensibility**: Add new app types/environments without modifying core code
- **Testability**: Isolated components with clear interfaces
- **Type Safety**: Full type coverage with mypy strict mode
- **Documentation**: Self-documenting code with docstrings and type hints

---

## 2. Current State Analysis

### Existing Libraries

| Library | Purpose | Files | Lines of Code |
|---------|---------|-------|---------------|
| k3sapp | Traditional Dockerfile apps | 6 | ~2,800 |
| k3sfn | Serverless functions | 5 | ~2,500 |
| k3scompose | Docker Compose projects | 5 | ~2,000 |
| k3sgateway | API Gateway routes | 4 | ~1,000 |

### Current Problems

1. **Code Duplication**: ~60% of generator code is duplicated across libraries
   - `generate_deployment()` exists in 3 libraries
   - `generate_service()` exists in 3 libraries
   - `generate_network_policy()` exists in 3 libraries
   - `generate_external_secret()` exists in 3 libraries

2. **Inconsistent Interfaces**: Different function signatures for same concepts
   - `generate_all_manifests(app, env, config)` vs `generate_all_manifests(config, env)`

3. **Procedural Style**: Functions instead of classes, no inheritance
   - Hard to extend without modifying existing code
   - No polymorphism for different app types

4. **Scattered Environment Logic**: Environment checks spread throughout code
   - `if env == Environment.LOCAL:` repeated dozens of times

5. **No Plugin System**: Adding new app types requires modifying core code

### Shared Concepts (Candidates for Abstraction)

| Concept | k3sapp | k3sfn | k3scompose | k3sgateway |
|---------|--------|-------|------------|------------|
| Environment enum | ✓ | ✓ | ✓ | ✓ |
| SecretRef | ✓ | ✓ | ✓ | - |
| SecurityConfig | ✓ | ✓ | ✓ | - |
| NetworkPolicy | ✓ | ✓ | ✓ | - |
| ServiceAccount | ✓ | ✓ | ✓ | - |
| ExternalSecret | ✓ | ✓ | ✓ | - |
| Ingress (HAProxy) | ✓ | ✓ | - | ✓ |
| Ingress (Traefik) | ✓ | ✓ | - | ✓ |
| KEDA HTTPScaledObject | ✓ | ✓ | - | - |
| Deployment | ✓ | ✓ | ✓ | - |
| Service | ✓ | ✓ | ✓ | ✓ |

---

## 3. Target Architecture

### High-Level Design

```
k3sgen/
├── core/                    # Core abstractions and protocols
│   ├── __init__.py
│   ├── types.py             # Shared enums, base dataclasses
│   ├── protocols.py         # Protocol definitions (interfaces)
│   ├── registry.py          # Plugin registry for app types
│   └── context.py           # Generation context (env, config)
│
├── config/                  # Configuration loading and validation
│   ├── __init__.py
│   ├── loader.py            # YAML loading with validation
│   ├── schema.py            # JSON Schema definitions
│   └── models.py            # Pydantic/dataclass models
│
├── manifests/               # Manifest generator classes
│   ├── __init__.py
│   ├── base.py              # Abstract ManifestGenerator
│   ├── deployment.py        # DeploymentGenerator
│   ├── service.py           # ServiceGenerator
│   ├── ingress/
│   │   ├── __init__.py
│   │   ├── base.py          # Abstract IngressGenerator
│   │   ├── haproxy.py       # HAProxyIngressGenerator
│   │   └── traefik.py       # TraefikIngressGenerator
│   ├── scaling/
│   │   ├── __init__.py
│   │   ├── base.py          # Abstract ScalingGenerator
│   │   ├── hpa.py           # HPAGenerator
│   │   ├── keda_http.py     # KEDAHttpGenerator
│   │   ├── keda_queue.py    # KEDAQueueGenerator
│   │   └── keda_cron.py     # KEDACronGenerator
│   ├── security/
│   │   ├── __init__.py
│   │   ├── network_policy.py
│   │   ├── service_account.py
│   │   └── external_secret.py
│   └── storage/
│       ├── __init__.py
│       ├── pvc.py
│       └── configmap.py
│
├── environments/            # Environment strategies
│   ├── __init__.py
│   ├── base.py              # Abstract EnvironmentStrategy
│   ├── local.py             # LocalEnvironment
│   ├── dev.py               # DevEnvironment
│   └── gcp.py               # GCPEnvironment
│
├── apps/                    # App type implementations
│   ├── __init__.py
│   ├── base.py              # Abstract AppGenerator
│   ├── traditional.py       # TraditionalAppGenerator (k3sapp)
│   ├── serverless.py        # ServerlessAppGenerator (k3sfn)
│   ├── compose.py           # ComposeAppGenerator (k3scompose)
│   └── gateway.py           # GatewayGenerator (k3sgateway)
│
├── cli/                     # CLI implementation
│   ├── __init__.py
│   ├── main.py              # Click/Typer app
│   └── commands/
│       ├── generate.py
│       ├── validate.py
│       └── init.py
│
├── utils/                   # Utility functions
│   ├── __init__.py
│   ├── naming.py            # K8s naming conventions
│   ├── yaml.py              # YAML serialization
│   └── substitution.py      # ${VAR} substitution
│
└── __init__.py              # Public API exports
```

### Dependency Graph

```
                    ┌─────────────┐
                    │    CLI      │
                    └──────┬──────┘
                           │
                    ┌──────▼──────┐
                    │   apps/     │
                    │ (generators)│
                    └──────┬──────┘
                           │
         ┌─────────────────┼─────────────────┐
         │                 │                 │
   ┌─────▼─────┐    ┌──────▼──────┐   ┌──────▼──────┐
   │environments│   │  manifests/ │   │   config/   │
   │ (strategy) │   │ (generators)│   │  (models)   │
   └─────┬─────┘    └──────┬──────┘   └──────┬──────┘
         │                 │                 │
         └─────────────────┼─────────────────┘
                           │
                    ┌──────▼──────┐
                    │    core/    │
                    │ (protocols) │
                    └─────────────┘
```

---

## 4. Core Design Patterns

### 4.1 Protocol Pattern (Structural Typing)

Use Python protocols for interface definitions:

```python
# core/protocols.py
from typing import Protocol, Any
from collections.abc import Sequence

type Manifest = dict[str, Any]
type ManifestList = Sequence[Manifest]

class Generatable(Protocol):
    """Protocol for anything that can generate K8s manifests."""

    def generate(self, context: "GenerationContext") -> ManifestList:
        """Generate Kubernetes manifests."""
        ...

class Configurable(Protocol):
    """Protocol for types that can be configured from dict."""

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Self":
        """Create instance from dictionary."""
        ...

class Validatable(Protocol):
    """Protocol for types that can validate themselves."""

    def validate(self) -> list[str]:
        """Return list of validation errors (empty if valid)."""
        ...
```

### 4.2 Strategy Pattern (Environment Handling)

```python
# environments/base.py
from abc import ABC, abstractmethod

class EnvironmentStrategy(ABC):
    """Abstract strategy for environment-specific behavior."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Environment name (local, dev, gcp)."""
        ...

    @property
    @abstractmethod
    def ingress_type(self) -> str:
        """Ingress controller type (traefik, haproxy)."""
        ...

    @property
    @abstractmethod
    def supports_external_secrets(self) -> bool:
        """Whether to generate ExternalSecret resources."""
        ...

    @abstractmethod
    def get_registry_url(self, app_name: str) -> str:
        """Get container registry URL for app."""
        ...

    @abstractmethod
    def get_image_pull_secrets(self) -> list[str]:
        """Get image pull secret names."""
        ...
```

### 4.3 Factory Pattern (App Type Registration)

```python
# core/registry.py
from typing import TypeVar, Callable

T = TypeVar("T", bound="AppGenerator")

class AppTypeRegistry:
    """Registry for app type generators."""

    _generators: dict[str, type["AppGenerator"]] = {}

    @classmethod
    def register(cls, app_type: str) -> Callable[[type[T]], type[T]]:
        """Decorator to register an app generator."""
        def decorator(generator_cls: type[T]) -> type[T]:
            cls._generators[app_type] = generator_cls
            return generator_cls
        return decorator

    @classmethod
    def get(cls, app_type: str) -> type["AppGenerator"]:
        """Get generator class for app type."""
        if app_type not in cls._generators:
            raise ValueError(f"Unknown app type: {app_type}")
        return cls._generators[app_type]

    @classmethod
    def create(cls, app_type: str, config: "AppConfig") -> "AppGenerator":
        """Create generator instance for app type."""
        return cls.get(app_type)(config)
```

### 4.4 Builder Pattern (Manifest Construction)

```python
# manifests/base.py
from abc import ABC, abstractmethod
from typing import Any

class ManifestBuilder:
    """Fluent builder for Kubernetes manifests."""

    def __init__(self, api_version: str, kind: str):
        self._manifest: dict[str, Any] = {
            "apiVersion": api_version,
            "kind": kind,
            "metadata": {},
            "spec": {},
        }

    def name(self, name: str) -> "ManifestBuilder":
        self._manifest["metadata"]["name"] = name
        return self

    def namespace(self, namespace: str) -> "ManifestBuilder":
        self._manifest["metadata"]["namespace"] = namespace
        return self

    def labels(self, labels: dict[str, str]) -> "ManifestBuilder":
        self._manifest["metadata"]["labels"] = labels
        return self

    def annotations(self, annotations: dict[str, str]) -> "ManifestBuilder":
        self._manifest["metadata"]["annotations"] = annotations
        return self

    def spec(self, **kwargs: Any) -> "ManifestBuilder":
        self._manifest["spec"].update(kwargs)
        return self

    def build(self) -> dict[str, Any]:
        return self._manifest
```

### 4.5 Composite Pattern (Manifest Aggregation)

```python
# apps/base.py
from abc import ABC, abstractmethod

class AppGenerator(ABC):
    """Base class for all app type generators."""

    def __init__(self, config: "AppConfig"):
        self.config = config
        self._generators: list["ManifestGenerator"] = []

    def add_generator(self, generator: "ManifestGenerator") -> None:
        """Add a manifest generator to the pipeline."""
        self._generators.append(generator)

    @abstractmethod
    def configure_generators(self, context: "GenerationContext") -> None:
        """Configure which generators to use based on config."""
        ...

    def generate(self, context: "GenerationContext") -> ManifestList:
        """Generate all manifests for this app."""
        self.configure_generators(context)
        manifests = []
        for generator in self._generators:
            if generator.should_generate(context):
                manifests.extend(generator.generate(context))
        return manifests
```

---

## 5. Module Structure

### 5.1 Core Module (`core/`)

#### `core/types.py` - Shared Type Definitions

```python
"""Core type definitions shared across all modules."""
from dataclasses import dataclass, field
from enum import StrEnum, auto
from typing import Any

# Type aliases (Python 3.12 syntax)
type Manifest = dict[str, Any]
type ManifestList = list[Manifest]


class Environment(StrEnum):
    """Deployment environment."""
    LOCAL = auto()
    DEV = auto()
    GCP = auto()


class ScalingType(StrEnum):
    """Autoscaling strategy."""
    NONE = auto()
    HPA = auto()
    KEDA_HTTP = auto()
    KEDA_QUEUE = auto()
    KEDA_CRON = auto()


class Visibility(StrEnum):
    """Network visibility level."""
    PUBLIC = auto()
    INTERNAL = auto()
    PRIVATE = auto()
    RESTRICTED = auto()


class IngressType(StrEnum):
    """Ingress controller type."""
    TRAEFIK = auto()
    HAPROXY = auto()


class SecretProvider(StrEnum):
    """External secret provider."""
    GCP = auto()
    AWS = auto()
    VAULT = auto()
    AZURE = auto()


class VolumeType(StrEnum):
    """Volume type."""
    EMPTY_DIR = auto()
    PVC = auto()
    SECRET = auto()
    CONFIGMAP = auto()


class ProbeType(StrEnum):
    """Health probe type."""
    HTTP = auto()
    TCP = auto()
    EXEC = auto()


@dataclass(frozen=True, slots=True)
class SecretRef:
    """Reference to an external secret."""
    secret: str
    provider: SecretProvider = SecretProvider.GCP
    version: str = "latest"
    key: str | None = None


@dataclass(frozen=True, slots=True)
class ResourceRequirements:
    """Container resource requirements."""
    memory: str = "256Mi"
    cpu: str = "100m"
    memory_limit: str | None = None
    cpu_limit: str | None = None
    ephemeral_storage: str | None = None

    def __post_init__(self) -> None:
        if self.memory_limit is None:
            object.__setattr__(self, "memory_limit", self.memory)


@dataclass(frozen=True, slots=True)
class PortSpec:
    """Container port specification."""
    name: str = "http"
    container_port: int = 8080
    service_port: int = 80
    protocol: str = "TCP"


@dataclass(frozen=True, slots=True)
class ProbeSpec:
    """Health check probe specification."""
    type: ProbeType = ProbeType.HTTP
    path: str = "/health"
    port: int = 8080
    initial_delay: int = 0
    period: int = 10
    timeout: int = 1
    success_threshold: int = 1
    failure_threshold: int = 3
    command: tuple[str, ...] | None = None


@dataclass(frozen=True, slots=True)
class EgressRule:
    """Network policy egress rule."""
    namespace: str | None = None
    pod_labels: dict[str, str] = field(default_factory=dict)
    cidr: str | None = None
```

#### `core/context.py` - Generation Context

```python
"""Generation context for manifest generation."""
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..environments.base import EnvironmentStrategy
    from ..config.models import AppsYamlConfig

@dataclass
class GenerationContext:
    """Context passed to all generators."""

    environment: "EnvironmentStrategy"
    config: "AppsYamlConfig"
    app_name: str
    namespace: str
    image: str

    @property
    def env_name(self) -> str:
        """Environment name (local, dev, gcp)."""
        return self.environment.name

    @property
    def ingress_type(self) -> str:
        """Ingress controller type."""
        return self.environment.ingress_type

    @property
    def supports_external_secrets(self) -> bool:
        """Whether external secrets are supported."""
        return self.environment.supports_external_secrets

    def to_k8s_name(self, name: str) -> str:
        """Convert name to valid K8s resource name."""
        return name.replace("_", "-").lower()
```

### 5.2 Manifests Module (`manifests/`)

#### `manifests/base.py` - Abstract Manifest Generator

```python
"""Base class for all manifest generators."""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..core.types import Manifest, ManifestList

if TYPE_CHECKING:
    from ..core.context import GenerationContext


class ManifestGenerator(ABC):
    """Abstract base class for manifest generators."""

    @property
    @abstractmethod
    def kind(self) -> str:
        """Kubernetes resource kind."""
        ...

    @property
    def api_version(self) -> str:
        """Kubernetes API version."""
        return "v1"

    @abstractmethod
    def should_generate(self, context: "GenerationContext") -> bool:
        """Check if this generator should produce output."""
        ...

    @abstractmethod
    def generate(self, context: "GenerationContext") -> ManifestList:
        """Generate Kubernetes manifests."""
        ...

    def _base_metadata(
        self,
        context: "GenerationContext",
        name: str | None = None,
    ) -> dict:
        """Generate standard metadata block."""
        k8s_name = context.to_k8s_name(name or context.app_name)
        return {
            "name": k8s_name,
            "namespace": context.namespace,
            "labels": {
                "app": k8s_name,
                "k3sgen.io/app": context.app_name,
                "k3sgen.io/env": context.env_name,
            },
        }

    def _base_selector(self, context: "GenerationContext") -> dict:
        """Generate standard selector."""
        return {
            "matchLabels": {
                "app": context.to_k8s_name(context.app_name),
            },
        }
```

#### `manifests/deployment.py` - Deployment Generator

```python
"""Deployment manifest generator."""
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .base import ManifestGenerator
from ..core.types import (
    Manifest,
    ManifestList,
    PortSpec,
    ProbeSpec,
    ProbeType,
    ResourceRequirements,
)

if TYPE_CHECKING:
    from ..core.context import GenerationContext


@dataclass
class DeploymentConfig:
    """Configuration for Deployment generation."""
    replicas: int = 1
    ports: list[PortSpec] | None = None
    resources: ResourceRequirements | None = None
    command: list[str] | None = None
    args: list[str] | None = None
    env: dict[str, str] | None = None
    env_from: list[dict[str, Any]] | None = None
    probes: dict[str, ProbeSpec] | None = None
    volumes: list[dict[str, Any]] | None = None
    volume_mounts: list[dict[str, Any]] | None = None
    service_account: str | None = None
    security_context: dict[str, Any] | None = None
    pod_security_context: dict[str, Any] | None = None
    image_pull_secrets: list[str] | None = None


class DeploymentGenerator(ManifestGenerator):
    """Generator for Kubernetes Deployment manifests."""

    def __init__(self, config: DeploymentConfig):
        self.config = config

    @property
    def kind(self) -> str:
        return "Deployment"

    @property
    def api_version(self) -> str:
        return "apps/v1"

    def should_generate(self, context: "GenerationContext") -> bool:
        return True  # Always generate Deployment

    def generate(self, context: "GenerationContext") -> ManifestList:
        container = self._build_container(context)
        pod_spec = self._build_pod_spec(context, container)

        deployment: Manifest = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": self._base_metadata(context),
            "spec": {
                "replicas": self.config.replicas,
                "selector": self._base_selector(context),
                "template": {
                    "metadata": {
                        "labels": {
                            "app": context.to_k8s_name(context.app_name),
                            "k3sgen.io/app": context.app_name,
                        },
                    },
                    "spec": pod_spec,
                },
            },
        }

        return [deployment]

    def _build_container(self, context: "GenerationContext") -> dict[str, Any]:
        """Build container spec."""
        container: dict[str, Any] = {
            "name": context.to_k8s_name(context.app_name),
            "image": context.image,
        }

        # Ports
        if self.config.ports:
            container["ports"] = [
                {
                    "containerPort": p.container_port,
                    "protocol": p.protocol,
                    "name": p.name,
                }
                for p in self.config.ports
            ]

        # Resources
        if self.config.resources:
            container["resources"] = self._build_resources(self.config.resources)

        # Command/Args
        if self.config.command:
            container["command"] = self.config.command
        if self.config.args:
            container["args"] = self.config.args

        # Environment
        if self.config.env:
            container["env"] = [
                {"name": k, "value": v}
                for k, v in self.config.env.items()
            ]
        if self.config.env_from:
            container["envFrom"] = self.config.env_from

        # Probes
        if self.config.probes:
            for probe_type, probe_spec in self.config.probes.items():
                container[f"{probe_type}Probe"] = self._build_probe(probe_spec)

        # Volume mounts
        if self.config.volume_mounts:
            container["volumeMounts"] = self.config.volume_mounts

        # Security context
        if self.config.security_context:
            container["securityContext"] = self.config.security_context

        return container

    def _build_pod_spec(
        self,
        context: "GenerationContext",
        container: dict[str, Any],
    ) -> dict[str, Any]:
        """Build pod spec."""
        pod_spec: dict[str, Any] = {
            "containers": [container],
        }

        if self.config.service_account:
            pod_spec["serviceAccountName"] = self.config.service_account

        if self.config.volumes:
            pod_spec["volumes"] = self.config.volumes

        if self.config.pod_security_context:
            pod_spec["securityContext"] = self.config.pod_security_context

        if self.config.image_pull_secrets:
            pod_spec["imagePullSecrets"] = [
                {"name": s} for s in self.config.image_pull_secrets
            ]

        return pod_spec

    def _build_resources(self, resources: ResourceRequirements) -> dict[str, Any]:
        """Build resources block."""
        result: dict[str, Any] = {
            "requests": {
                "memory": resources.memory,
                "cpu": resources.cpu,
            },
            "limits": {
                "memory": resources.memory_limit,
            },
        }

        if resources.cpu_limit:
            result["limits"]["cpu"] = resources.cpu_limit

        if resources.ephemeral_storage:
            result["requests"]["ephemeral-storage"] = resources.ephemeral_storage
            result["limits"]["ephemeral-storage"] = resources.ephemeral_storage

        return result

    def _build_probe(self, probe: ProbeSpec) -> dict[str, Any]:
        """Build probe configuration."""
        result: dict[str, Any] = {
            "periodSeconds": probe.period,
            "timeoutSeconds": probe.timeout,
            "successThreshold": probe.success_threshold,
            "failureThreshold": probe.failure_threshold,
        }

        if probe.initial_delay > 0:
            result["initialDelaySeconds"] = probe.initial_delay

        match probe.type:
            case ProbeType.HTTP:
                result["httpGet"] = {"path": probe.path, "port": probe.port}
            case ProbeType.TCP:
                result["tcpSocket"] = {"port": probe.port}
            case ProbeType.EXEC if probe.command:
                result["exec"] = {"command": list(probe.command)}

        return result
```

---

## 6. Abstract Base Classes

### 6.1 Complete Class Hierarchy

```
ManifestGenerator (ABC)
├── DeploymentGenerator
├── ServiceGenerator
├── IngressGenerator (ABC)
│   ├── HAProxyIngressGenerator
│   └── TraefikIngressGenerator
├── ScalingGenerator (ABC)
│   ├── HPAGenerator
│   ├── KEDAHttpGenerator
│   ├── KEDAQueueGenerator
│   └── KEDACronGenerator
├── SecurityGenerator (ABC)
│   ├── NetworkPolicyGenerator
│   ├── ServiceAccountGenerator
│   └── ExternalSecretGenerator
└── StorageGenerator (ABC)
    ├── PVCGenerator
    ├── ConfigMapGenerator
    └── SecretGenerator

EnvironmentStrategy (ABC)
├── LocalEnvironment
├── DevEnvironment
└── GCPEnvironment

AppGenerator (ABC)
├── TraditionalAppGenerator
├── ServerlessAppGenerator
├── ComposeAppGenerator
└── GatewayGenerator
```

### 6.2 Abstract Ingress Generator

```python
# manifests/ingress/base.py
"""Abstract base for ingress generators."""
from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..base import ManifestGenerator
from ...core.types import ManifestList

if TYPE_CHECKING:
    from ...core.context import GenerationContext


@dataclass
class IngressConfig:
    """Configuration for ingress generation."""
    path: str = "/"
    path_type: str = "Prefix"
    strip_prefix: bool = False
    hosts: list[str] | None = None
    tls_enabled: bool = False
    tls_secret: str | None = None
    timeouts: dict[str, str] | None = None
    annotations: dict[str, str] | None = None


class IngressGenerator(ManifestGenerator):
    """Abstract base for ingress generators."""

    def __init__(self, config: IngressConfig):
        self.config = config

    @property
    def kind(self) -> str:
        return "Ingress"

    @property
    def api_version(self) -> str:
        return "networking.k8s.io/v1"

    @abstractmethod
    def get_backend_service(self, context: "GenerationContext") -> dict:
        """Get backend service configuration."""
        ...

    @abstractmethod
    def get_annotations(self, context: "GenerationContext") -> dict[str, str]:
        """Get ingress annotations."""
        ...

    def should_generate(self, context: "GenerationContext") -> bool:
        # Check if ingress is enabled for this app
        return True

    def generate(self, context: "GenerationContext") -> ManifestList:
        manifests = []

        # Generate any required supporting resources
        manifests.extend(self._generate_supporting_resources(context))

        # Generate main ingress
        manifests.append(self._generate_ingress(context))

        return manifests

    def _generate_ingress(self, context: "GenerationContext") -> dict:
        """Generate the main ingress resource."""
        ingress = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {
                **self._base_metadata(context),
                "annotations": self.get_annotations(context),
            },
            "spec": {
                "ingressClassName": self._get_ingress_class(),
                "rules": self._build_rules(context),
            },
        }

        if self.config.tls_enabled:
            ingress["spec"]["tls"] = self._build_tls()

        return ingress

    @abstractmethod
    def _get_ingress_class(self) -> str:
        """Get the ingress class name."""
        ...

    @abstractmethod
    def _generate_supporting_resources(
        self,
        context: "GenerationContext",
    ) -> ManifestList:
        """Generate any supporting resources (middlewares, services, etc.)."""
        ...

    def _build_rules(self, context: "GenerationContext") -> list[dict]:
        """Build ingress rules."""
        rule: dict = {
            "http": {
                "paths": [
                    {
                        "path": self.config.path,
                        "pathType": self.config.path_type,
                        "backend": self.get_backend_service(context),
                    }
                ],
            },
        }

        if self.config.hosts:
            return [{"host": host, **rule} for host in self.config.hosts]
        return [rule]

    def _build_tls(self) -> list[dict]:
        """Build TLS configuration."""
        tls: dict = {}
        if self.config.tls_secret:
            tls["secretName"] = self.config.tls_secret
        if self.config.hosts:
            tls["hosts"] = self.config.hosts
        return [tls] if tls else []
```

### 6.3 Abstract Scaling Generator

```python
# manifests/scaling/base.py
"""Abstract base for scaling generators."""
from abc import abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..base import ManifestGenerator
from ...core.types import ManifestList, ScalingType

if TYPE_CHECKING:
    from ...core.context import GenerationContext


@dataclass
class ScalingConfig:
    """Configuration for scaling generation."""
    type: ScalingType = ScalingType.KEDA_HTTP
    min_replicas: int = 0
    max_replicas: int = 10
    cooldown_period: int = 300

    # HPA specific
    target_cpu_percent: int | None = None
    target_memory_percent: int | None = None

    # KEDA HTTP specific
    target_pending_requests: int = 100

    # KEDA Queue specific
    queue_name: str | None = None
    queue_length: int = 5

    # KEDA Cron specific
    cron_schedules: list["CronSchedule"] | None = None


@dataclass
class CronSchedule:
    """Cron schedule for time-based scaling."""
    timezone: str = "UTC"
    start: str = "0 8 * * *"
    end: str = "0 18 * * *"
    replicas: int = 5


class ScalingGenerator(ManifestGenerator):
    """Abstract base for scaling generators."""

    def __init__(self, config: ScalingConfig):
        self.config = config

    @property
    @abstractmethod
    def scaling_type(self) -> ScalingType:
        """The scaling type this generator handles."""
        ...

    def should_generate(self, context: "GenerationContext") -> bool:
        return self.config.type == self.scaling_type

    @abstractmethod
    def generate(self, context: "GenerationContext") -> ManifestList:
        """Generate scaling resources."""
        ...

    def _scale_target_ref(self, context: "GenerationContext") -> dict:
        """Generate scaleTargetRef for scaling resources."""
        return {
            "apiVersion": "apps/v1",
            "kind": "Deployment",
            "name": context.to_k8s_name(context.app_name),
        }
```

---

## 7. Manifest Generators

### 7.1 Service Generator

```python
# manifests/service.py
"""Service manifest generator."""
from dataclasses import dataclass
from typing import TYPE_CHECKING

from .base import ManifestGenerator
from ..core.types import Manifest, ManifestList, PortSpec

if TYPE_CHECKING:
    from ..core.context import GenerationContext


@dataclass
class ServiceConfig:
    """Configuration for Service generation."""
    ports: list[PortSpec] | None = None
    type: str = "ClusterIP"
    external_name: str | None = None  # For ExternalName services


class ServiceGenerator(ManifestGenerator):
    """Generator for Kubernetes Service manifests."""

    def __init__(self, config: ServiceConfig):
        self.config = config

    @property
    def kind(self) -> str:
        return "Service"

    def should_generate(self, context: "GenerationContext") -> bool:
        return True

    def generate(self, context: "GenerationContext") -> ManifestList:
        service: Manifest = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": self._base_metadata(context),
            "spec": self._build_spec(context),
        }
        return [service]

    def _build_spec(self, context: "GenerationContext") -> dict:
        """Build service spec."""
        if self.config.type == "ExternalName" and self.config.external_name:
            return {
                "type": "ExternalName",
                "externalName": self.config.external_name,
            }

        ports = self.config.ports or [PortSpec()]

        return {
            "type": self.config.type,
            "selector": {
                "app": context.to_k8s_name(context.app_name),
            },
            "ports": [
                {
                    "name": p.name,
                    "port": p.service_port,
                    "targetPort": p.container_port,
                    "protocol": p.protocol,
                }
                for p in ports
            ],
        }
```

### 7.2 HAProxy Ingress Generator

```python
# manifests/ingress/haproxy.py
"""HAProxy ingress generator."""
from typing import TYPE_CHECKING

from .base import IngressConfig, IngressGenerator
from ...core.types import ManifestList

if TYPE_CHECKING:
    from ...core.context import GenerationContext


class HAProxyIngressGenerator(IngressGenerator):
    """Generator for HAProxy Ingress manifests."""

    def __init__(
        self,
        config: IngressConfig,
        keda_routing_host: str | None = None,
    ):
        super().__init__(config)
        self.keda_routing_host = keda_routing_host

    def _get_ingress_class(self) -> str:
        return "haproxy"

    def get_backend_service(self, context: "GenerationContext") -> dict:
        """Use KEDA route service for scale-to-zero support."""
        name = context.to_k8s_name(context.app_name)
        return {
            "service": {
                "name": f"keda-route-{name}",
                "port": {"number": 8080},
            },
        }

    def get_annotations(self, context: "GenerationContext") -> dict[str, str]:
        """Build HAProxy-specific annotations."""
        annotations = {
            "haproxy-ingress.github.io/timeout-connect":
                self.config.timeouts.get("connect", "10s") if self.config.timeouts else "10s",
            "haproxy-ingress.github.io/timeout-server":
                self.config.timeouts.get("server", "180s") if self.config.timeouts else "180s",
            "haproxy-ingress.github.io/timeout-client":
                self.config.timeouts.get("client", "180s") if self.config.timeouts else "180s",
            "haproxy-ingress.github.io/retry-on":
                "conn-failure,empty-response,response-timeout",
            "haproxy-ingress.github.io/retries": "3",
        }

        # Host header rewrite for KEDA routing
        if self.keda_routing_host:
            config_backend = f"http-request set-header Host {self.keda_routing_host}\n"

            if self.config.strip_prefix and self.config.path != "/":
                path = self.config.path.rstrip("/")
                config_backend += (
                    f"http-request set-path %[path,regsub(^{path}/,/),"
                    f"regsub(^{path}$,/)]\n"
                )

            annotations["haproxy-ingress.github.io/config-backend"] = config_backend

        # Merge user annotations
        if self.config.annotations:
            annotations.update(self.config.annotations)

        return annotations

    def _generate_supporting_resources(
        self,
        context: "GenerationContext",
    ) -> ManifestList:
        """Generate KEDA route ExternalName service."""
        name = context.to_k8s_name(context.app_name)

        return [{
            "apiVersion": "v1",
            "kind": "Service",
            "metadata": {
                "name": f"keda-route-{name}",
                "namespace": context.namespace,
                "labels": {
                    "app": name,
                    "k3sgen.io/app": context.app_name,
                    "k3sgen.io/component": "keda-route",
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
        }]
```

### 7.3 Traefik Ingress Generator

```python
# manifests/ingress/traefik.py
"""Traefik IngressRoute generator."""
from typing import TYPE_CHECKING

from .base import IngressConfig, IngressGenerator
from ...core.types import ManifestList

if TYPE_CHECKING:
    from ...core.context import GenerationContext


class TraefikIngressGenerator(IngressGenerator):
    """Generator for Traefik IngressRoute manifests."""

    def __init__(
        self,
        config: IngressConfig,
        keda_routing_host: str | None = None,
    ):
        super().__init__(config)
        self.keda_routing_host = keda_routing_host

    @property
    def kind(self) -> str:
        return "IngressRoute"

    @property
    def api_version(self) -> str:
        return "traefik.io/v1alpha1"

    def _get_ingress_class(self) -> str:
        return "traefik"

    def get_backend_service(self, context: "GenerationContext") -> dict:
        """Get Traefik service configuration."""
        return {
            "name": "keda-interceptor-proxy",
            "port": 8080,
        }

    def get_annotations(self, context: "GenerationContext") -> dict[str, str]:
        """Traefik uses middlewares, not annotations."""
        return self.config.annotations or {}

    def _generate_supporting_resources(
        self,
        context: "GenerationContext",
    ) -> ManifestList:
        """Generate Traefik Middleware for host rewrite."""
        if not self.keda_routing_host:
            return []

        name = context.to_k8s_name(context.app_name)

        return [{
            "apiVersion": "traefik.io/v1alpha1",
            "kind": "Middleware",
            "metadata": {
                "name": f"{name}-host-rewrite",
                "namespace": context.namespace,
                "labels": {
                    "app": name,
                    "k3sgen.io/app": context.app_name,
                },
            },
            "spec": {
                "headers": {
                    "customRequestHeaders": {
                        "Host": self.keda_routing_host,
                    },
                },
            },
        }]

    def generate(self, context: "GenerationContext") -> ManifestList:
        """Generate Traefik IngressRoute instead of standard Ingress."""
        manifests = self._generate_supporting_resources(context)

        name = context.to_k8s_name(context.app_name)

        # Build match rule
        match = f"PathPrefix(`{self.config.path}`)"
        if self.config.hosts:
            host_match = " || ".join(f"Host(`{h}`)" for h in self.config.hosts)
            match = f"({host_match}) && {match}"

        middlewares = []
        if self.keda_routing_host:
            middlewares.append({
                "name": f"{name}-host-rewrite",
                "namespace": context.namespace,
            })

        route: dict = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": self._base_metadata(context, f"{name}-routes"),
            "spec": {
                "entryPoints": ["web", "websecure"],
                "routes": [
                    {
                        "match": match,
                        "kind": "Rule",
                        "services": [self.get_backend_service(context)],
                        "middlewares": middlewares,
                    }
                ],
            },
        }

        manifests.append(route)
        return manifests
```

### 7.4 KEDA HTTP Scaling Generator

```python
# manifests/scaling/keda_http.py
"""KEDA HTTP scaling generator."""
from typing import TYPE_CHECKING

from .base import ScalingConfig, ScalingGenerator
from ...core.types import ManifestList, ScalingType

if TYPE_CHECKING:
    from ...core.context import GenerationContext


class KEDAHttpGenerator(ScalingGenerator):
    """Generator for KEDA HTTPScaledObject manifests."""

    def __init__(
        self,
        config: ScalingConfig,
        service_port: int = 80,
        path_prefix: str = "/",
    ):
        super().__init__(config)
        self.service_port = service_port
        self.path_prefix = path_prefix

    @property
    def kind(self) -> str:
        return "HTTPScaledObject"

    @property
    def api_version(self) -> str:
        return "http.keda.sh/v1alpha1"

    @property
    def scaling_type(self) -> ScalingType:
        return ScalingType.KEDA_HTTP

    def generate(self, context: "GenerationContext") -> ManifestList:
        name = context.to_k8s_name(context.app_name)
        routing_host = f"{name}.{context.namespace}"

        httpso = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {
                **self._base_metadata(context, f"{name}-http"),
            },
            "spec": {
                "hosts": [routing_host],
                "pathPrefixes": [self.path_prefix],
                "scaleTargetRef": {
                    **self._scale_target_ref(context),
                    "service": name,
                    "port": self.service_port,
                },
                "replicas": {
                    "min": self.config.min_replicas,
                    "max": self.config.max_replicas,
                },
                "scalingMetric": {
                    "requestRate": {
                        "granularity": "1s",
                        "targetValue": self.config.target_pending_requests,
                        "window": "1m",
                    },
                },
                "scaledownPeriod": self.config.cooldown_period,
            },
        }

        return [httpso]
```

### 7.5 Network Policy Generator

```python
# manifests/security/network_policy.py
"""Network policy generator."""
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..base import ManifestGenerator
from ...core.types import EgressRule, ManifestList, Visibility

if TYPE_CHECKING:
    from ...core.context import GenerationContext


@dataclass
class NetworkPolicyConfig:
    """Configuration for NetworkPolicy generation."""
    enabled: bool = True
    visibility: Visibility = Visibility.PRIVATE
    allow_from: list[EgressRule] = field(default_factory=list)
    allow_to: list[EgressRule] = field(default_factory=list)
    primary_port: int = 8080


class NetworkPolicyGenerator(ManifestGenerator):
    """Generator for Kubernetes NetworkPolicy manifests."""

    def __init__(self, config: NetworkPolicyConfig):
        self.config = config

    @property
    def kind(self) -> str:
        return "NetworkPolicy"

    @property
    def api_version(self) -> str:
        return "networking.k8s.io/v1"

    def should_generate(self, context: "GenerationContext") -> bool:
        return self.config.enabled

    def generate(self, context: "GenerationContext") -> ManifestList:
        name = context.to_k8s_name(context.app_name)

        ingress_rules = self._build_ingress_rules(context)
        egress_rules = self._build_egress_rules(context)

        policy_types = ["Ingress"]
        if egress_rules:
            policy_types.append("Egress")

        policy = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": {
                **self._base_metadata(context, f"{name}-policy"),
                "labels": {
                    **self._base_metadata(context)["labels"],
                    "k3sgen.io/visibility": self.config.visibility.value,
                },
            },
            "spec": {
                "podSelector": {
                    "matchLabels": {"app": name},
                },
                "policyTypes": policy_types,
                "ingress": ingress_rules,
            },
        }

        if egress_rules:
            policy["spec"]["egress"] = egress_rules

        return [policy]

    def _build_ingress_rules(self, context: "GenerationContext") -> list[dict]:
        """Build ingress rules based on visibility."""
        rules = []
        port_spec = {"protocol": "TCP", "port": self.config.primary_port}

        # Always allow KEDA for scaling
        rules.append({
            "from": [{
                "namespaceSelector": {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": "keda",
                    },
                },
            }],
            "ports": [port_spec],
        })

        match self.config.visibility:
            case Visibility.PUBLIC | Visibility.INTERNAL:
                # Allow from any namespace
                rules.append({
                    "from": [{"namespaceSelector": {}}],
                    "ports": [port_spec],
                })
            case Visibility.PRIVATE:
                # Allow from same namespace only
                rules.append({
                    "from": [{"podSelector": {}}],
                    "ports": [port_spec],
                })
            case Visibility.RESTRICTED:
                # Only custom allow_from rules
                pass

        # Custom allow_from rules
        for rule in self.config.allow_from:
            rules.append(self._build_from_rule(rule, port_spec))

        return rules

    def _build_egress_rules(self, context: "GenerationContext") -> list[dict]:
        """Build egress rules."""
        if not self.config.allow_to:
            return []

        rules = []

        # Always allow DNS
        rules.append({
            "to": [{
                "namespaceSelector": {},
                "podSelector": {
                    "matchLabels": {"k8s-app": "kube-dns"},
                },
            }],
            "ports": [
                {"protocol": "UDP", "port": 53},
                {"protocol": "TCP", "port": 53},
            ],
        })

        # Custom allow_to rules
        for rule in self.config.allow_to:
            rules.append(self._build_to_rule(rule))

        return rules

    def _build_from_rule(self, rule: EgressRule, port_spec: dict) -> dict:
        """Build ingress from-rule."""
        from_spec: dict = {}

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

        return {"from": [from_spec], "ports": [port_spec]}

    def _build_to_rule(self, rule: EgressRule) -> dict:
        """Build egress to-rule."""
        to_spec: dict = {}

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

        return {"to": [to_spec]}
```

### 7.6 External Secret Generator

```python
# manifests/security/external_secret.py
"""External secret generator."""
from dataclasses import dataclass
from typing import TYPE_CHECKING

from ..base import ManifestGenerator
from ...core.types import ManifestList, SecretRef

if TYPE_CHECKING:
    from ...core.context import GenerationContext


@dataclass
class ExternalSecretConfig:
    """Configuration for ExternalSecret generation."""
    secrets: dict[str, SecretRef]  # env_var_name -> SecretRef
    refresh_interval: str = "1h"
    secret_store_name: str = "gcp-secret-manager"
    secret_store_kind: str = "ClusterSecretStore"


class ExternalSecretGenerator(ManifestGenerator):
    """Generator for External Secrets Operator manifests."""

    def __init__(self, config: ExternalSecretConfig):
        self.config = config

    @property
    def kind(self) -> str:
        return "ExternalSecret"

    @property
    def api_version(self) -> str:
        return "external-secrets.io/v1beta1"

    def should_generate(self, context: "GenerationContext") -> bool:
        # Only generate for environments that support external secrets
        return (
            context.supports_external_secrets
            and bool(self.config.secrets)
        )

    def generate(self, context: "GenerationContext") -> ManifestList:
        name = context.to_k8s_name(context.app_name)

        data = []
        for env_key, ref in self.config.secrets.items():
            entry: dict = {
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

        external_secret = {
            "apiVersion": self.api_version,
            "kind": self.kind,
            "metadata": self._base_metadata(context, f"{name}-secrets"),
            "spec": {
                "refreshInterval": self.config.refresh_interval,
                "secretStoreRef": {
                    "kind": self.config.secret_store_kind,
                    "name": self.config.secret_store_name,
                },
                "target": {
                    "name": f"{name}-secrets",
                    "creationPolicy": "Owner",
                },
                "data": data,
            },
        }

        return [external_secret]
```

---

## 8. Environment Strategy Pattern

### 8.1 Base Environment Strategy

```python
# environments/base.py
"""Abstract base for environment strategies."""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..core.types import IngressType

if TYPE_CHECKING:
    from ..config.models import AppsYamlConfig


class EnvironmentStrategy(ABC):
    """Abstract strategy for environment-specific behavior."""

    def __init__(self, config: "AppsYamlConfig"):
        self.config = config

    @property
    @abstractmethod
    def name(self) -> str:
        """Environment name."""
        ...

    @property
    @abstractmethod
    def ingress_type(self) -> IngressType:
        """Ingress controller type."""
        ...

    @property
    @abstractmethod
    def supports_external_secrets(self) -> bool:
        """Whether External Secrets Operator is available."""
        ...

    @property
    @abstractmethod
    def supports_workload_identity(self) -> bool:
        """Whether Workload Identity is available."""
        ...

    @abstractmethod
    def get_registry_url(self, app_name: str, app_path: str) -> str:
        """Get container image URL."""
        ...

    @abstractmethod
    def get_image_pull_secrets(self) -> list[str]:
        """Get image pull secret names."""
        ...

    @property
    def domain(self) -> str:
        """Get environment domain."""
        env_config = self.config.environments.get(self.name)
        return env_config.domain if env_config else "localhost"

    @property
    def tls_enabled(self) -> bool:
        """Check if TLS is enabled."""
        env_config = self.config.environments.get(self.name)
        return env_config.tls if env_config else False

    @property
    def tls_secret(self) -> str | None:
        """Get TLS secret name."""
        env_config = self.config.environments.get(self.name)
        return env_config.tls_secret if env_config else None
```

### 8.2 Local Environment

```python
# environments/local.py
"""Local development environment strategy."""
from .base import EnvironmentStrategy
from ..core.types import IngressType


class LocalEnvironment(EnvironmentStrategy):
    """Strategy for local k3d development."""

    @property
    def name(self) -> str:
        return "local"

    @property
    def ingress_type(self) -> IngressType:
        return IngressType.TRAEFIK

    @property
    def supports_external_secrets(self) -> bool:
        return False  # Use .env files locally

    @property
    def supports_workload_identity(self) -> bool:
        return False

    def get_registry_url(self, app_name: str, app_path: str) -> str:
        # Local builds use simple name
        return f"{app_name}:latest"

    def get_image_pull_secrets(self) -> list[str]:
        return []  # No secrets needed locally
```

### 8.3 GCP Environment

```python
# environments/gcp.py
"""GCP production environment strategy."""
from .base import EnvironmentStrategy
from ..core.types import IngressType


class GCPEnvironment(EnvironmentStrategy):
    """Strategy for GCP/GKE production deployment."""

    @property
    def name(self) -> str:
        return "gcp"

    @property
    def ingress_type(self) -> IngressType:
        return IngressType.HAPROXY

    @property
    def supports_external_secrets(self) -> bool:
        return True

    @property
    def supports_workload_identity(self) -> bool:
        return True

    def get_registry_url(self, app_name: str, app_path: str) -> str:
        registry = self.config.defaults.registry.get("gcp", "")
        if not registry:
            raise ValueError("GCP registry not configured in defaults.registry.gcp")
        return f"{registry}/{app_name}:latest"

    def get_image_pull_secrets(self) -> list[str]:
        return ["artifact-registry"]
```

### 8.4 Environment Factory

```python
# environments/__init__.py
"""Environment strategy factory."""
from typing import TYPE_CHECKING

from .base import EnvironmentStrategy
from .local import LocalEnvironment
from .dev import DevEnvironment
from .gcp import GCPEnvironment
from ..core.types import Environment

if TYPE_CHECKING:
    from ..config.models import AppsYamlConfig

_STRATEGIES: dict[Environment, type[EnvironmentStrategy]] = {
    Environment.LOCAL: LocalEnvironment,
    Environment.DEV: DevEnvironment,
    Environment.GCP: GCPEnvironment,
}


def get_environment_strategy(
    env: Environment,
    config: "AppsYamlConfig",
) -> EnvironmentStrategy:
    """Get environment strategy for the given environment."""
    strategy_class = _STRATEGIES.get(env)
    if not strategy_class:
        raise ValueError(f"Unknown environment: {env}")
    return strategy_class(config)


def register_environment(
    env: Environment,
    strategy_class: type[EnvironmentStrategy],
) -> None:
    """Register a custom environment strategy."""
    _STRATEGIES[env] = strategy_class
```

---

## 9. App Type Implementations

### 9.1 Base App Generator

```python
# apps/base.py
"""Abstract base for app generators."""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from ..core.types import ManifestList
from ..manifests.base import ManifestGenerator

if TYPE_CHECKING:
    from ..core.context import GenerationContext
    from ..config.models import AppConfig


class AppGenerator(ABC):
    """Abstract base class for all app type generators."""

    def __init__(self, config: "AppConfig"):
        self.config = config
        self._generators: list[ManifestGenerator] = []

    @property
    @abstractmethod
    def app_type(self) -> str:
        """App type identifier (traditional, serverless, compose, gateway)."""
        ...

    def add_generator(self, generator: ManifestGenerator) -> None:
        """Add a manifest generator to the pipeline."""
        self._generators.append(generator)

    def clear_generators(self) -> None:
        """Clear all generators."""
        self._generators.clear()

    @abstractmethod
    def configure_generators(self, context: "GenerationContext") -> None:
        """Configure which generators to use based on config and context."""
        ...

    def generate(self, context: "GenerationContext") -> ManifestList:
        """Generate all manifests for this app."""
        self.clear_generators()
        self.configure_generators(context)

        manifests: ManifestList = []
        for generator in self._generators:
            if generator.should_generate(context):
                manifests.extend(generator.generate(context))

        return manifests

    @abstractmethod
    def get_image(self, context: "GenerationContext") -> str:
        """Get container image URL for this app."""
        ...
```

### 9.2 Traditional App Generator

```python
# apps/traditional.py
"""Traditional Dockerfile app generator."""
from typing import TYPE_CHECKING

from .base import AppGenerator
from ..core.registry import AppTypeRegistry
from ..core.types import IngressType, ScalingType
from ..manifests.deployment import DeploymentConfig, DeploymentGenerator
from ..manifests.service import ServiceConfig, ServiceGenerator
from ..manifests.ingress.haproxy import HAProxyIngressGenerator
from ..manifests.ingress.traefik import TraefikIngressGenerator
from ..manifests.ingress.base import IngressConfig
from ..manifests.scaling.hpa import HPAGenerator
from ..manifests.scaling.keda_http import KEDAHttpGenerator
from ..manifests.scaling.keda_queue import KEDAQueueGenerator
from ..manifests.scaling.keda_cron import KEDACronGenerator
from ..manifests.scaling.base import ScalingConfig
from ..manifests.security.network_policy import NetworkPolicyConfig, NetworkPolicyGenerator
from ..manifests.security.service_account import ServiceAccountConfig, ServiceAccountGenerator
from ..manifests.security.external_secret import ExternalSecretConfig, ExternalSecretGenerator

if TYPE_CHECKING:
    from ..core.context import GenerationContext
    from ..config.models import TraditionalAppConfig


@AppTypeRegistry.register("traditional")
class TraditionalAppGenerator(AppGenerator):
    """Generator for traditional Dockerfile-based apps."""

    config: "TraditionalAppConfig"

    @property
    def app_type(self) -> str:
        return "traditional"

    def configure_generators(self, context: "GenerationContext") -> None:
        """Configure all generators based on app config."""

        # 1. ServiceAccount (if configured)
        if self.config.security.create_service_account:
            self._add_service_account_generator(context)

        # 2. ExternalSecret (if secrets configured)
        if self.config.get_secret_refs():
            self._add_external_secret_generator(context)

        # 3. Deployment (always)
        self._add_deployment_generator(context)

        # 4. Service (always)
        self._add_service_generator(context)

        # 5. Scaling
        self._add_scaling_generator(context)

        # 6. Ingress (if enabled)
        if self.config.ingress.enabled:
            self._add_ingress_generator(context)

        # 7. NetworkPolicy (if enabled)
        if self.config.security.network_policy.enabled:
            self._add_network_policy_generator(context)

    def _add_deployment_generator(self, context: "GenerationContext") -> None:
        """Add deployment generator."""
        resources = self.config.get_effective_resources(context.env_name)
        scaling = self.config.get_effective_scaling(context.env_name)

        config = DeploymentConfig(
            replicas=scaling.min_replicas if scaling.type != ScalingType.NONE else 1,
            ports=self.config.container.ports,
            resources=resources,
            command=self.config.container.command,
            args=self.config.container.args,
            env=self.config.get_literal_env_vars(context.env_name),
            env_from=self._build_env_from(context),
            probes=self._build_probes(),
            volumes=self._build_volumes(),
            volume_mounts=self._build_volume_mounts(),
            service_account=self.config.security.service_account,
            security_context=self._build_container_security_context(),
            pod_security_context=self._build_pod_security_context(),
            image_pull_secrets=context.environment.get_image_pull_secrets(),
        )

        self.add_generator(DeploymentGenerator(config))

    def _add_service_generator(self, context: "GenerationContext") -> None:
        """Add service generator."""
        config = ServiceConfig(
            ports=self.config.container.ports or [self.config.get_primary_port()],
        )
        self.add_generator(ServiceGenerator(config))

    def _add_scaling_generator(self, context: "GenerationContext") -> None:
        """Add appropriate scaling generator."""
        scaling = self.config.get_effective_scaling(context.env_name)

        config = ScalingConfig(
            type=scaling.type,
            min_replicas=scaling.min_instances,
            max_replicas=scaling.max_instances,
            cooldown_period=scaling.cooldown_period,
            target_cpu_percent=scaling.target_cpu_percent,
            target_memory_percent=scaling.target_memory_percent,
            target_pending_requests=scaling.target_pending_requests,
            queue_name=scaling.queue_name,
            queue_length=scaling.queue_length,
            cron_schedules=scaling.cron_schedules,
        )

        match scaling.type:
            case ScalingType.HPA:
                self.add_generator(HPAGenerator(config))
            case ScalingType.KEDA_HTTP:
                port = self.config.get_primary_port()
                path = self.config.ingress.path if self.config.ingress.enabled else "/"
                self.add_generator(KEDAHttpGenerator(config, port.service_port, path))
            case ScalingType.KEDA_QUEUE:
                self.add_generator(KEDAQueueGenerator(config))
            case ScalingType.KEDA_CRON:
                self.add_generator(KEDACronGenerator(config))

    def _add_ingress_generator(self, context: "GenerationContext") -> None:
        """Add ingress generator based on environment."""
        name = context.to_k8s_name(context.app_name)
        routing_host = f"{name}.{context.namespace}"

        config = IngressConfig(
            path=self.config.ingress.path,
            path_type=self.config.ingress.path_type,
            strip_prefix=self.config.ingress.strip_prefix,
            hosts=self.config.ingress.hosts,
            tls_enabled=self.config.ingress.tls.enabled if self.config.ingress.tls else False,
            tls_secret=self.config.ingress.tls.secret if self.config.ingress.tls else None,
            timeouts=self._build_timeouts(),
            annotations=self.config.ingress.annotations,
        )

        match context.ingress_type:
            case IngressType.HAPROXY:
                self.add_generator(HAProxyIngressGenerator(config, routing_host))
            case IngressType.TRAEFIK:
                self.add_generator(TraefikIngressGenerator(config, routing_host))

    def _add_network_policy_generator(self, context: "GenerationContext") -> None:
        """Add network policy generator."""
        config = NetworkPolicyConfig(
            enabled=self.config.security.network_policy.enabled,
            visibility=self.config.security.visibility,
            allow_from=self.config.security.network_policy.allow_from,
            allow_to=self.config.security.network_policy.allow_to,
            primary_port=self.config.get_primary_port().container_port,
        )
        self.add_generator(NetworkPolicyGenerator(config))

    def _add_service_account_generator(self, context: "GenerationContext") -> None:
        """Add service account generator."""
        config = ServiceAccountConfig(
            name=self.config.security.service_account,
            annotations=self.config.security.service_account_annotations,
        )
        self.add_generator(ServiceAccountGenerator(config))

    def _add_external_secret_generator(self, context: "GenerationContext") -> None:
        """Add external secret generator."""
        config = ExternalSecretConfig(
            secrets=self.config.get_secret_refs(),
        )
        self.add_generator(ExternalSecretGenerator(config))

    def get_image(self, context: "GenerationContext") -> str:
        """Get container image URL."""
        return context.environment.get_registry_url(
            self.config.name,
            self.config.path,
        )

    # Helper methods for building config objects...
    def _build_env_from(self, context: "GenerationContext") -> list[dict]:
        """Build envFrom list."""
        env_from = []

        for ref in self.config.env_from:
            if ref.type == "secret":
                item = {"secretRef": {"name": ref.name}}
                if ref.optional:
                    item["secretRef"]["optional"] = True
            else:
                item = {"configMapRef": {"name": ref.name}}
                if ref.optional:
                    item["configMapRef"]["optional"] = True
            if ref.prefix:
                item["prefix"] = ref.prefix
            env_from.append(item)

        # Add ESO-synced secrets
        if context.supports_external_secrets and self.config.get_secret_refs():
            name = context.to_k8s_name(context.app_name)
            env_from.append({"secretRef": {"name": f"{name}-secrets"}})

        return env_from

    def _build_probes(self) -> dict:
        """Build probes configuration."""
        probes = {}
        if self.config.probes.startup:
            probes["startup"] = self.config.probes.startup
        if self.config.probes.readiness:
            probes["readiness"] = self.config.probes.readiness
        if self.config.probes.liveness:
            probes["liveness"] = self.config.probes.liveness
        return probes

    def _build_volumes(self) -> list[dict]:
        """Build volumes list."""
        # Implementation...
        return []

    def _build_volume_mounts(self) -> list[dict]:
        """Build volume mounts list."""
        # Implementation...
        return []

    def _build_timeouts(self) -> dict[str, str]:
        """Build timeouts configuration."""
        if not self.config.ingress.timeouts:
            return {}
        t = self.config.ingress.timeouts
        return {
            "connect": t.connect,
            "server": t.server,
            "client": t.client,
            "queue": t.queue,
        }

    def _build_container_security_context(self) -> dict | None:
        """Build container security context."""
        # Implementation...
        return None

    def _build_pod_security_context(self) -> dict | None:
        """Build pod security context."""
        # Implementation...
        return None
```

### 9.3 Serverless App Generator

```python
# apps/serverless.py
"""Serverless function app generator."""
from typing import TYPE_CHECKING

from .base import AppGenerator
from ..core.registry import AppTypeRegistry

if TYPE_CHECKING:
    from ..core.context import GenerationContext
    from ..config.models import ServerlessAppConfig


@AppTypeRegistry.register("serverless")
class ServerlessAppGenerator(AppGenerator):
    """Generator for serverless function apps."""

    config: "ServerlessAppConfig"

    @property
    def app_type(self) -> str:
        return "serverless"

    def configure_generators(self, context: "GenerationContext") -> None:
        """Configure generators for serverless functions."""
        # Similar pattern to TraditionalAppGenerator but with:
        # - Per-function deployments
        # - Schedule triggers -> CronJob
        # - Queue triggers -> KEDA Queue ScaledObject
        # - HTTP triggers -> HTTPScaledObject
        pass

    def get_image(self, context: "GenerationContext") -> str:
        """Get container image URL."""
        return context.environment.get_registry_url(
            self.config.name,
            self.config.path,
        )
```

---

## 10. Plugin System

### 10.1 Plugin Interface

```python
# core/plugins.py
"""Plugin system for extending k3sgen."""
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .registry import AppTypeRegistry
    from ..environments import register_environment


class K3sGenPlugin(ABC):
    """Base class for k3sgen plugins."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Plugin name."""
        ...

    @property
    @abstractmethod
    def version(self) -> str:
        """Plugin version."""
        ...

    def register_app_types(self, registry: "AppTypeRegistry") -> None:
        """Register custom app types."""
        pass

    def register_environments(self) -> None:
        """Register custom environments."""
        pass

    def register_manifest_generators(self) -> None:
        """Register custom manifest generators."""
        pass


def load_plugins() -> list[K3sGenPlugin]:
    """Load all installed plugins via entry points."""
    from importlib.metadata import entry_points

    plugins = []
    eps = entry_points(group="k3sgen.plugins")

    for ep in eps:
        plugin_class = ep.load()
        plugins.append(plugin_class())

    return plugins
```

### 10.2 Plugin Registration in pyproject.toml

```toml
[project.entry-points."k3sgen.plugins"]
my_plugin = "my_k3sgen_plugin:MyPlugin"
```

---

## 11. Configuration Schema

### 11.1 Pydantic Models (Alternative to Dataclasses)

```python
# config/models.py
"""Configuration models using Pydantic for validation."""
from pydantic import BaseModel, Field, field_validator
from typing import Any

from ..core.types import (
    Environment,
    IngressType,
    ScalingType,
    SecretProvider,
    Visibility,
)


class ResourcesModel(BaseModel):
    """Resource requirements model."""
    memory: str = "256Mi"
    cpu: str = "100m"
    memory_limit: str | None = None
    cpu_limit: str | None = None
    ephemeral_storage: str | None = None

    @field_validator("memory_limit", mode="before")
    @classmethod
    def set_memory_limit(cls, v: str | None, info) -> str:
        return v or info.data.get("memory", "256Mi")


class ScalingModel(BaseModel):
    """Scaling configuration model."""
    type: ScalingType = ScalingType.KEDA_HTTP
    min_instances: int = Field(default=0, ge=0)
    max_instances: int = Field(default=10, ge=1)
    target_pending_requests: int = Field(default=100, ge=1)
    queue_name: str | None = None
    queue_length: int = Field(default=5, ge=1)
    target_cpu_percent: int | None = Field(default=None, ge=1, le=100)
    target_memory_percent: int | None = Field(default=None, ge=1, le=100)
    cooldown_period: int = Field(default=300, ge=0)
    cron_schedules: list["CronScheduleModel"] = Field(default_factory=list)


class CronScheduleModel(BaseModel):
    """Cron schedule model."""
    timezone: str = "UTC"
    start: str
    end: str
    replicas: int = Field(ge=1)


class SecretRefModel(BaseModel):
    """Secret reference model."""
    secret: str
    provider: SecretProvider = SecretProvider.GCP
    version: str = "latest"
    key: str | None = None


class IngressModel(BaseModel):
    """Ingress configuration model."""
    enabled: bool = False
    path: str = "/"
    path_type: str = "Prefix"
    strip_prefix: bool = False
    hosts: list[str] = Field(default_factory=list)
    tls: "TlsModel | None" = None
    timeouts: "TimeoutsModel | None" = None
    annotations: dict[str, str] = Field(default_factory=dict)


class TlsModel(BaseModel):
    """TLS configuration model."""
    enabled: bool = False
    secret: str | None = None
    hosts: list[str] = Field(default_factory=list)


class TimeoutsModel(BaseModel):
    """Timeout configuration model."""
    connect: str = "10s"
    server: str = "180s"
    client: str = "180s"
    queue: str = "180s"


class NetworkPolicyModel(BaseModel):
    """Network policy configuration model."""
    enabled: bool = True
    allow_from: list["NetworkPolicyRuleModel"] = Field(default_factory=list)
    allow_to: list["NetworkPolicyRuleModel"] = Field(default_factory=list)


class NetworkPolicyRuleModel(BaseModel):
    """Network policy rule model."""
    namespace: str | None = None
    pod_labels: dict[str, str] = Field(default_factory=dict)
    cidr: str | None = None


class SecurityModel(BaseModel):
    """Security configuration model."""
    visibility: Visibility = Visibility.PRIVATE
    network_policy: NetworkPolicyModel = Field(default_factory=NetworkPolicyModel)
    service_account: str | None = None
    create_service_account: bool = False
    service_account_annotations: dict[str, str] = Field(default_factory=dict)


class TraditionalAppConfig(BaseModel):
    """Traditional app configuration."""
    name: str
    path: str
    namespace: str = "apps"
    enabled: bool = True

    resources: ResourcesModel = Field(default_factory=ResourcesModel)
    scaling: ScalingModel = Field(default_factory=ScalingModel)
    ingress: IngressModel = Field(default_factory=IngressModel)
    security: SecurityModel = Field(default_factory=SecurityModel)

    environment: dict[str, str | SecretRefModel] = Field(default_factory=dict)

    # Environment overrides
    local: "EnvOverrideModel | None" = None
    dev: "EnvOverrideModel | None" = None
    gcp: "EnvOverrideModel | None" = None

    def get_effective_resources(self, env: str) -> ResourcesModel:
        """Get resources with environment override."""
        override = getattr(self, env, None)
        if override and override.resources:
            return override.resources
        return self.resources

    def get_effective_scaling(self, env: str) -> ScalingModel:
        """Get scaling with environment override."""
        override = getattr(self, env, None)
        if override and override.scaling:
            return override.scaling
        return self.scaling


class EnvOverrideModel(BaseModel):
    """Environment-specific overrides."""
    enabled: bool | None = None
    replicas: int | None = None
    resources: ResourcesModel | None = None
    scaling: ScalingModel | None = None
    environment: dict[str, str] = Field(default_factory=dict)


class AppsYamlConfig(BaseModel):
    """Root apps.yaml configuration."""
    version: str = "2"
    defaults: "DefaultsModel" = Field(default_factory=lambda: DefaultsModel())
    environments: dict[str, "EnvironmentConfigModel"] = Field(default_factory=dict)
    apps: list[TraditionalAppConfig] = Field(default_factory=list)


class DefaultsModel(BaseModel):
    """Global defaults."""
    namespace: str = "apps"
    registry: dict[str, str] = Field(default_factory=dict)
    ingress: dict[str, str] = Field(default_factory=dict)


class EnvironmentConfigModel(BaseModel):
    """Per-environment configuration."""
    domain: str = "localhost"
    tls: bool = False
    tls_secret: str | None = None
```

---

## 12. CLI Architecture

### 12.1 Main CLI with Typer

```python
# cli/main.py
"""Main CLI entry point using Typer."""
import typer
from pathlib import Path
from typing import Annotated

from ..core.types import Environment
from ..config.loader import load_config
from ..environments import get_environment_strategy
from .commands.generate import generate_command
from .commands.validate import validate_command

app = typer.Typer(
    name="k3sgen",
    help="Kubernetes manifest generator for k3s platform",
    no_args_is_help=True,
)


@app.command()
def generate(
    config_file: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to apps.yaml"),
    ] = Path("apps.yaml"),
    env: Annotated[
        Environment,
        typer.Option("--env", "-e", help="Target environment"),
    ] = Environment.LOCAL,
    output: Annotated[
        Path,
        typer.Option("--output", "-o", help="Output directory"),
    ] = Path("generated"),
    app_name: Annotated[
        str | None,
        typer.Option("--app", "-a", help="Generate for specific app only"),
    ] = None,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Print manifests without writing"),
    ] = False,
) -> None:
    """Generate Kubernetes manifests from apps.yaml."""
    generate_command(
        config_file=config_file,
        env=env,
        output=output,
        app_name=app_name,
        dry_run=dry_run,
    )


@app.command()
def validate(
    config_file: Annotated[
        Path,
        typer.Option("--config", "-c", help="Path to apps.yaml"),
    ] = Path("apps.yaml"),
) -> None:
    """Validate apps.yaml configuration."""
    validate_command(config_file)


@app.command()
def init(
    output: Annotated[
        Path,
        typer.Argument(help="Output directory"),
    ] = Path("."),
) -> None:
    """Initialize a new k3sgen project."""
    # Create apps.yaml template, directory structure, etc.
    pass


def main() -> None:
    """CLI entry point."""
    app()


if __name__ == "__main__":
    main()
```

### 12.2 Generate Command

```python
# cli/commands/generate.py
"""Generate command implementation."""
from pathlib import Path
import yaml

from ...core.types import Environment, ManifestList
from ...core.context import GenerationContext
from ...core.registry import AppTypeRegistry
from ...config.loader import load_config
from ...environments import get_environment_strategy


def generate_command(
    config_file: Path,
    env: Environment,
    output: Path,
    app_name: str | None = None,
    dry_run: bool = False,
) -> None:
    """Generate Kubernetes manifests."""
    # Load configuration
    config = load_config(config_file)

    # Get environment strategy
    environment = get_environment_strategy(env, config)

    # Filter apps if specific app requested
    apps = config.apps
    if app_name:
        apps = [a for a in apps if a.name == app_name]
        if not apps:
            raise ValueError(f"App not found: {app_name}")

    # Generate manifests for each app
    for app_config in apps:
        if not app_config.enabled:
            continue

        # Create generator for app type
        generator = AppTypeRegistry.create("traditional", app_config)

        # Create generation context
        context = GenerationContext(
            environment=environment,
            config=config,
            app_name=app_config.name,
            namespace=app_config.namespace,
            image=generator.get_image(context),
        )

        # Generate manifests
        manifests = generator.generate(context)

        if dry_run:
            _print_manifests(manifests)
        else:
            _write_manifests(manifests, output, app_config.name)


def _print_manifests(manifests: ManifestList) -> None:
    """Print manifests to stdout."""
    for manifest in manifests:
        print("---")
        print(yaml.safe_dump(manifest, default_flow_style=False))


def _write_manifests(manifests: ManifestList, output: Path, app_name: str) -> None:
    """Write manifests to files."""
    output.mkdir(parents=True, exist_ok=True)

    output_file = output / f"{app_name}.yaml"
    with open(output_file, "w") as f:
        for i, manifest in enumerate(manifests):
            if i > 0:
                f.write("---\n")
            yaml.safe_dump(manifest, f, default_flow_style=False)

    print(f"Generated: {output_file}")
```

---

## 13. Testing Strategy

### 13.1 Test Structure

```
tests/
├── conftest.py              # Shared fixtures
├── unit/
│   ├── test_types.py
│   ├── test_context.py
│   ├── manifests/
│   │   ├── test_deployment.py
│   │   ├── test_service.py
│   │   ├── test_ingress.py
│   │   ├── test_scaling.py
│   │   └── test_security.py
│   ├── environments/
│   │   ├── test_local.py
│   │   ├── test_dev.py
│   │   └── test_gcp.py
│   └── apps/
│       ├── test_traditional.py
│       ├── test_serverless.py
│       └── test_compose.py
├── integration/
│   ├── test_full_generation.py
│   └── test_kubectl_apply.py
└── fixtures/
    ├── apps.yaml
    └── expected/
        ├── local/
        ├── dev/
        └── gcp/
```

### 13.2 Test Fixtures

```python
# tests/conftest.py
"""Shared test fixtures."""
import pytest
from pathlib import Path

from k3sgen.core.types import Environment
from k3sgen.core.context import GenerationContext
from k3sgen.config.models import AppsYamlConfig, TraditionalAppConfig
from k3sgen.environments.local import LocalEnvironment


@pytest.fixture
def sample_config() -> AppsYamlConfig:
    """Sample apps.yaml configuration."""
    return AppsYamlConfig(
        version="2",
        defaults=DefaultsModel(
            namespace="apps",
            registry={"local": "", "gcp": "us-docker.pkg.dev/project/repo"},
        ),
        apps=[
            TraditionalAppConfig(
                name="test-app",
                path="apps/test-app",
                namespace="apps",
            ),
        ],
    )


@pytest.fixture
def local_context(sample_config: AppsYamlConfig) -> GenerationContext:
    """Generation context for local environment."""
    env = LocalEnvironment(sample_config)
    return GenerationContext(
        environment=env,
        config=sample_config,
        app_name="test-app",
        namespace="apps",
        image="test-app:latest",
    )


@pytest.fixture
def gcp_context(sample_config: AppsYamlConfig) -> GenerationContext:
    """Generation context for GCP environment."""
    from k3sgen.environments.gcp import GCPEnvironment
    env = GCPEnvironment(sample_config)
    return GenerationContext(
        environment=env,
        config=sample_config,
        app_name="test-app",
        namespace="apps",
        image="us-docker.pkg.dev/project/repo/test-app:latest",
    )
```

### 13.3 Unit Test Example

```python
# tests/unit/manifests/test_deployment.py
"""Tests for deployment generator."""
import pytest

from k3sgen.manifests.deployment import DeploymentConfig, DeploymentGenerator
from k3sgen.core.types import PortSpec, ResourceRequirements


class TestDeploymentGenerator:
    """Tests for DeploymentGenerator."""

    def test_generates_basic_deployment(self, local_context):
        """Test basic deployment generation."""
        config = DeploymentConfig(replicas=2)
        generator = DeploymentGenerator(config)

        manifests = generator.generate(local_context)

        assert len(manifests) == 1
        deployment = manifests[0]
        assert deployment["apiVersion"] == "apps/v1"
        assert deployment["kind"] == "Deployment"
        assert deployment["spec"]["replicas"] == 2

    def test_includes_resources(self, local_context):
        """Test resource requirements in deployment."""
        config = DeploymentConfig(
            resources=ResourceRequirements(
                memory="512Mi",
                cpu="250m",
                memory_limit="1Gi",
            ),
        )
        generator = DeploymentGenerator(config)

        manifests = generator.generate(local_context)

        container = manifests[0]["spec"]["template"]["spec"]["containers"][0]
        assert container["resources"]["requests"]["memory"] == "512Mi"
        assert container["resources"]["limits"]["memory"] == "1Gi"

    def test_includes_ports(self, local_context):
        """Test port configuration in deployment."""
        config = DeploymentConfig(
            ports=[
                PortSpec(name="http", container_port=8080),
                PortSpec(name="metrics", container_port=9090),
            ],
        )
        generator = DeploymentGenerator(config)

        manifests = generator.generate(local_context)

        container = manifests[0]["spec"]["template"]["spec"]["containers"][0]
        assert len(container["ports"]) == 2
        assert container["ports"][0]["containerPort"] == 8080
        assert container["ports"][1]["containerPort"] == 9090
```

### 13.4 Integration Test Example

```python
# tests/integration/test_full_generation.py
"""Integration tests for full manifest generation."""
import pytest
import subprocess
import tempfile
from pathlib import Path

from k3sgen.core.types import Environment
from k3sgen.config.loader import load_config
from k3sgen.apps.traditional import TraditionalAppGenerator
from k3sgen.environments import get_environment_strategy


class TestFullGeneration:
    """Integration tests for complete manifest generation."""

    @pytest.fixture
    def apps_yaml(self, tmp_path: Path) -> Path:
        """Create temporary apps.yaml."""
        content = """
version: "2"
defaults:
  namespace: apps
  registry:
    local: ""
    gcp: "us-docker.pkg.dev/project/repo"
apps:
  - name: test-api
    path: apps/test-api
    ingress:
      enabled: true
      path: /api
    scaling:
      type: keda-http
      min_instances: 0
      max_instances: 10
"""
        config_file = tmp_path / "apps.yaml"
        config_file.write_text(content)
        return config_file

    def test_generates_valid_manifests(self, apps_yaml: Path):
        """Test that generated manifests are valid K8s YAML."""
        config = load_config(apps_yaml)
        env = get_environment_strategy(Environment.LOCAL, config)

        app_config = config.apps[0]
        generator = TraditionalAppGenerator(app_config)

        # Create context
        context = GenerationContext(
            environment=env,
            config=config,
            app_name=app_config.name,
            namespace=app_config.namespace,
            image=generator.get_image(context),
        )

        manifests = generator.generate(context)

        # Verify expected resources
        kinds = [m["kind"] for m in manifests]
        assert "Deployment" in kinds
        assert "Service" in kinds
        assert "HTTPScaledObject" in kinds

    def test_kubectl_dry_run(self, apps_yaml: Path, tmp_path: Path):
        """Test manifests with kubectl --dry-run."""
        # Generate manifests
        config = load_config(apps_yaml)
        env = get_environment_strategy(Environment.LOCAL, config)

        app_config = config.apps[0]
        generator = TraditionalAppGenerator(app_config)

        context = GenerationContext(
            environment=env,
            config=config,
            app_name=app_config.name,
            namespace=app_config.namespace,
            image="test:latest",
        )

        manifests = generator.generate(context)

        # Write to temp file
        import yaml
        manifest_file = tmp_path / "manifests.yaml"
        with open(manifest_file, "w") as f:
            for m in manifests:
                f.write("---\n")
                yaml.safe_dump(m, f)

        # Run kubectl dry-run
        result = subprocess.run(
            ["kubectl", "apply", "--dry-run=client", "-f", str(manifest_file)],
            capture_output=True,
            text=True,
        )

        assert result.returncode == 0, f"kubectl failed: {result.stderr}"
```

---

## 14. Migration Strategy

### 14.1 Phase 1: Core Library (Week 1-2)

1. Create new `k3sgen` package structure
2. Implement core types and protocols
3. Implement base manifest generators
4. Implement environment strategies
5. Write comprehensive unit tests

### 14.2 Phase 2: Traditional Apps (Week 3)

1. Port k3sapp functionality to TraditionalAppGenerator
2. Ensure 100% feature parity
3. Compare generated manifests with original
4. Write integration tests

### 14.3 Phase 3: Serverless Functions (Week 4)

1. Port k3sfn functionality to ServerlessAppGenerator
2. Handle function decorators and metadata
3. Ensure trigger types work correctly

### 14.4 Phase 4: Compose and Gateway (Week 5)

1. Port k3scompose to ComposeAppGenerator
2. Port k3sgateway to GatewayGenerator
3. Handle docker-compose parsing

### 14.5 Phase 5: CLI and Integration (Week 6)

1. Implement new CLI with Typer
2. Add validation commands
3. Update documentation
4. Deprecate old libraries

### 14.6 Backward Compatibility

During migration, maintain the old libraries as thin wrappers:

```python
# libs/k3sapp/k3sapp/__init__.py (deprecated wrapper)
"""DEPRECATED: Use k3sgen instead."""
import warnings
from k3sgen.apps.traditional import TraditionalAppGenerator
from k3sgen.core.types import *

warnings.warn(
    "k3sapp is deprecated, use k3sgen instead",
    DeprecationWarning,
    stacklevel=2,
)

# Re-export for backward compatibility
__all__ = ["TraditionalAppGenerator", ...]
```

---

## 15. Implementation Checklist

### Phase 1: Foundation

#### Step 1.1: Project Setup
- [ ] Create `libs/k3sgen/` directory structure
- [ ] Create `pyproject.toml` with Python 3.12 requirement
- [ ] Set up pytest, mypy, ruff configuration
- [ ] Create `__init__.py` files for all packages

#### Step 1.2: Core Types
- [ ] **File:** `core/types.py`
  - [ ] Implement `Environment` enum
  - [ ] Implement `ScalingType` enum
  - [ ] Implement `Visibility` enum
  - [ ] Implement `IngressType` enum
  - [ ] Implement `SecretProvider` enum
  - [ ] Implement `VolumeType` enum
  - [ ] Implement `ProbeType` enum
  - [ ] Implement `SecretRef` dataclass
  - [ ] Implement `ResourceRequirements` dataclass
  - [ ] Implement `PortSpec` dataclass
  - [ ] Implement `ProbeSpec` dataclass
  - [ ] Implement `EgressRule` dataclass
  - [ ] Add type aliases (`Manifest`, `ManifestList`)

#### Step 1.3: Core Protocols
- [ ] **File:** `core/protocols.py`
  - [ ] Define `Generatable` protocol
  - [ ] Define `Configurable` protocol
  - [ ] Define `Validatable` protocol

#### Step 1.4: Core Context
- [ ] **File:** `core/context.py`
  - [ ] Implement `GenerationContext` dataclass
  - [ ] Add `to_k8s_name()` helper method

#### Step 1.5: Core Registry
- [ ] **File:** `core/registry.py`
  - [ ] Implement `AppTypeRegistry` class
  - [ ] Add `register()` decorator
  - [ ] Add `get()` method
  - [ ] Add `create()` method

### Phase 2: Manifest Generators

#### Step 2.1: Base Generator
- [ ] **File:** `manifests/base.py`
  - [ ] Implement `ManifestGenerator` ABC
  - [ ] Add `_base_metadata()` method
  - [ ] Add `_base_selector()` method

#### Step 2.2: Deployment Generator
- [ ] **File:** `manifests/deployment.py`
  - [ ] Implement `DeploymentConfig` dataclass
  - [ ] Implement `DeploymentGenerator` class
  - [ ] Add `_build_container()` method
  - [ ] Add `_build_pod_spec()` method
  - [ ] Add `_build_resources()` method
  - [ ] Add `_build_probe()` method

#### Step 2.3: Service Generator
- [ ] **File:** `manifests/service.py`
  - [ ] Implement `ServiceConfig` dataclass
  - [ ] Implement `ServiceGenerator` class
  - [ ] Support ClusterIP and ExternalName types

#### Step 2.4: Ingress Generators
- [ ] **File:** `manifests/ingress/base.py`
  - [ ] Implement `IngressConfig` dataclass
  - [ ] Implement `IngressGenerator` ABC
- [ ] **File:** `manifests/ingress/haproxy.py`
  - [ ] Implement `HAProxyIngressGenerator`
  - [ ] Add KEDA route service generation
  - [ ] Add HAProxy-specific annotations
- [ ] **File:** `manifests/ingress/traefik.py`
  - [ ] Implement `TraefikIngressGenerator`
  - [ ] Add Middleware generation
  - [ ] Add IngressRoute generation

#### Step 2.5: Scaling Generators
- [ ] **File:** `manifests/scaling/base.py`
  - [ ] Implement `ScalingConfig` dataclass
  - [ ] Implement `CronSchedule` dataclass
  - [ ] Implement `ScalingGenerator` ABC
- [ ] **File:** `manifests/scaling/hpa.py`
  - [ ] Implement `HPAGenerator`
- [ ] **File:** `manifests/scaling/keda_http.py`
  - [ ] Implement `KEDAHttpGenerator`
- [ ] **File:** `manifests/scaling/keda_queue.py`
  - [ ] Implement `KEDAQueueGenerator`
  - [ ] Add TriggerAuthentication generation
- [ ] **File:** `manifests/scaling/keda_cron.py`
  - [ ] Implement `KEDACronGenerator`

#### Step 2.6: Security Generators
- [ ] **File:** `manifests/security/network_policy.py`
  - [ ] Implement `NetworkPolicyConfig` dataclass
  - [ ] Implement `NetworkPolicyGenerator`
  - [ ] Add visibility-based rules
  - [ ] Add egress rules with DNS
- [ ] **File:** `manifests/security/service_account.py`
  - [ ] Implement `ServiceAccountConfig` dataclass
  - [ ] Implement `ServiceAccountGenerator`
- [ ] **File:** `manifests/security/external_secret.py`
  - [ ] Implement `ExternalSecretConfig` dataclass
  - [ ] Implement `ExternalSecretGenerator`

#### Step 2.7: Storage Generators
- [ ] **File:** `manifests/storage/pvc.py`
  - [ ] Implement `PVCConfig` dataclass
  - [ ] Implement `PVCGenerator`
- [ ] **File:** `manifests/storage/configmap.py`
  - [ ] Implement `ConfigMapGenerator`

### Phase 3: Environment Strategies

#### Step 3.1: Base Strategy
- [ ] **File:** `environments/base.py`
  - [ ] Implement `EnvironmentStrategy` ABC
  - [ ] Add abstract properties and methods

#### Step 3.2: Environment Implementations
- [ ] **File:** `environments/local.py`
  - [ ] Implement `LocalEnvironment`
- [ ] **File:** `environments/dev.py`
  - [ ] Implement `DevEnvironment`
- [ ] **File:** `environments/gcp.py`
  - [ ] Implement `GCPEnvironment`

#### Step 3.3: Factory
- [ ] **File:** `environments/__init__.py`
  - [ ] Implement `get_environment_strategy()`
  - [ ] Implement `register_environment()`

### Phase 4: App Generators

#### Step 4.1: Base App Generator
- [ ] **File:** `apps/base.py`
  - [ ] Implement `AppGenerator` ABC
  - [ ] Add generator pipeline management

#### Step 4.2: Traditional App
- [ ] **File:** `apps/traditional.py`
  - [ ] Implement `TraditionalAppGenerator`
  - [ ] Register with `@AppTypeRegistry.register("traditional")`
  - [ ] Port all k3sapp functionality

#### Step 4.3: Serverless App
- [ ] **File:** `apps/serverless.py`
  - [ ] Implement `ServerlessAppGenerator`
  - [ ] Register with `@AppTypeRegistry.register("serverless")`
  - [ ] Port all k3sfn functionality

#### Step 4.4: Compose App
- [ ] **File:** `apps/compose.py`
  - [ ] Implement `ComposeAppGenerator`
  - [ ] Register with `@AppTypeRegistry.register("compose")`
  - [ ] Port all k3scompose functionality

#### Step 4.5: Gateway
- [ ] **File:** `apps/gateway.py`
  - [ ] Implement `GatewayGenerator`
  - [ ] Register with `@AppTypeRegistry.register("gateway")`
  - [ ] Port all k3sgateway functionality

### Phase 5: Configuration

#### Step 5.1: Models
- [ ] **File:** `config/models.py`
  - [ ] Choose Pydantic or dataclasses
  - [ ] Implement all config models
  - [ ] Add validation logic

#### Step 5.2: Loader
- [ ] **File:** `config/loader.py`
  - [ ] Implement YAML loading
  - [ ] Implement JSON Schema validation
  - [ ] Handle version migrations

#### Step 5.3: Schema
- [ ] **File:** `config/schema.py` or `schemas/apps-schema.json`
  - [ ] Update JSON Schema for new structure
  - [ ] Add validation for all fields

### Phase 6: CLI

#### Step 6.1: Main CLI
- [ ] **File:** `cli/main.py`
  - [ ] Set up Typer app
  - [ ] Add `generate` command
  - [ ] Add `validate` command
  - [ ] Add `init` command

#### Step 6.2: Commands
- [ ] **File:** `cli/commands/generate.py`
  - [ ] Implement full generation flow
  - [ ] Add dry-run support
  - [ ] Add single-app generation
- [ ] **File:** `cli/commands/validate.py`
  - [ ] Implement config validation

### Phase 7: Utilities

#### Step 7.1: Helpers
- [ ] **File:** `utils/naming.py`
  - [ ] Implement naming utilities
- [ ] **File:** `utils/yaml.py`
  - [ ] Implement YAML serialization helpers
- [ ] **File:** `utils/substitution.py`
  - [ ] Implement `${VAR}` substitution

### Phase 8: Testing

#### Step 8.1: Unit Tests
- [ ] **File:** `tests/unit/test_types.py`
- [ ] **File:** `tests/unit/test_context.py`
- [ ] **File:** `tests/unit/manifests/test_deployment.py`
- [ ] **File:** `tests/unit/manifests/test_service.py`
- [ ] **File:** `tests/unit/manifests/test_ingress.py`
- [ ] **File:** `tests/unit/manifests/test_scaling.py`
- [ ] **File:** `tests/unit/manifests/test_security.py`
- [ ] **File:** `tests/unit/environments/test_local.py`
- [ ] **File:** `tests/unit/environments/test_gcp.py`
- [ ] **File:** `tests/unit/apps/test_traditional.py`

#### Step 8.2: Integration Tests
- [ ] **File:** `tests/integration/test_full_generation.py`
- [ ] **File:** `tests/integration/test_kubectl_apply.py`

#### Step 8.3: Fixtures
- [ ] **File:** `tests/fixtures/apps.yaml`
- [ ] **Dir:** `tests/fixtures/expected/local/`
- [ ] **Dir:** `tests/fixtures/expected/gcp/`

### Phase 9: Documentation

#### Step 9.1: README
- [ ] Update `libs/k3sgen/README.md`
- [ ] Add usage examples
- [ ] Add migration guide

#### Step 9.2: API Docs
- [ ] Add docstrings to all public classes/methods
- [ ] Generate API documentation

### Phase 10: Migration

#### Step 10.1: Deprecation Wrappers
- [ ] Update `libs/k3sapp/` to use k3sgen
- [ ] Update `libs/k3sfn/` to use k3sgen
- [ ] Update `libs/k3scompose/` to use k3sgen
- [ ] Update `libs/k3sgateway/` to use k3sgen
- [ ] Add deprecation warnings

#### Step 10.2: Update Scripts
- [ ] Update `scripts/deploy-apps.sh` to use new CLI
- [ ] Update Tiltfile if needed
- [ ] Update CI/CD pipelines

#### Step 10.3: Verification
- [ ] Compare generated manifests old vs new
- [ ] Test all environments (local, dev, gcp)
- [ ] Test all app types

---

## Summary

This refactoring plan transforms four separate Python libraries into a unified, modular, OOP-based architecture. Key improvements:

1. **Single Source of Truth**: One library instead of four
2. **Clean Abstractions**: Protocol-based interfaces, abstract base classes
3. **Strategy Pattern**: Environment-specific behavior isolated
4. **Factory Pattern**: Easy registration of new app types
5. **Composite Pattern**: Manifest generators as composable units
6. **Modern Python 3.12**: Type hints, pattern matching, `|` unions
7. **Comprehensive Testing**: Unit and integration tests
8. **Backward Compatibility**: Gradual migration with deprecation wrappers

The implementation follows a phased approach, allowing incremental progress while maintaining a working system throughout the migration.

---

*Last Updated: December 2025*
