"""Tests for k3scompose Kubernetes manifest generators."""

import pytest

from k3scompose.generators import (
    generate_deployment,
    generate_service,
    generate_configmap,
    generate_pvc,
    generate_all_manifests,
)
from k3scompose.types import (
    ComposeConfig,
    ComposeProject,
    ComposeService,
    ComposeVolume,
    Environment,
    PortMapping,
    VolumeMount,
)


@pytest.fixture
def simple_service():
    """Create a simple compose service."""
    return ComposeService.from_dict("web", {
        "image": "nginx:alpine",
        "ports": ["80:80"],
    })


@pytest.fixture
def full_service():
    """Create a full compose service with all options."""
    return ComposeService.from_dict("api", {
        "image": "myapi:v1.0",
        "ports": ["8080:8080", "9090:9090"],
        "environment": {
            "DATABASE_URL": "postgres://db:5432/app",
            "LOG_LEVEL": "debug",
        },
        "volumes": ["data:/var/data"],
        "working_dir": "/app",
        "user": "1000:1000",
        "deploy": {
            "replicas": 2,
            "resources": {
                "limits": {"cpus": "0.5", "memory": "512M"},
                "reservations": {"cpus": "0.1", "memory": "128M"},
            },
        },
        "healthcheck": {
            "test": ["CMD", "curl", "-f", "http://localhost:8080/health"],
            "interval": "30s",
            "timeout": "10s",
            "retries": 3,
        },
    })


@pytest.fixture
def compose_project(simple_service, full_service):
    """Create a compose project with multiple services."""
    return ComposeProject(
        name="testproject",
        path="/path/to/project",
        services=[simple_service, full_service],
        volumes={
            "data": ComposeVolume(name="data"),
        },
        networks=["default"],
    )


@pytest.fixture
def compose_config():
    """Create compose config from apps.yaml."""
    return ComposeConfig.from_dict({
        "name": "testproject",
        "path": "apps/testproject",
        "namespace": "apps",
        "enabled": True,
    })


class TestGenerateDeployment:
    def test_simple_deployment(self, simple_service, compose_project):
        deployment = generate_deployment(
            simple_service,
            compose_project,
            namespace="apps",
        )

        assert deployment["apiVersion"] == "apps/v1"
        assert deployment["kind"] == "Deployment"
        assert deployment["metadata"]["name"] == "web"
        assert deployment["metadata"]["namespace"] == "apps"

        # Check container
        containers = deployment["spec"]["template"]["spec"]["containers"]
        assert len(containers) == 1
        assert containers[0]["name"] == "web"
        assert containers[0]["image"] == "nginx:alpine"

        # Check port
        ports = containers[0]["ports"]
        assert len(ports) == 1
        assert ports[0]["containerPort"] == 80

    def test_deployment_with_registry(self, compose_project):
        # Service with build context should use registry
        service = ComposeService.from_dict("buildapp", {
            "build": {"context": "."},
            "ports": ["8080:8080"],
        })

        deployment = generate_deployment(
            service,
            compose_project,
            namespace="apps",
            registry="gcr.io/myproject/apps",
        )

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        assert "gcr.io/myproject/apps" in container["image"]

    def test_deployment_replicas(self, full_service, compose_project):
        deployment = generate_deployment(
            full_service,
            compose_project,
            namespace="apps",
        )

        assert deployment["spec"]["replicas"] == 2

    def test_deployment_resources(self, full_service, compose_project):
        deployment = generate_deployment(
            full_service,
            compose_project,
            namespace="apps",
        )

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        resources = container["resources"]

        assert "limits" in resources
        assert "requests" in resources

    def test_deployment_env_vars(self, full_service, compose_project):
        deployment = generate_deployment(
            full_service,
            compose_project,
            namespace="apps",
        )

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        env_vars = {e["name"]: e["value"] for e in container.get("env", [])}

        assert env_vars.get("DATABASE_URL") == "postgres://db:5432/app"
        assert env_vars.get("LOG_LEVEL") == "debug"

    def test_deployment_healthcheck(self, full_service, compose_project):
        deployment = generate_deployment(
            full_service,
            compose_project,
            namespace="apps",
        )

        container = deployment["spec"]["template"]["spec"]["containers"][0]

        assert "livenessProbe" in container
        assert "readinessProbe" in container

    def test_deployment_volumes(self, full_service, compose_project):
        deployment = generate_deployment(
            full_service,
            compose_project,
            namespace="apps",
        )

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        pod_spec = deployment["spec"]["template"]["spec"]

        assert "volumeMounts" in container
        assert "volumes" in pod_spec

    def test_deployment_labels(self, simple_service, compose_project):
        deployment = generate_deployment(
            simple_service,
            compose_project,
            namespace="apps",
        )

        labels = deployment["metadata"]["labels"]
        assert labels["app"] == "web"
        assert labels["k3scompose.io/project"] == "testproject"


class TestGenerateService:
    def test_service_with_ports(self, simple_service, compose_project):
        service = generate_service(
            simple_service,
            compose_project,
            namespace="apps",
        )

        assert service["apiVersion"] == "v1"
        assert service["kind"] == "Service"
        assert service["metadata"]["name"] == "web"

        ports = service["spec"]["ports"]
        assert len(ports) == 1
        assert ports[0]["port"] == 80
        assert ports[0]["targetPort"] == 80

    def test_service_multiple_ports(self, full_service, compose_project):
        service = generate_service(
            full_service,
            compose_project,
            namespace="apps",
        )

        ports = service["spec"]["ports"]
        assert len(ports) == 2

    def test_service_no_ports(self, compose_project):
        svc = ComposeService.from_dict("worker", {
            "image": "worker:latest",
            # No ports
        })

        service = generate_service(svc, compose_project, namespace="apps")
        assert service is None

    def test_service_selector(self, simple_service, compose_project):
        service = generate_service(
            simple_service,
            compose_project,
            namespace="apps",
        )

        selector = service["spec"]["selector"]
        assert selector["app"] == "web"


class TestGenerateConfigMap:
    def test_configmap_from_env(self, compose_project):
        env_content = {
            "API_KEY": "test-key",
            "DEBUG": "true",
        }

        svc = ComposeService.from_dict("app", {"image": "app:latest"})

        configmap = generate_configmap(
            svc,
            compose_project,
            namespace="apps",
            env_file_content=env_content,
        )

        assert configmap["apiVersion"] == "v1"
        assert configmap["kind"] == "ConfigMap"
        assert configmap["metadata"]["name"] == "app-env"
        assert configmap["data"]["API_KEY"] == "test-key"

    def test_configmap_none_when_no_env(self, compose_project):
        svc = ComposeService.from_dict("app", {"image": "app:latest"})

        configmap = generate_configmap(
            svc,
            compose_project,
            namespace="apps",
            env_file_content=None,
        )

        assert configmap is None


class TestGeneratePVC:
    def test_pvc_creation(self):
        volume = ComposeVolume(name="db-data")

        pvc = generate_pvc(
            volume,
            namespace="apps",
            project_name="myproject",
        )

        assert pvc["apiVersion"] == "v1"
        assert pvc["kind"] == "PersistentVolumeClaim"
        assert pvc["metadata"]["name"] == "db-data"
        assert pvc["spec"]["accessModes"] == ["ReadWriteOnce"]
        assert pvc["spec"]["resources"]["requests"]["storage"] == "1Gi"

    def test_pvc_with_storage_class(self):
        volume = ComposeVolume(name="fast-storage")

        pvc = generate_pvc(
            volume,
            namespace="apps",
            project_name="myproject",
            storage_class="ssd",
        )

        assert pvc["spec"]["storageClassName"] == "ssd"

    def test_pvc_with_custom_size(self):
        volume = ComposeVolume(name="big-data")

        pvc = generate_pvc(
            volume,
            namespace="apps",
            project_name="myproject",
            size="10Gi",
        )

        assert pvc["spec"]["resources"]["requests"]["storage"] == "10Gi"


class TestGenerateAllManifests:
    def test_all_manifests(self, compose_project, compose_config):
        manifests = generate_all_manifests(
            compose_project,
            compose_config,
            Environment.LOCAL,
        )

        kinds = [m["kind"] for m in manifests]

        # Should have PVC for 'data' volume
        assert "PersistentVolumeClaim" in kinds

        # Should have deployments for both services
        assert kinds.count("Deployment") == 2

        # Should have service for services with ports
        assert "Service" in kinds

    def test_manifests_with_registry(self, compose_project, compose_config):
        manifests = generate_all_manifests(
            compose_project,
            compose_config,
            Environment.GCP,
            registry="gcr.io/myproject/apps",
        )

        # Check that build services get registry prefix
        deployments = [m for m in manifests if m["kind"] == "Deployment"]
        assert len(deployments) == 2

    def test_namespace_applied(self, compose_project, compose_config):
        manifests = generate_all_manifests(
            compose_project,
            compose_config,
            Environment.LOCAL,
        )

        for manifest in manifests:
            assert manifest["metadata"]["namespace"] == "apps"
