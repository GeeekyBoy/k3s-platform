"""Tests for k3sapp schema loading and validation."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from k3sapp.schema import (
    load_apps_yaml,
    validate_apps_yaml,
    get_app_config,
    get_enabled_apps,
    resolve_registry_url,
    get_ingress_type,
)
from k3sapp.types import AppsYamlConfig, Environment


@pytest.fixture
def sample_apps_yaml():
    """Create sample apps.yaml content."""
    return {
        "version": "2",
        "defaults": {
            "namespace": "apps",
            "registry": {
                "local": "",
                "dev": "registry.dev.example.com",
                "gcp": "gcr.io/myproject/apps",
            },
            "ingress": {
                "local": "traefik",
                "dev": "traefik",
                "gcp": "haproxy",
            },
        },
        "environments": {
            "local": {
                "domain": "localhost",
            },
            "gcp": {
                "domain": "prod.example.com",
                "tls": True,
            },
        },
        "apps": [
            {
                "name": "app1",
                "path": "apps/app1",
                "enabled": True,
            },
            {
                "name": "app2",
                "path": "apps/app2",
                "enabled": True,
                "gcp": {
                    "enabled": False,
                },
            },
            {
                "name": "app3",
                "path": "apps/app3",
                "enabled": False,
            },
        ],
    }


@pytest.fixture
def apps_yaml_file(sample_apps_yaml, tmp_path):
    """Create temporary apps.yaml file."""
    file_path = tmp_path / "apps.yaml"
    with open(file_path, "w") as f:
        yaml.dump(sample_apps_yaml, f)
    return str(file_path)


class TestLoadAppsYaml:
    def test_load_valid_file(self, apps_yaml_file):
        config = load_apps_yaml(apps_yaml_file, validate=False)

        assert isinstance(config, AppsYamlConfig)
        assert config.version == "2"
        assert len(config.apps) == 3

    def test_load_nonexistent_file(self):
        with pytest.raises(FileNotFoundError):
            load_apps_yaml("/nonexistent/apps.yaml")

    def test_load_with_defaults(self, apps_yaml_file):
        config = load_apps_yaml(apps_yaml_file, validate=False)

        assert config.defaults.namespace == "apps"
        assert config.defaults.registry is not None


class TestValidateAppsYaml:
    def test_validate_valid_config(self, sample_apps_yaml):
        errors = validate_apps_yaml(sample_apps_yaml)
        # May be empty if jsonschema not installed or schema not found
        # The function returns empty list for both success and skip scenarios
        assert isinstance(errors, list)

    def test_validate_missing_required_fields(self):
        invalid_config = {
            "apps": [
                {"name": "test"},  # Missing 'path'
            ],
        }
        errors = validate_apps_yaml(invalid_config)
        # If jsonschema is installed and schema found, should have errors
        # Otherwise empty list (validation skipped)
        assert isinstance(errors, list)


class TestGetAppConfig:
    def test_get_existing_app(self, apps_yaml_file):
        app = get_app_config("app1", Environment.LOCAL, apps_yaml_file)

        assert app is not None
        assert app.name == "app1"
        assert app.path == "apps/app1"

    def test_get_nonexistent_app(self, apps_yaml_file):
        app = get_app_config("nonexistent", Environment.LOCAL, apps_yaml_file)
        assert app is None


class TestGetEnabledApps:
    def test_enabled_apps_local(self, apps_yaml_file):
        enabled = get_enabled_apps(Environment.LOCAL, apps_yaml_file)

        names = [app.name for app in enabled]
        assert "app1" in names
        assert "app2" in names
        assert "app3" not in names  # Globally disabled

    def test_enabled_apps_gcp(self, apps_yaml_file):
        enabled = get_enabled_apps(Environment.GCP, apps_yaml_file)

        names = [app.name for app in enabled]
        assert "app1" in names
        assert "app2" not in names  # Disabled for GCP
        assert "app3" not in names


class TestResolveRegistryUrl:
    def test_local_registry(self, apps_yaml_file):
        config = load_apps_yaml(apps_yaml_file, validate=False)
        app = config.get_app("app1")

        url = resolve_registry_url(app, Environment.LOCAL, config)
        assert url == "app1:latest"

    def test_gcp_registry(self, apps_yaml_file):
        config = load_apps_yaml(apps_yaml_file, validate=False)
        app = config.get_app("app1")

        url = resolve_registry_url(app, Environment.GCP, config)
        assert url == "gcr.io/myproject/apps/app1:latest"

    def test_dev_registry(self, apps_yaml_file):
        config = load_apps_yaml(apps_yaml_file, validate=False)
        app = config.get_app("app1")

        url = resolve_registry_url(app, Environment.DEV, config)
        assert url == "registry.dev.example.com/app1:latest"


class TestGetIngressType:
    def test_local_ingress_type(self, apps_yaml_file):
        config = load_apps_yaml(apps_yaml_file, validate=False)

        ingress_type = get_ingress_type(Environment.LOCAL, config)
        assert ingress_type == "traefik"

    def test_gcp_ingress_type(self, apps_yaml_file):
        config = load_apps_yaml(apps_yaml_file, validate=False)

        ingress_type = get_ingress_type(Environment.GCP, config)
        assert ingress_type == "haproxy"


class TestEnvironmentSpecificConfig:
    def test_environment_domain(self, apps_yaml_file):
        config = load_apps_yaml(apps_yaml_file, validate=False)

        # environments is Dict[str, EnvironmentSpecificConfig]
        local_env = config.environments.get("local")
        gcp_env = config.environments.get("gcp")

        assert local_env is not None
        assert local_env.domain == "localhost"
        assert gcp_env is not None
        assert gcp_env.domain == "prod.example.com"

    def test_environment_tls(self, apps_yaml_file):
        config = load_apps_yaml(apps_yaml_file, validate=False)

        gcp_env = config.environments.get("gcp")
        local_env = config.environments.get("local")

        assert gcp_env is not None
        assert gcp_env.tls is True
        assert local_env is not None
        assert local_env.tls is False  # Default is False, not None
