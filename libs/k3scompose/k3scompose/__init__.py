"""
K3s Compose - CLI tool for Docker Compose projects

Converts docker-compose.yaml to Kubernetes manifests.
"""

__version__ = "0.1.0"

from .types import (
    Environment,
    ComposeService,
    ComposeProject,
    ComposeConfig,
)

from .parser import (
    load_docker_compose,
    load_compose_config,
)

from .generators import (
    generate_deployment,
    generate_service,
    generate_configmap,
    generate_secret,
    generate_pvc,
    generate_all_manifests,
)

__all__ = [
    # Types
    "Environment",
    "ComposeService",
    "ComposeProject",
    "ComposeConfig",
    # Parser
    "load_docker_compose",
    "load_compose_config",
    # Generators
    "generate_deployment",
    "generate_service",
    "generate_configmap",
    "generate_secret",
    "generate_pvc",
    "generate_all_manifests",
]
