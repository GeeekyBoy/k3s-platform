"""
CLI tool for K3s Gateway.

Generates Kubernetes Ingress manifests from apps.yaml gateway configuration.
"""

import argparse
import sys
from pathlib import Path
from typing import Any, Dict, Optional

import yaml

from .types import GatewayConfig
from .generators import generate_all_manifests


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


def load_apps_yaml(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Load apps.yaml configuration.

    Args:
        path: Optional path to apps.yaml. If not provided, searches up from cwd.

    Returns:
        Parsed YAML content as dict

    Raises:
        FileNotFoundError: If apps.yaml not found
    """
    if path:
        apps_path = Path(path)
    else:
        apps_path = find_apps_yaml()

    if not apps_path or not apps_path.exists():
        raise FileNotFoundError("apps.yaml not found")

    with open(apps_path) as f:
        return yaml.safe_load(f)


def get_gateway_config(apps_yaml_path: Optional[str] = None) -> GatewayConfig:
    """
    Get gateway configuration from apps.yaml.

    Args:
        apps_yaml_path: Optional path to apps.yaml

    Returns:
        GatewayConfig object
    """
    config = load_apps_yaml(apps_yaml_path)
    return GatewayConfig.from_dict(config.get("gateway"))


def get_environment_settings(
    apps_yaml_path: Optional[str] = None,
    env: str = "local",
) -> Dict[str, Any]:
    """
    Get environment-specific settings from apps.yaml.

    Args:
        apps_yaml_path: Optional path to apps.yaml
        env: Environment name (local, dev, gcp)

    Returns:
        Dict with domain, tls, ingress settings
    """
    config = load_apps_yaml(apps_yaml_path)

    # Get defaults
    defaults = config.get("defaults", {})
    ingress_type = defaults.get("ingress", {}).get(env, "traefik")

    # Get environment-specific settings
    environments = config.get("environments", {})
    env_config = environments.get(env, {})

    return {
        "domain": env_config.get("domain"),
        "tls": env_config.get("tls", False),
        "tls_secret": env_config.get("tls_secret"),
        "ingress_type": ingress_type,
    }


def cmd_generate(args: argparse.Namespace) -> None:
    """Generate gateway manifests."""
    try:
        gateway_config = get_gateway_config(args.apps_yaml)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not gateway_config.routes:
        print("No gateway routes defined in apps.yaml")
        sys.exit(0)

    # Get environment settings
    env_settings = get_environment_settings(args.apps_yaml, args.env)

    # Override with CLI args
    ingress_type = args.ingress or env_settings["ingress_type"]
    domain = args.domain or env_settings["domain"]
    tls_enabled = args.tls if args.tls is not None else env_settings["tls"]
    tls_secret = args.tls_secret or env_settings["tls_secret"]

    print(f"Generating gateway manifests (env: {args.env})")
    print(f"  Ingress type: {ingress_type}")
    print(f"  Domain: {domain or '(none)'}")
    print(f"  TLS: {tls_enabled}")
    print(f"  Routes: {len(gateway_config.routes)}")

    generate_all_manifests(
        gateway_config=gateway_config,
        output_dir=args.output,
        ingress_type=ingress_type,
        domain=domain,
        tls_enabled=tls_enabled,
        tls_secret=tls_secret,
        namespace=args.namespace,
    )


def cmd_list(args: argparse.Namespace) -> None:
    """List gateway routes."""
    try:
        gateway_config = get_gateway_config(args.apps_yaml)
    except FileNotFoundError as e:
        print(f"Error: {e}")
        sys.exit(1)

    if not gateway_config.routes:
        print("No gateway routes defined")
        return

    print("Gateway Routes:")
    print("-" * 60)
    for route in gateway_config.routes:
        strip_info = " [strip_prefix]" if route.strip_prefix else ""
        print(f"  {route.path} -> {route.service}:{route.port}{strip_info}")

    print(f"\nTotal: {len(gateway_config.routes)} routes")

    if gateway_config.rate_limit.enabled:
        print(f"\nRate Limit: {gateway_config.rate_limit.requests_per_second} req/s")

    if gateway_config.cors.enabled:
        print(f"CORS: enabled (origins: {gateway_config.cors.allow_origins})")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="K3s Gateway CLI - Generate Ingress manifests from apps.yaml gateway configuration"
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # Generate command
    gen_parser = subparsers.add_parser("generate", help="Generate gateway manifests")
    gen_parser.add_argument(
        "--output", "-o",
        default="./generated/gateway",
        help="Output directory for manifests"
    )
    gen_parser.add_argument(
        "--apps-yaml",
        default=None,
        help="Path to apps.yaml (default: auto-detect)"
    )
    gen_parser.add_argument(
        "--env", "-e",
        default="local",
        choices=["local", "dev", "gcp"],
        help="Target environment (default: local)"
    )
    gen_parser.add_argument(
        "--ingress", "-i",
        default=None,
        choices=["traefik", "haproxy"],
        help="Ingress controller type (default: from apps.yaml)"
    )
    gen_parser.add_argument(
        "--domain", "-d",
        default=None,
        help="Ingress host domain (default: from apps.yaml)"
    )
    gen_parser.add_argument(
        "--tls",
        action="store_true",
        default=None,
        help="Enable TLS"
    )
    gen_parser.add_argument(
        "--tls-secret",
        default=None,
        help="TLS secret name"
    )
    gen_parser.add_argument(
        "--namespace", "-n",
        default="apps",
        help="Namespace for Traefik resources (default: apps)"
    )

    # List command
    list_parser = subparsers.add_parser("list", help="List gateway routes")
    list_parser.add_argument(
        "--apps-yaml",
        default=None,
        help="Path to apps.yaml (default: auto-detect)"
    )

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "list":
        cmd_list(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
