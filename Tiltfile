# Tiltfile for K3s Platform - Dynamic Configuration (v2)
# ================================================================================
# This Tiltfile reads apps.yaml and uses CLI tools to generate K8s manifests.
# No manual editing needed when adding/removing apps!
#
# CLI Tools:
#   - k3sapp:     Generate manifests for traditional container apps
#   - k3sfn:      Generate manifests for serverless functions
#   - k3scompose: Generate manifests for Docker Compose projects
#
# Usage:
#   tilt up                         # Start development environment
#   tilt up -- --no-valkey          # Skip Valkey
#   tilt up -- --only fastapi       # Only run FastAPI
#   tilt up -- --exclude serverless # Exclude serverless apps
#
# Prerequisites:
#   - k3d cluster running (./providers/dev/setup.sh --no-tilt)
#   - kubectl configured for dev cluster
#   - uv installed for Python package management
#
# Configuration:
#   - Edit apps.yaml to add/remove services
#   - Everything is auto-configured from that file
#
# Docs: https://docs.tilt.dev/
# ================================================================================

load('ext://configmap', 'configmap_create')

# ============================================================================
# Configuration
# ============================================================================

# User-configurable options
config.define_bool("no-valkey", args=False, usage="Skip Valkey deployment")
config.define_string_list("only", args=False, usage="Only run specified apps")
config.define_string_list("exclude", args=False, usage="Exclude specified apps")
cfg = config.parse()

# ============================================================================
# Load apps.yaml Configuration
# ============================================================================

def load_apps_config():
    """Load and parse apps.yaml configuration"""
    apps_yaml = read_yaml('apps.yaml')
    return apps_yaml

apps_config = load_apps_config()

# ============================================================================
# Helper Functions
# ============================================================================

def is_app_enabled(name, section_enabled=True):
    """Check if an app should be enabled based on --only and --exclude flags"""
    only_list = cfg.get('only', [])
    exclude_list = cfg.get('exclude', [])

    if not section_enabled:
        return False

    if only_list and name not in only_list:
        return False

    if name in exclude_list:
        return False

    return True

def get_serverless_functions(app_path):
    """Discover serverless functions from a k3sfn app"""
    # Run k3sfn list to get functions
    result = local(
        'uv run python3 -m k3sfn.cli list %s --format json 2>/dev/null || echo "[]"' % app_path,
        quiet=True,
    )

    # Parse JSON output
    try:
        import json
        functions = decode_json(result)
        return functions if functions else []
    except:
        return []

# ============================================================================
# Registry Configuration
# ============================================================================

default_registry('registry.localhost:5111')

# ============================================================================
# Helm Charts (Infrastructure)
# ============================================================================

helm_apps = apps_config.get('helm', [])

for helm_app in helm_apps:
    name = helm_app.get('name', '')
    enabled = helm_app.get('enabled', True)

    # Check for valkey skip flag
    if name == 'valkey' and cfg.get('no-valkey'):
        enabled = False

    if not is_app_enabled(name, enabled):
        continue

    # Watch values file for changes
    values_file = helm_app.get('values', '')
    if values_file:
        watch_file('./' + values_file)

    # For Helm apps, we just track the resources (deployed by setup.sh)
    # Tilt will watch for changes and redeploy if needed
    if name == 'valkey':
        k8s_resource(
            'valkey-node',
            labels=['infra'],
            port_forwards=[
                port_forward(6379, 6379, name='Valkey'),
                port_forward(26379, 26379, name='Sentinel'),
            ],
        )

# ============================================================================
# Traditional Apps (FastAPI, etc.) - Uses k3sapp CLI
# ============================================================================

traditional_apps = apps_config.get('apps', [])

for app in traditional_apps:
    name = app.get('name', '')
    enabled = app.get('enabled', True)

    if not is_app_enabled(name, enabled):
        continue

    app_path = app.get('path', 'apps/' + name)
    namespace = app.get('namespace', 'apps')
    build_config = app.get('build', {})
    dockerfile_dev = build_config.get('dockerfile_dev', 'Dockerfile.dev')
    dev_config = app.get('dev', {})
    generated_dir = './k8s/generated/dev'

    # Generate manifests using k3sapp CLI
    local_resource(
        '%s-generate' % name,
        cmd='uv run --project libs/k3sapp k3sapp generate %s --env dev -o %s' % (name, generated_dir),
        deps=[
            './apps.yaml',
            './%s/' % app_path,
            './libs/k3sapp/k3sapp/',
        ],
        labels=['app'],
    )

    # Build with live update for dev mode
    live_update_rules = []
    for sync_rule in dev_config.get('sync', []):
        live_update_rules.append(
            sync('./%s/%s' % (app_path, sync_rule['src']), sync_rule['dest'])
        )

    docker_build(
        '%s-app' % name,
        context='./%s' % app_path,
        dockerfile='./%s/%s' % (app_path, dockerfile_dev),
        live_update=live_update_rules if dev_config.get('live_update', False) else [],
        only=[
            './%s/' % app_path,
        ],
    )

    # Apply generated Kubernetes manifests
    k8s_yaml('%s/%s.yaml' % (generated_dir, name))

    # Configure resource with port forwards
    port = dev_config.get('port', 8000)
    container_ports = app.get('container', {}).get('ports', [])
    if container_ports:
        port = container_ports[0].get('container_port', port)

    resource_deps = ['%s-generate' % name]

    # Add valkey dependency if valkey is enabled
    if not cfg.get('no-valkey'):
        for helm_app in helm_apps:
            if helm_app.get('name') == 'valkey' and helm_app.get('enabled', True):
                resource_deps.append('valkey-node')
                break

    k8s_resource(
        name,
        port_forwards=[
            port_forward(port, port, name=name.upper()),
        ],
        labels=['app'],
        resource_deps=resource_deps,
    )

# ============================================================================
# Serverless Functions (k3sfn) - Uses k3sfn CLI with apps.yaml integration
# ============================================================================

serverless_apps = apps_config.get('serverless', [])

for serverless_app in serverless_apps:
    name = serverless_app.get('name', '')
    enabled = serverless_app.get('enabled', True)

    if not is_app_enabled(name, enabled):
        continue

    app_path = serverless_app.get('path', 'apps/' + name)
    namespace = serverless_app.get('namespace', 'apps')
    dev_config = serverless_app.get('dev', {})
    port_base = dev_config.get('port_base', 8081)
    live_update_enabled = dev_config.get('live_update', True)

    generated_dir = './k8s/generated/dev/%s' % name

    # Generate manifests using k3sfn CLI with apps.yaml integration
    local_resource(
        '%s-generate' % name,
        cmd='uv run --project libs/k3sfn k3sfn generate --name %s --from-apps-yaml --env dev -o %s' % (name, generated_dir),
        deps=[
            './apps.yaml',
            './%s/functions/' % app_path,
            './libs/k3sfn/k3sfn/',
        ],
        labels=['serverless'],
    )

    # Build serverless image with live update
    live_update_rules = []
    if live_update_enabled:
        live_update_rules = [
            sync('./%s/functions/' % app_path, '/app/functions/'),
            sync('./libs/k3sfn/k3sfn/', '/app/libs/k3sfn/k3sfn/'),
        ]

    # Check if dev Dockerfile exists, otherwise use generated one
    dockerfile_dev = './%s/Dockerfile.dev' % app_path
    if not os.path.exists(dockerfile_dev):
        dockerfile_dev = '%s/Dockerfile' % generated_dir

    docker_build(
        'registry.localhost:5111/%s' % name,
        context='.',
        dockerfile=dockerfile_dev,
        live_update=live_update_rules,
        only=[
            './%s/functions/' % app_path,
            './%s/Dockerfile.dev' % app_path,
            './libs/k3sfn/',
        ],
    )

    # Apply serverless manifests
    k8s_yaml('%s/manifests.yaml' % generated_dir)

    # Create resources for known HTTP functions with port forwards
    # Port assignments are dynamic based on function discovery
    current_port = port_base

    # Read k3sfn.json if it exists to get function list
    k3sfn_json_path = '%s/k3sfn.json' % generated_dir
    functions_to_configure = []

    if os.path.exists(k3sfn_json_path):
        k3sfn_data = read_json(k3sfn_json_path)
        if k3sfn_data and 'functions' in k3sfn_data:
            functions_to_configure = k3sfn_data.get('functions', [])

    for func in functions_to_configure:
        func_name = func.get('name', '')
        trigger_type = func.get('trigger_type', '')
        resource_name = '%s-%s' % (name, func_name.replace('_', '-'))

        if trigger_type == 'http':
            # HTTP functions get port forwards
            k8s_resource(
                resource_name,
                new_name='fn-%s' % func_name.replace('_', '-'),
                port_forwards=[port_forward(current_port, 8080, name=func.get('path', '/'))],
                labels=['serverless'],
                resource_deps=['%s-generate' % name],
            )
            current_port += 1
        elif trigger_type == 'queue':
            # Queue workers don't need port forwards
            k8s_resource(
                resource_name,
                new_name='fn-%s' % func_name.replace('_', '-'),
                labels=['serverless-queue'],
                resource_deps=['%s-generate' % name],
            )
        # Schedule triggers are CronJobs, handled differently

# ============================================================================
# Development Helpers
# ============================================================================

# Test endpoints (manual trigger)
local_resource(
    'test-api',
    cmd='curl -s http://localhost:8000/health 2>/dev/null | jq . || echo "FastAPI not ready"',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['dev'],
)

local_resource(
    'test-serverless',
    cmd='curl -s "http://localhost:8081/api/hello?name=Tilt" 2>/dev/null | jq . || echo "Serverless not ready"',
    auto_init=False,
    trigger_mode=TRIGGER_MODE_MANUAL,
    labels=['dev'],
)

# Run serverless functions locally without containers (ultra-fast iteration)
for serverless_app in serverless_apps:
    if not serverless_app.get('enabled', True):
        continue
    name = serverless_app.get('name', '')
    app_path = serverless_app.get('path', 'apps/' + name)

    local_resource(
        'run-%s-local' % name,
        serve_cmd='uv run python3 -m k3sfn.cli run ./%s --port 8090' % app_path,
        auto_init=False,
        labels=['dev-local'],
    )

# ============================================================================
# UI Configuration
# ============================================================================

update_settings(
    max_parallel_updates=3,
    k8s_upsert_timeout_secs=120,
)

# Watch apps.yaml for changes - restart Tilt when config changes
watch_file('apps.yaml')
