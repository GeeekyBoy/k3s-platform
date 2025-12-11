"""Tests for k3sapp types."""

import pytest

from k3sapp.types import (
    AppConfig,
    AppsYamlConfig,
    BuildConfig,
    ContainerConfig,
    Environment,
    IngressConfig,
    PathType,
    PortConfig,
    ProbeConfig,
    ProbesConfig,
    ProbeType,
    ResourcesConfig,
    ScalingConfig,
    ScalingType,
    SecurityConfig,
    Visibility,
    VolumeConfig,
    VolumeType,
)


class TestEnvironment:
    def test_environment_values(self):
        assert Environment.LOCAL.value == "local"
        assert Environment.DEV.value == "dev"
        assert Environment.GCP.value == "gcp"


class TestResourcesConfig:
    def test_default_values(self):
        config = ResourcesConfig()
        assert config.memory == "256Mi"
        assert config.cpu == "100m"
        assert config.memory_limit == "256Mi"  # Defaults to memory

    def test_from_dict(self):
        data = {
            "memory": "512Mi",
            "cpu": "200m",
            "memory_limit": "1Gi",
        }
        config = ResourcesConfig.from_dict(data)
        assert config.memory == "512Mi"
        assert config.cpu == "200m"
        assert config.memory_limit == "1Gi"

    def test_from_dict_empty(self):
        config = ResourcesConfig.from_dict(None)
        assert config.memory == "256Mi"


class TestScalingConfig:
    def test_default_values(self):
        config = ScalingConfig()
        assert config.type == ScalingType.KEDA_HTTP
        assert config.min_instances == 0
        assert config.max_instances == 10

    def test_from_dict(self):
        data = {
            "type": "hpa",
            "min_instances": 1,
            "max_instances": 5,
            "target_cpu_percent": 70,
        }
        config = ScalingConfig.from_dict(data)
        assert config.type == ScalingType.HPA
        assert config.min_instances == 1
        assert config.max_instances == 5
        assert config.target_cpu_percent == 70


class TestProbeConfig:
    def test_from_dict_http(self):
        data = {
            "type": "http",
            "path": "/health",
            "port": 8080,
            "period": 10,
        }
        config = ProbeConfig.from_dict(data)
        assert config.type == ProbeType.HTTP
        assert config.path == "/health"
        assert config.port == 8080

    def test_from_dict_exec(self):
        data = {
            "type": "exec",
            "command": ["cat", "/tmp/healthy"],
        }
        config = ProbeConfig.from_dict(data)
        assert config.type == ProbeType.EXEC
        assert config.command == ["cat", "/tmp/healthy"]

    def test_from_dict_none(self):
        config = ProbeConfig.from_dict(None)
        assert config is None


class TestIngressConfig:
    def test_default_values(self):
        config = IngressConfig()
        assert config.enabled is False
        assert config.path == "/"
        assert config.path_type == PathType.PREFIX

    def test_from_dict(self):
        data = {
            "enabled": True,
            "path": "/api",
            "strip_prefix": True,
        }
        config = IngressConfig.from_dict(data)
        assert config.enabled is True
        assert config.path == "/api"
        assert config.strip_prefix is True


class TestSecurityConfig:
    def test_default_values(self):
        config = SecurityConfig()
        assert config.visibility == Visibility.PRIVATE
        assert config.network_policy.enabled is True

    def test_from_dict(self):
        data = {
            "visibility": "public",
            "service_account": "my-sa",
        }
        config = SecurityConfig.from_dict(data)
        assert config.visibility == Visibility.PUBLIC
        assert config.service_account == "my-sa"


class TestAppConfig:
    def test_from_dict_minimal(self):
        data = {
            "name": "myapp",
            "path": "apps/myapp",
        }
        config = AppConfig.from_dict(data)
        assert config.name == "myapp"
        assert config.path == "apps/myapp"
        assert config.namespace == "apps"
        assert config.enabled is True

    def test_from_dict_full(self):
        data = {
            "name": "myapp",
            "path": "apps/myapp",
            "namespace": "production",
            "enabled": True,
            "build": {
                "dockerfile": "Dockerfile.prod",
            },
            "resources": {
                "memory": "1Gi",
                "cpu": "500m",
            },
            "scaling": {
                "type": "keda-http",
                "min_instances": 0,
                "max_instances": 10,
            },
            "ingress": {
                "enabled": True,
                "path": "/myapp",
            },
            "local": {
                "port": 8000,
                "live_update": True,
            },
        }
        config = AppConfig.from_dict(data)
        assert config.name == "myapp"
        assert config.namespace == "production"
        assert config.build.dockerfile == "Dockerfile.prod"
        assert config.resources.memory == "1Gi"
        assert config.scaling.type == ScalingType.KEDA_HTTP
        assert config.ingress.enabled is True
        assert config.local.port == 8000

    def test_get_effective_scaling(self):
        data = {
            "name": "myapp",
            "path": "apps/myapp",
            "scaling": {
                "type": "keda-http",
                "min_instances": 0,
            },
            "local": {
                "scaling": {
                    "type": "none",
                },
            },
        }
        config = AppConfig.from_dict(data)

        # Default scaling
        scaling = config.get_effective_scaling(Environment.GCP)
        assert scaling.type == ScalingType.KEDA_HTTP

        # Local override
        scaling = config.get_effective_scaling(Environment.LOCAL)
        assert scaling.type == ScalingType.NONE

    def test_get_primary_port(self):
        data = {
            "name": "myapp",
            "path": "apps/myapp",
            "container": {
                "ports": [
                    {"name": "http", "container_port": 8080, "service_port": 80},
                    {"name": "metrics", "container_port": 9090, "service_port": 9090},
                ],
            },
        }
        config = AppConfig.from_dict(data)
        port = config.get_primary_port()
        assert port.name == "http"
        assert port.container_port == 8080


class TestAppsYamlConfig:
    def test_from_dict(self):
        data = {
            "version": "2",
            "defaults": {
                "namespace": "apps",
            },
            "apps": [
                {"name": "app1", "path": "apps/app1"},
                {"name": "app2", "path": "apps/app2", "enabled": False},
            ],
        }
        config = AppsYamlConfig.from_dict(data)
        assert config.version == "2"
        assert len(config.apps) == 2
        assert config.apps[0].name == "app1"
        assert config.apps[1].enabled is False

    def test_get_app(self):
        data = {
            "apps": [
                {"name": "app1", "path": "apps/app1"},
                {"name": "app2", "path": "apps/app2"},
            ],
        }
        config = AppsYamlConfig.from_dict(data)
        app = config.get_app("app1")
        assert app is not None
        assert app.name == "app1"

        app = config.get_app("nonexistent")
        assert app is None
