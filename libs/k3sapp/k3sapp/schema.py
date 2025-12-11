"""
Schema loading and validation for apps.yaml v2.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

try:
    import jsonschema
    HAS_JSONSCHEMA = True
except ImportError:
    HAS_JSONSCHEMA = False

from .types import AppConfig, AppsYamlConfig, Environment


def get_schema_path() -> Path:
    """Get path to JSON schema file."""
    # Try relative to this file first
    schema_dir = Path(__file__).parent.parent.parent.parent / "schemas"
    schema_path = schema_dir / "apps-schema.json"
    if schema_path.exists():
        return schema_path

    # Try from project root
    for parent in Path(__file__).parents:
        candidate = parent / "schemas" / "apps-schema.json"
        if candidate.exists():
            return candidate

    raise FileNotFoundError("Could not find apps-schema.json")


def load_schema() -> Dict[str, Any]:
    """Load the JSON schema for apps.yaml."""
    schema_path = get_schema_path()
    with open(schema_path) as f:
        return json.load(f)


def validate_apps_yaml(data: Dict[str, Any]) -> List[str]:
    """
    Validate apps.yaml data against JSON schema.

    Returns list of validation errors (empty if valid).
    """
    if not HAS_JSONSCHEMA:
        return []  # Skip validation if jsonschema not installed

    try:
        schema = load_schema()
        validator = jsonschema.Draft7Validator(schema)
        errors = []
        for error in validator.iter_errors(data):
            path = ".".join(str(p) for p in error.absolute_path)
            errors.append(f"{path}: {error.message}" if path else error.message)
        return errors
    except FileNotFoundError:
        return []  # Skip validation if schema file not found
    except Exception as e:
        return [f"Schema validation error: {e}"]


def load_apps_yaml(
    path: str = "apps.yaml",
    validate: bool = True,
) -> AppsYamlConfig:
    """
    Load and parse apps.yaml file.

    Args:
        path: Path to apps.yaml file
        validate: Whether to validate against schema

    Returns:
        Parsed AppsYamlConfig

    Raises:
        FileNotFoundError: If apps.yaml not found
        ValueError: If validation fails
    """
    apps_path = Path(path)
    if not apps_path.exists():
        raise FileNotFoundError(f"apps.yaml not found at {path}")

    with open(apps_path) as f:
        data = yaml.safe_load(f)

    if validate:
        errors = validate_apps_yaml(data)
        if errors:
            raise ValueError(f"apps.yaml validation failed:\n" + "\n".join(errors))

    return AppsYamlConfig.from_dict(data)


def get_app_config(
    app_name: str,
    env: Environment,
    apps_yaml_path: str = "apps.yaml",
) -> Optional[AppConfig]:
    """
    Get app configuration with environment-specific overrides applied.

    Args:
        app_name: Name of the app
        env: Target environment
        apps_yaml_path: Path to apps.yaml

    Returns:
        AppConfig or None if not found
    """
    config = load_apps_yaml(apps_yaml_path)
    return config.get_app(app_name)


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


def get_enabled_apps(
    env: Environment,
    apps_yaml_path: str = "apps.yaml",
) -> List[AppConfig]:
    """
    Get list of enabled apps for the given environment.

    Args:
        env: Target environment
        apps_yaml_path: Path to apps.yaml

    Returns:
        List of enabled AppConfig objects
    """
    config = load_apps_yaml(apps_yaml_path)
    enabled = []

    for app in config.apps:
        # Check base enabled flag
        if not app.enabled:
            continue

        # Check environment-specific enabled flag
        env_override = app.get_env_override(env)
        if env_override and env_override.enabled is False:
            continue

        enabled.append(app)

    return enabled


def resolve_registry_url(
    app: AppConfig,
    env: Environment,
    config: AppsYamlConfig,
) -> str:
    """
    Resolve the full container image URL for an app.

    Args:
        app: App configuration
        env: Target environment
        config: Root apps.yaml config

    Returns:
        Full image URL
    """
    registry = config.defaults.get_registry(env)
    if registry:
        return f"{registry}/{app.name}:latest"
    return f"{app.name}:latest"


def get_ingress_type(
    env: Environment,
    config: AppsYamlConfig,
) -> str:
    """
    Get ingress controller type for environment.

    Args:
        env: Target environment
        config: Root apps.yaml config

    Returns:
        Ingress type: "traefik" or "haproxy"
    """
    return config.defaults.get_ingress_type(env)
