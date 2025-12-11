"""Tests for k3scompose parser."""

import os
import tempfile
from pathlib import Path

import pytest
import yaml

from k3scompose.parser import (
    load_compose_config,
    load_docker_compose,
    parse_compose_project,
    get_compose_project,
    get_enabled_compose_projects,
    resolve_compose_project,
)
from k3scompose.types import ComposeConfig, Environment


@pytest.fixture
def docker_compose_content():
    """Sample docker-compose.yaml content."""
    return {
        "version": "3.8",
        "services": {
            "web": {
                "image": "nginx:alpine",
                "ports": ["80:80"],
            },
            "api": {
                "build": {"context": "."},
                "ports": ["8080:8080"],
                "environment": {"DATABASE_URL": "postgres://db:5432/app"},
                "depends_on": ["db"],
            },
            "db": {
                "image": "postgres:15",
                "volumes": ["db-data:/var/lib/postgresql/data"],
                "environment": {"POSTGRES_PASSWORD": "secret"},
            },
        },
        "volumes": {
            "db-data": {},
        },
    }


@pytest.fixture
def apps_yaml_content():
    """Sample apps.yaml with compose projects."""
    return {
        "version": "2",
        "compose": [
            {
                "name": "project1",
                "path": "apps/project1",
                "enabled": True,
            },
            {
                "name": "project2",
                "path": "apps/project2",
                "enabled": True,
                "gcp": {"enabled": False},
            },
            {
                "name": "project3",
                "path": "apps/project3",
                "enabled": False,
            },
        ],
    }


@pytest.fixture
def temp_compose_dir(docker_compose_content, tmp_path):
    """Create temporary directory with docker-compose.yaml."""
    compose_dir = tmp_path / "project"
    compose_dir.mkdir()

    compose_file = compose_dir / "docker-compose.yaml"
    with open(compose_file, "w") as f:
        yaml.dump(docker_compose_content, f)

    return str(compose_dir)


@pytest.fixture
def temp_apps_yaml(apps_yaml_content, tmp_path):
    """Create temporary apps.yaml file."""
    apps_file = tmp_path / "apps.yaml"
    with open(apps_file, "w") as f:
        yaml.dump(apps_yaml_content, f)
    return str(apps_file)


class TestLoadDockerCompose:
    def test_load_yaml(self, temp_compose_dir):
        data = load_docker_compose(temp_compose_dir)

        assert "services" in data
        assert "web" in data["services"]
        assert "api" in data["services"]
        assert "db" in data["services"]

    def test_load_yml_extension(self, docker_compose_content, tmp_path):
        compose_dir = tmp_path / "yml_project"
        compose_dir.mkdir()

        # Use .yml extension
        compose_file = compose_dir / "docker-compose.yml"
        with open(compose_file, "w") as f:
            yaml.dump(docker_compose_content, f)

        data = load_docker_compose(str(compose_dir))
        assert "services" in data

    def test_load_compose_yaml(self, docker_compose_content, tmp_path):
        compose_dir = tmp_path / "compose_project"
        compose_dir.mkdir()

        # Use compose.yaml
        compose_file = compose_dir / "compose.yaml"
        with open(compose_file, "w") as f:
            yaml.dump(docker_compose_content, f)

        data = load_docker_compose(str(compose_dir))
        assert "services" in data

    def test_file_not_found(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        with pytest.raises(FileNotFoundError):
            load_docker_compose(str(empty_dir))


class TestParseComposeProject:
    def test_parse_project(self, temp_compose_dir):
        project = parse_compose_project("testproject", temp_compose_dir)

        assert project.name == "testproject"
        assert project.path == temp_compose_dir
        assert len(project.services) == 3
        assert len(project.volumes) == 1

    def test_service_properties(self, temp_compose_dir):
        project = parse_compose_project("testproject", temp_compose_dir)

        # Find the web service
        web = next(s for s in project.services if s.name == "web")
        assert web.image == "nginx:alpine"
        assert len(web.ports) == 1
        assert web.ports[0].container_port == 80

        # Find the api service
        api = next(s for s in project.services if s.name == "api")
        assert api.build is not None
        assert "DATABASE_URL" in api.environment
        assert "db" in api.depends_on

        # Find the db service
        db = next(s for s in project.services if s.name == "db")
        assert db.image == "postgres:15"
        assert len(db.volumes) == 1


class TestLoadComposeConfig:
    def test_load_configs(self, temp_apps_yaml):
        configs = load_compose_config(temp_apps_yaml)

        assert len(configs) == 3
        assert all(isinstance(c, ComposeConfig) for c in configs)

    def test_config_properties(self, temp_apps_yaml):
        configs = load_compose_config(temp_apps_yaml)

        project1 = next(c for c in configs if c.name == "project1")
        assert project1.path == "apps/project1"
        assert project1.enabled is True

    def test_file_not_found(self):
        with pytest.raises(FileNotFoundError):
            load_compose_config("/nonexistent/apps.yaml")


class TestGetComposeProject:
    def test_get_existing_project(self, temp_apps_yaml):
        config = get_compose_project("project1", temp_apps_yaml)

        assert config is not None
        assert config.name == "project1"

    def test_get_nonexistent_project(self, temp_apps_yaml):
        config = get_compose_project("nonexistent", temp_apps_yaml)
        assert config is None


class TestGetEnabledComposeProjects:
    def test_enabled_for_local(self, temp_apps_yaml):
        enabled = get_enabled_compose_projects(Environment.LOCAL, temp_apps_yaml)

        names = [c.name for c in enabled]
        assert "project1" in names
        assert "project2" in names
        assert "project3" not in names  # Globally disabled

    def test_enabled_for_gcp(self, temp_apps_yaml):
        enabled = get_enabled_compose_projects(Environment.GCP, temp_apps_yaml)

        names = [c.name for c in enabled]
        assert "project1" in names
        assert "project2" not in names  # Disabled for GCP
        assert "project3" not in names


class TestResolveComposeProject:
    def test_resolve_project(self, docker_compose_content, tmp_path):
        # Create project structure
        base_path = tmp_path / "repo"
        base_path.mkdir()

        project_dir = base_path / "apps" / "myproject"
        project_dir.mkdir(parents=True)

        compose_file = project_dir / "docker-compose.yaml"
        with open(compose_file, "w") as f:
            yaml.dump(docker_compose_content, f)

        config = ComposeConfig.from_dict({
            "name": "myproject",
            "path": "apps/myproject",
        })

        project = resolve_compose_project(config, str(base_path))

        assert project.name == "myproject"
        assert len(project.services) == 3
