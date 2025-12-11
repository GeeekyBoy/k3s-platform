"""
Docker Compose parser for k3scompose.

Loads and parses docker-compose.yaml files.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

from .types import ComposeConfig, ComposeProject, Environment


def load_docker_compose(
    path: str,
    filename: str = "docker-compose.yaml",
) -> Dict[str, Any]:
    """
    Load docker-compose.yaml file.

    Args:
        path: Directory containing docker-compose.yaml
        filename: Compose file name (default: docker-compose.yaml)

    Returns:
        Parsed YAML content

    Raises:
        FileNotFoundError: If compose file not found
    """
    compose_path = Path(path) / filename
    if not compose_path.exists():
        # Try alternative names
        alternatives = [
            "docker-compose.yml",
            "compose.yaml",
            "compose.yml",
        ]
        for alt in alternatives:
            alt_path = Path(path) / alt
            if alt_path.exists():
                compose_path = alt_path
                break
        else:
            raise FileNotFoundError(
                f"No docker-compose file found in {path}. "
                f"Tried: {filename}, {', '.join(alternatives)}"
            )

    with open(compose_path) as f:
        return yaml.safe_load(f)


def parse_compose_project(
    name: str,
    path: str,
    filename: str = "docker-compose.yaml",
) -> ComposeProject:
    """
    Parse a docker-compose project.

    Args:
        name: Project name
        path: Directory containing docker-compose.yaml
        filename: Compose file name

    Returns:
        Parsed ComposeProject
    """
    data = load_docker_compose(path, filename)
    return ComposeProject.from_dict(name, path, data)


def load_compose_config(
    apps_yaml_path: str = "apps.yaml",
) -> List[ComposeConfig]:
    """
    Load compose project configurations from apps.yaml.

    Args:
        apps_yaml_path: Path to apps.yaml file

    Returns:
        List of ComposeConfig objects
    """
    apps_path = Path(apps_yaml_path)
    if not apps_path.exists():
        raise FileNotFoundError(f"apps.yaml not found at {apps_yaml_path}")

    with open(apps_path) as f:
        data = yaml.safe_load(f)

    compose_entries = data.get("compose", [])
    return [ComposeConfig.from_dict(c) for c in compose_entries]


def get_compose_project(
    name: str,
    apps_yaml_path: str = "apps.yaml",
) -> Optional[ComposeConfig]:
    """
    Get a specific compose project configuration.

    Args:
        name: Project name
        apps_yaml_path: Path to apps.yaml

    Returns:
        ComposeConfig or None if not found
    """
    configs = load_compose_config(apps_yaml_path)
    for config in configs:
        if config.name == name:
            return config
    return None


def get_enabled_compose_projects(
    env: Environment,
    apps_yaml_path: str = "apps.yaml",
) -> List[ComposeConfig]:
    """
    Get list of enabled compose projects for environment.

    Args:
        env: Target environment
        apps_yaml_path: Path to apps.yaml

    Returns:
        List of enabled ComposeConfig objects
    """
    configs = load_compose_config(apps_yaml_path)
    return [c for c in configs if c.is_enabled(env)]


def resolve_compose_project(
    config: ComposeConfig,
    base_path: str = ".",
) -> ComposeProject:
    """
    Resolve and parse a compose project from its config.

    Args:
        config: ComposeConfig from apps.yaml
        base_path: Base path for resolving relative paths

    Returns:
        Parsed ComposeProject
    """
    project_path = str(Path(base_path) / config.path)
    return parse_compose_project(config.name, project_path, config.file)
