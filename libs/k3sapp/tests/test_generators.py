"""Tests for k3sapp Kubernetes manifest generators."""

import pytest

from k3sapp.generators import (
    generate_deployment,
    generate_service,
    generate_httpscaledobject,
    generate_hpa,
    generate_ingress,
    generate_network_policy,
    generate_pdb,
    generate_all_manifests,
)
from k3sapp.types import (
    AppConfig,
    AppsYamlConfig,
    Environment,
    ScalingType,
    Visibility,
)


@pytest.fixture
def minimal_app():
    """Create minimal app config for testing."""
    return AppConfig.from_dict({
        "name": "testapp",
        "path": "apps/testapp",
    })


@pytest.fixture
def full_app():
    """Create full app config for testing."""
    return AppConfig.from_dict({
        "name": "myapp",
        "path": "apps/myapp",
        "namespace": "production",
        "build": {
            "dockerfile": "Dockerfile",
        },
        "container": {
            "ports": [
                {"name": "http", "container_port": 8080, "service_port": 80},
            ],
        },
        "resources": {
            "memory": "512Mi",
            "cpu": "250m",
            "memory_limit": "1Gi",
        },
        "scaling": {
            "type": "keda-http",
            "min_instances": 0,
            "max_instances": 10,
            "target_pending_requests": 100,
        },
        "probes": {
            "readiness": {
                "type": "http",
                "path": "/health",
                "port": 8080,
            },
            "liveness": {
                "type": "http",
                "path": "/health",
                "port": 8080,
            },
        },
        "ingress": {
            "enabled": True,
            "path": "/api",
            "strip_prefix": True,
        },
        "security": {
            "visibility": "public",
            "network_policy": {
                "enabled": True,
            },
        },
        "environment": {
            "LOG_LEVEL": "INFO",
        },
        "local": {
            "scaling": {"type": "none"},
            "replicas": 1,
        },
    })


@pytest.fixture
def apps_config():
    """Create apps.yaml config for testing."""
    return AppsYamlConfig.from_dict({
        "version": "2",
        "defaults": {
            "namespace": "apps",
            "registry": {
                "local": "",
                "gcp": "gcr.io/myproject/apps",
            },
            "ingress": {
                "local": "traefik",
                "gcp": "haproxy",
            },
        },
        "apps": [],
    })


class TestGenerateDeployment:
    def test_minimal_deployment(self, minimal_app, apps_config):
        deployment = generate_deployment(
            minimal_app,
            Environment.LOCAL,
            "testapp:latest",
            apps_config,
        )

        assert deployment["apiVersion"] == "apps/v1"
        assert deployment["kind"] == "Deployment"
        assert deployment["metadata"]["name"] == "testapp"
        assert deployment["metadata"]["namespace"] == "apps"

        # Check container
        containers = deployment["spec"]["template"]["spec"]["containers"]
        assert len(containers) == 1
        assert containers[0]["name"] == "testapp"
        assert containers[0]["image"] == "testapp:latest"

    def test_deployment_with_resources(self, full_app, apps_config):
        deployment = generate_deployment(
            full_app,
            Environment.GCP,
            "myapp:v1.0",
            apps_config,
        )

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        resources = container["resources"]

        assert resources["requests"]["memory"] == "512Mi"
        assert resources["requests"]["cpu"] == "250m"
        assert resources["limits"]["memory"] == "1Gi"

    def test_deployment_with_probes(self, full_app, apps_config):
        deployment = generate_deployment(
            full_app,
            Environment.GCP,
            "myapp:v1.0",
            apps_config,
        )

        container = deployment["spec"]["template"]["spec"]["containers"][0]

        assert "readinessProbe" in container
        assert container["readinessProbe"]["httpGet"]["path"] == "/health"
        assert container["readinessProbe"]["httpGet"]["port"] == 8080

        assert "livenessProbe" in container
        assert container["livenessProbe"]["httpGet"]["path"] == "/health"

    def test_deployment_env_vars(self, full_app, apps_config):
        deployment = generate_deployment(
            full_app,
            Environment.GCP,
            "myapp:v1.0",
            apps_config,
        )

        container = deployment["spec"]["template"]["spec"]["containers"][0]
        env_vars = {e["name"]: e["value"] for e in container.get("env", [])}

        assert env_vars.get("LOG_LEVEL") == "INFO"

    def test_deployment_replicas_from_scaling(self, full_app, apps_config):
        # GCP uses KEDA, so min_instances = 0
        deployment = generate_deployment(
            full_app,
            Environment.GCP,
            "myapp:v1.0",
            apps_config,
        )
        assert deployment["spec"]["replicas"] == 0

    def test_deployment_replicas_local_override(self, full_app, apps_config):
        # Local has scaling.type = none and replicas = 1
        deployment = generate_deployment(
            full_app,
            Environment.LOCAL,
            "myapp:latest",
            apps_config,
        )
        assert deployment["spec"]["replicas"] == 1


class TestGenerateService:
    def test_service_creation(self, minimal_app):
        service = generate_service(minimal_app, Environment.LOCAL)

        assert service["apiVersion"] == "v1"
        assert service["kind"] == "Service"
        assert service["metadata"]["name"] == "testapp"

        # Check port
        ports = service["spec"]["ports"]
        assert len(ports) >= 1

    def test_service_with_custom_ports(self, full_app):
        service = generate_service(full_app, Environment.GCP)

        ports = service["spec"]["ports"]
        assert any(p["port"] == 80 for p in ports)
        assert any(p["targetPort"] == 8080 for p in ports)


class TestGenerateHTTPScaledObject:
    def test_httpscaledobject_creation(self, full_app, apps_config):
        hso = generate_httpscaledobject(full_app, Environment.GCP, apps_config)

        assert hso["apiVersion"] == "http.keda.sh/v1alpha1"
        assert hso["kind"] == "HTTPScaledObject"
        assert hso["metadata"]["name"] == "myapp-http"

        spec = hso["spec"]
        assert spec["scaleTargetRef"]["name"] == "myapp"
        assert spec["replicas"]["min"] == 0
        assert spec["replicas"]["max"] == 10
        # The actual key is scalingMetric.requestRate.targetValue
        assert spec["scalingMetric"]["requestRate"]["targetValue"] == 100

    def test_httpscaledobject_none_scaling(self, apps_config):
        # App with scaling.type = none should return None for HTTPScaledObject
        app = AppConfig.from_dict({
            "name": "noscaleapp",
            "path": "apps/noscaleapp",
            "scaling": {
                "type": "none",
            },
        })
        hso = generate_httpscaledobject(app, Environment.GCP, apps_config)
        # App with scaling type = none should not generate HTTPScaledObject
        assert hso is None


class TestGenerateHPA:
    def test_hpa_creation(self):
        app = AppConfig.from_dict({
            "name": "hpaapp",
            "path": "apps/hpaapp",
            "scaling": {
                "type": "hpa",
                "min_instances": 2,
                "max_instances": 10,
                "target_cpu_percent": 70,
            },
        })

        hpa = generate_hpa(app, Environment.GCP)

        assert hpa["apiVersion"] == "autoscaling/v2"
        assert hpa["kind"] == "HorizontalPodAutoscaler"
        assert hpa["spec"]["minReplicas"] == 2
        assert hpa["spec"]["maxReplicas"] == 10


class TestGenerateIngress:
    def test_traefik_ingress(self, full_app, apps_config):
        manifests = generate_ingress(full_app, Environment.LOCAL, apps_config)

        # Returns a list of manifests (middleware + ingress route)
        assert isinstance(manifests, list)
        assert len(manifests) > 0

        # Find IngressRoute
        kinds = [m["kind"] for m in manifests]
        assert "IngressRoute" in kinds or "Middleware" in kinds

    def test_haproxy_ingress(self, full_app, apps_config):
        manifests = generate_ingress(full_app, Environment.GCP, apps_config)

        # Returns a list of manifests
        assert isinstance(manifests, list)
        assert len(manifests) > 0

        # Find Ingress
        ingresses = [m for m in manifests if m["kind"] == "Ingress"]
        assert len(ingresses) > 0

        ingress = ingresses[0]
        assert ingress["apiVersion"] == "networking.k8s.io/v1"

        # HAProxy annotations
        annotations = ingress["metadata"].get("annotations", {})
        assert any("haproxy" in k.lower() for k in annotations.keys())

    def test_ingress_path_configuration(self, full_app, apps_config):
        manifests = generate_ingress(full_app, Environment.GCP, apps_config)

        ingresses = [m for m in manifests if m["kind"] == "Ingress"]
        assert len(ingresses) > 0

        ingress = ingresses[0]
        rules = ingress["spec"]["rules"]
        assert len(rules) >= 1

        # Check path
        paths = rules[0]["http"]["paths"]
        assert any(p["path"] == "/api" for p in paths)


class TestGenerateNetworkPolicy:
    def test_public_network_policy(self, full_app, apps_config):
        policy = generate_network_policy(full_app, Environment.GCP, apps_config)

        assert policy["apiVersion"] == "networking.k8s.io/v1"
        assert policy["kind"] == "NetworkPolicy"

        # Public visibility should allow ingress
        ingress = policy["spec"].get("ingress", [])
        assert len(ingress) > 0

    def test_private_network_policy(self, apps_config):
        app = AppConfig.from_dict({
            "name": "privateapp",
            "path": "apps/privateapp",
            "security": {
                "visibility": "private",
                "network_policy": {
                    "enabled": True,
                },
            },
        })

        policy = generate_network_policy(app, Environment.GCP, apps_config)

        # Private visibility should restrict ingress to same namespace
        assert policy["spec"]["podSelector"]["matchLabels"]["app"] == "privateapp"


class TestGeneratePDB:
    def test_pdb_creation(self):
        app = AppConfig.from_dict({
            "name": "pdbapp",
            "path": "apps/pdbapp",
            "gcp": {
                "pod_disruption_budget": {
                    "min_available": 1,
                },
            },
        })

        pdb = generate_pdb(app, Environment.GCP)

        assert pdb["apiVersion"] == "policy/v1"
        assert pdb["kind"] == "PodDisruptionBudget"
        assert pdb["spec"]["minAvailable"] == 1


class TestGenerateAllManifests:
    def test_all_manifests_generated(self, full_app, apps_config):
        manifests = generate_all_manifests(
            full_app,
            Environment.GCP,
            apps_config,
        )

        # Should include Deployment, Service, HTTPScaledObject, Ingress, NetworkPolicy
        kinds = [m["kind"] for m in manifests]

        assert "Deployment" in kinds
        assert "Service" in kinds
        assert "HTTPScaledObject" in kinds
        assert "Ingress" in kinds
        assert "NetworkPolicy" in kinds

    def test_hpa_instead_of_keda(self, apps_config):
        app = AppConfig.from_dict({
            "name": "hpaapp",
            "path": "apps/hpaapp",
            "scaling": {
                "type": "hpa",
                "min_instances": 1,
                "max_instances": 5,
                "target_cpu_percent": 80,
            },
        })

        manifests = generate_all_manifests(
            app,
            Environment.GCP,
            apps_config,
        )

        kinds = [m["kind"] for m in manifests]

        assert "HorizontalPodAutoscaler" in kinds
        assert "HTTPScaledObject" not in kinds

    def test_no_ingress_when_disabled(self, apps_config):
        app = AppConfig.from_dict({
            "name": "noingress",
            "path": "apps/noingress",
            "ingress": {
                "enabled": False,
            },
        })

        manifests = generate_all_manifests(
            app,
            Environment.GCP,
            apps_config,
        )

        kinds = [m["kind"] for m in manifests]
        assert "Ingress" not in kinds
