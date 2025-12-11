"""
CLI for k3sapp - Kubernetes manifest generator for traditional apps.

Commands:
    generate    Generate K8s manifests for an app
    generate-all Generate manifests for all enabled apps
    list        List apps from apps.yaml
    validate    Validate apps.yaml schema
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

import yaml

from .generators import generate_all_manifests
from .schema import (
    find_apps_yaml,
    get_enabled_apps,
    load_apps_yaml,
    validate_apps_yaml,
)
from .types import Environment


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="k3sapp",
        description="Generate Kubernetes manifests for traditional apps",
    )
    parser.add_argument(
        "-f", "--file",
        default="apps.yaml",
        help="Path to apps.yaml (default: apps.yaml)",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose output",
    )

    subparsers = parser.add_subparsers(dest="command", help="Commands")

    # generate command
    gen_parser = subparsers.add_parser(
        "generate",
        help="Generate K8s manifests for an app",
    )
    gen_parser.add_argument(
        "app",
        help="App name to generate manifests for",
    )
    gen_parser.add_argument(
        "-e", "--env",
        choices=["local", "dev", "gcp"],
        default="local",
        help="Target environment (default: local)",
    )
    gen_parser.add_argument(
        "-o", "--output",
        help="Output directory (default: stdout)",
    )
    gen_parser.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format (default: yaml)",
    )

    # generate-all command
    gen_all_parser = subparsers.add_parser(
        "generate-all",
        help="Generate manifests for all enabled apps",
    )
    gen_all_parser.add_argument(
        "-e", "--env",
        choices=["local", "dev", "gcp"],
        default="local",
        help="Target environment (default: local)",
    )
    gen_all_parser.add_argument(
        "-o", "--output",
        help="Output directory (required)",
        required=True,
    )
    gen_all_parser.add_argument(
        "--format",
        choices=["yaml", "json"],
        default="yaml",
        help="Output format (default: yaml)",
    )

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List apps from apps.yaml",
    )
    list_parser.add_argument(
        "-e", "--env",
        choices=["local", "dev", "gcp"],
        help="Filter by environment (show only enabled apps)",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # validate command
    subparsers.add_parser(
        "validate",
        help="Validate apps.yaml schema",
    )

    return parser


def output_manifests(
    manifests: list,
    output_format: str,
    output_path: Optional[str] = None,
    app_name: Optional[str] = None,
) -> None:
    """Output manifests to file or stdout."""
    if output_format == "json":
        content = json.dumps(manifests, indent=2)
    else:
        # Multi-document YAML
        docs = []
        for m in manifests:
            docs.append(yaml.dump(m, default_flow_style=False, sort_keys=False))
        content = "---\n" + "---\n".join(docs)

    if output_path:
        out_dir = Path(output_path)
        out_dir.mkdir(parents=True, exist_ok=True)

        if app_name:
            filename = f"{app_name}.{output_format}"
        else:
            filename = f"manifests.{output_format}"

        out_file = out_dir / filename
        out_file.write_text(content)
        print(f"Written: {out_file}", file=sys.stderr)
    else:
        print(content)


def cmd_generate(args: argparse.Namespace) -> int:
    """Handle generate command."""
    try:
        config = load_apps_yaml(args.file)
    except FileNotFoundError:
        print(f"Error: apps.yaml not found at {args.file}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    app = config.get_app(args.app)
    if not app:
        print(f"Error: App '{args.app}' not found in apps.yaml", file=sys.stderr)
        print(f"Available apps: {', '.join(a.name for a in config.apps)}", file=sys.stderr)
        return 1

    env = Environment(args.env)
    manifests = generate_all_manifests(app, env, config)

    output_manifests(
        manifests,
        args.format,
        args.output,
        app_name=app.name,
    )

    if args.verbose:
        print(f"Generated {len(manifests)} manifests for {app.name}", file=sys.stderr)

    return 0


def cmd_generate_all(args: argparse.Namespace) -> int:
    """Handle generate-all command."""
    try:
        config = load_apps_yaml(args.file)
    except FileNotFoundError:
        print(f"Error: apps.yaml not found at {args.file}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    env = Environment(args.env)
    apps = get_enabled_apps(env, args.file)

    if not apps:
        print(f"No enabled apps found for environment: {args.env}", file=sys.stderr)
        return 0

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    total_manifests = 0
    for app in apps:
        manifests = generate_all_manifests(app, env, config)
        output_manifests(
            manifests,
            args.format,
            args.output,
            app_name=app.name,
        )
        total_manifests += len(manifests)

    print(
        f"Generated {total_manifests} manifests for {len(apps)} apps",
        file=sys.stderr,
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Handle list command."""
    try:
        config = load_apps_yaml(args.file)
    except FileNotFoundError:
        print(f"Error: apps.yaml not found at {args.file}", file=sys.stderr)
        return 1
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.env:
        env = Environment(args.env)
        apps = get_enabled_apps(env, args.file)
    else:
        apps = config.apps

    if args.json:
        app_data = []
        for app in apps:
            app_data.append({
                "name": app.name,
                "path": app.path,
                "namespace": app.namespace,
                "enabled": app.enabled,
                "ingress_enabled": app.ingress.enabled,
                "ingress_path": app.ingress.path if app.ingress.enabled else None,
                "scaling_type": app.scaling.type.value,
            })
        print(json.dumps(app_data, indent=2))
    else:
        if not apps:
            print("No apps found")
            return 0

        # Table header
        print(f"{'NAME':<25} {'NAMESPACE':<15} {'PATH':<20} {'SCALING':<12} {'INGRESS':<10}")
        print("-" * 85)

        for app in apps:
            ingress = app.ingress.path if app.ingress.enabled else "-"
            print(
                f"{app.name:<25} "
                f"{app.namespace:<15} "
                f"{app.path:<20} "
                f"{app.scaling.type.value:<12} "
                f"{ingress:<10}"
            )

    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    """Handle validate command."""
    apps_path = Path(args.file)
    if not apps_path.exists():
        print(f"Error: apps.yaml not found at {args.file}", file=sys.stderr)
        return 1

    with open(apps_path) as f:
        data = yaml.safe_load(f)

    errors = validate_apps_yaml(data)
    if errors:
        print("Validation errors:", file=sys.stderr)
        for error in errors:
            print(f"  - {error}", file=sys.stderr)
        return 1

    print(f"✓ {args.file} is valid")

    # Also try to parse it
    try:
        config = load_apps_yaml(args.file, validate=False)
        print(f"  Found {len(config.apps)} apps")
        for app in config.apps:
            status = "enabled" if app.enabled else "disabled"
            print(f"    - {app.name} ({status})")
    except Exception as e:
        print(f"Warning: Schema valid but parsing failed: {e}", file=sys.stderr)

    return 0


def main(argv: Optional[List[str]] = None) -> int:
    """Main entry point."""
    parser = create_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help()
        return 0

    commands = {
        "generate": cmd_generate,
        "generate-all": cmd_generate_all,
        "list": cmd_list,
        "validate": cmd_validate,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
