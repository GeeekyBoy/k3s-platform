"""
K3s App - CLI tool for traditional Dockerfile-based applications

Generates Kubernetes manifests from apps.yaml configuration.
"""

__version__ = "0.1.0"

from .types import (
    Environment,
    ScalingType,
    Visibility,
    PathType,
    AppConfig,
    ResourcesConfig,
    ScalingConfig,
    ProbeConfig,
    ProbesConfig,
    IngressConfig,
    SecurityConfig,
    VolumeConfig,
    BuildConfig,
    ContainerConfig,
    PortConfig,
)

from .schema import (
    load_apps_yaml,
    validate_apps_yaml,
    get_app_config,
)

from .generators import (
    generate_deployment,
    generate_service,
    generate_ingress,
    generate_httpscaledobject,
    generate_network_policy,
    generate_pdb,
    generate_all_manifests,
)

__all__ = [
    # Types
    "Environment",
    "ScalingType",
    "Visibility",
    "PathType",
    "AppConfig",
    "ResourcesConfig",
    "ScalingConfig",
    "ProbeConfig",
    "ProbesConfig",
    "IngressConfig",
    "SecurityConfig",
    "VolumeConfig",
    "BuildConfig",
    "ContainerConfig",
    "PortConfig",
    # Schema
    "load_apps_yaml",
    "validate_apps_yaml",
    "get_app_config",
    # Generators
    "generate_deployment",
    "generate_service",
    "generate_ingress",
    "generate_httpscaledobject",
    "generate_network_policy",
    "generate_pdb",
    "generate_all_manifests",
]
