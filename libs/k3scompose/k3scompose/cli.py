"""
CLI for k3scompose - Docker Compose to Kubernetes converter.

Commands:
    generate    Generate K8s manifests for a compose project
    generate-all Generate manifests for all enabled compose projects
    list        List compose projects from apps.yaml
    parse       Parse and display docker-compose.yaml
"""

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional

import yaml

from .generators import generate_all_manifests
from .parser import (
    get_enabled_compose_projects,
    load_compose_config,
    parse_compose_project,
    resolve_compose_project,
)
from .types import Environment


def create_parser() -> argparse.ArgumentParser:
    """Create the argument parser."""
    parser = argparse.ArgumentParser(
        prog="k3scompose",
        description="Convert Docker Compose to Kubernetes manifests",
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
        help="Generate K8s manifests for a compose project",
    )
    gen_parser.add_argument(
        "project",
        help="Project name to generate manifests for",
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
    gen_parser.add_argument(
        "--registry",
        help="Container registry prefix for built images",
    )

    # generate-all command
    gen_all_parser = subparsers.add_parser(
        "generate-all",
        help="Generate manifests for all enabled compose projects",
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
    gen_all_parser.add_argument(
        "--registry",
        help="Container registry prefix for built images",
    )

    # list command
    list_parser = subparsers.add_parser(
        "list",
        help="List compose projects from apps.yaml",
    )
    list_parser.add_argument(
        "-e", "--env",
        choices=["local", "dev", "gcp"],
        help="Filter by environment (show only enabled projects)",
    )
    list_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    # parse command
    parse_parser = subparsers.add_parser(
        "parse",
        help="Parse and display docker-compose.yaml",
    )
    parse_parser.add_argument(
        "path",
        help="Path to directory containing docker-compose.yaml",
    )
    parse_parser.add_argument(
        "--compose-file",
        default="docker-compose.yaml",
        help="Compose file name (default: docker-compose.yaml)",
    )
    parse_parser.add_argument(
        "--json",
        action="store_true",
        help="Output as JSON",
    )

    return parser


def output_manifests(
    manifests: list,
    output_format: str,
    output_path: Optional[str] = None,
    project_name: Optional[str] = None,
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

        if project_name:
            filename = f"{project_name}.{output_format}"
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
        configs = load_compose_config(args.file)
    except FileNotFoundError:
        print(f"Error: apps.yaml not found at {args.file}", file=sys.stderr)
        return 1

    # Find the project
    config = None
    for c in configs:
        if c.name == args.project:
            config = c
            break

    if not config:
        print(f"Error: Project '{args.project}' not found in apps.yaml", file=sys.stderr)
        print(f"Available projects: {', '.join(c.name for c in configs)}", file=sys.stderr)
        return 1

    # Parse the compose project
    try:
        base_path = Path(args.file).parent
        project = resolve_compose_project(config, str(base_path))
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    env = Environment(args.env)
    manifests = generate_all_manifests(project, config, env, args.registry)

    output_manifests(
        manifests,
        args.format,
        args.output,
        project_name=config.name,
    )

    if args.verbose:
        print(
            f"Generated {len(manifests)} manifests for {config.name} "
            f"({len(project.services)} services)",
            file=sys.stderr,
        )

    return 0


def cmd_generate_all(args: argparse.Namespace) -> int:
    """Handle generate-all command."""
    try:
        configs = load_compose_config(args.file)
    except FileNotFoundError:
        print(f"Error: apps.yaml not found at {args.file}", file=sys.stderr)
        return 1

    env = Environment(args.env)
    enabled = [c for c in configs if c.is_enabled(env)]

    if not enabled:
        print(f"No enabled compose projects for environment: {args.env}", file=sys.stderr)
        return 0

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    base_path = Path(args.file).parent
    total_manifests = 0

    for config in enabled:
        try:
            project = resolve_compose_project(config, str(base_path))
        except FileNotFoundError as e:
            print(f"Warning: Skipping {config.name}: {e}", file=sys.stderr)
            continue

        manifests = generate_all_manifests(project, config, env, args.registry)
        output_manifests(
            manifests,
            args.format,
            args.output,
            project_name=config.name,
        )
        total_manifests += len(manifests)

    print(
        f"Generated {total_manifests} manifests for {len(enabled)} projects",
        file=sys.stderr,
    )
    return 0


def cmd_list(args: argparse.Namespace) -> int:
    """Handle list command."""
    try:
        configs = load_compose_config(args.file)
    except FileNotFoundError:
        print(f"Error: apps.yaml not found at {args.file}", file=sys.stderr)
        return 1

    if args.env:
        env = Environment(args.env)
        configs = [c for c in configs if c.is_enabled(env)]

    if args.json:
        project_data = []
        for c in configs:
            project_data.append({
                "name": c.name,
                "path": c.path,
                "file": c.file,
                "namespace": c.namespace,
                "enabled": c.enabled,
            })
        print(json.dumps(project_data, indent=2))
    else:
        if not configs:
            print("No compose projects found")
            return 0

        # Table header
        print(f"{'NAME':<25} {'PATH':<30} {'NAMESPACE':<15} {'ENABLED':<10}")
        print("-" * 80)

        for c in configs:
            enabled = "yes" if c.enabled else "no"
            print(
                f"{c.name:<25} "
                f"{c.path:<30} "
                f"{c.namespace:<15} "
                f"{enabled:<10}"
            )

    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    """Handle parse command."""
    try:
        project = parse_compose_project(
            name=Path(args.path).name,
            path=args.path,
            filename=args.compose_file,
        )
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    if args.json:
        data = {
            "name": project.name,
            "path": project.path,
            "services": [],
            "volumes": list(project.volumes.keys()),
            "networks": project.networks,
        }
        for svc in project.services:
            svc_data = {
                "name": svc.name,
                "image": svc.image,
                "build": svc.build,
                "ports": [
                    {"host": p.host_port, "container": p.container_port}
                    for p in svc.ports
                ],
                "volumes": [
                    {"source": v.source, "target": v.target}
                    for v in svc.volumes
                ],
                "environment": svc.environment,
                "depends_on": svc.depends_on,
            }
            data["services"].append(svc_data)
        print(json.dumps(data, indent=2))
    else:
        print(f"Project: {project.name}")
        print(f"Path: {project.path}")
        print(f"Services: {len(project.services)}")
        print(f"Volumes: {len(project.volumes)}")
        print(f"Networks: {len(project.networks)}")
        print()

        for svc in project.services:
            print(f"  Service: {svc.name}")
            if svc.image:
                print(f"    Image: {svc.image}")
            if svc.build:
                print(f"    Build: {svc.build.get('context', '.')}")
            if svc.ports:
                ports_str = ", ".join(
                    f"{p.host_port or p.container_port}:{p.container_port}"
                    for p in svc.ports
                )
                print(f"    Ports: {ports_str}")
            if svc.volumes:
                print(f"    Volumes: {len(svc.volumes)}")
            if svc.environment:
                print(f"    Environment: {len(svc.environment)} vars")
            if svc.depends_on:
                print(f"    Depends on: {', '.join(svc.depends_on)}")
            print()

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
        "parse": cmd_parse,
    }

    handler = commands.get(args.command)
    if handler:
        return handler(args)

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
