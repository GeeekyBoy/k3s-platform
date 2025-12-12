# Implementation Gaps Plan

This document provides detailed implementation plans for all missing features identified in STATUS.md.

---

## Table of Contents

1. [KEDA Queue Scaling (keda-queue)](#1-keda-queue-scaling-keda-queue)
2. [KEDA Cron Scaling (keda-cron)](#2-keda-cron-scaling-keda-cron)
3. [Ephemeral Storage](#3-ephemeral-storage)
4. [Network Policy Egress (allow_to)](#4-network-policy-egress-allow_to)
5. [ServiceAccount Creation](#5-serviceaccount-creation)
6. [Gateway Rate Limiting](#6-gateway-rate-limiting)
7. [Gateway CORS for HAProxy](#7-gateway-cors-for-haproxy)
8. [Gateway Authentication](#8-gateway-authentication)
9. [Secrets and Environment Variables](#9-secrets-and-environment-variables)

---

## 1. KEDA Queue Scaling (keda-queue)

### Overview

Enable autoscaling based on Redis/Valkey queue length using KEDA ScaledObject with Redis Lists scaler.

**References:**
- [KEDA Redis Lists Scaler](https://keda.sh/docs/2.18/scalers/redis-lists/)
- [KodeKloud KEDA Redis Scaling Notes](https://notes.kodekloud.com/docs/Kubernetes-Autoscaling/Kubernetes-Event-Driven-Autoscaling-KEDA/KEDA-Scaling-With-Redis-List)

### Schema Fields (already defined)

```yaml
scaling:
  type: keda-queue
  queue_name: "job-queue"        # Redis list key
  queue_length: 5                # Target queue length per pod
  min_instances: 0
  max_instances: 10
```

### Implementation Plan

#### Step 1: Add TriggerAuthentication Generator

**File:** `libs/k3sapp/k3sapp/generators.py`

Add new function to generate TriggerAuthentication for Redis:

```python
def generate_trigger_authentication(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """Generate KEDA TriggerAuthentication for queue scaling."""
    scaling = app.get_effective_scaling(env)
    if scaling.type != ScalingType.KEDA_QUEUE:
        return None

    name = _to_k8s_name(app.name)

    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "TriggerAuthentication",
        "metadata": {
            "name": f"{name}-redis-auth",
            "namespace": app.namespace,
        },
        "spec": {
            "secretTargetRef": [
                {
                    "parameter": "password",
                    "name": "valkey-secret",  # Platform-level secret
                    "key": "password",
                },
            ],
        },
    }
```

#### Step 2: Add ScaledObject Generator for Queue

**File:** `libs/k3sapp/k3sapp/generators.py`

```python
def generate_keda_scaledobject_queue(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """Generate KEDA ScaledObject for Redis queue scaling."""
    scaling = app.get_effective_scaling(env)
    if scaling.type != ScalingType.KEDA_QUEUE:
        return None

    if not scaling.queue_name:
        return None

    name = _to_k8s_name(app.name)

    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": f"{name}-queue",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "scaleTargetRef": {
                "name": name,
                "kind": "Deployment",
            },
            "pollingInterval": 15,
            "cooldownPeriod": scaling.cooldown_period,
            "minReplicaCount": scaling.min_instances,
            "maxReplicaCount": scaling.max_instances,
            "triggers": [
                {
                    "type": "redis",
                    "metadata": {
                        "address": "valkey-master.valkey.svc.cluster.local:6379",
                        "listName": scaling.queue_name,
                        "listLength": str(scaling.queue_length),
                        "enableTLS": "false",
                        "databaseIndex": "0",
                    },
                    "authenticationRef": {
                        "name": f"{name}-redis-auth",
                    },
                },
            ],
        },
    }
```

#### Step 3: Update generate_all_manifests

Add to `generate_all_manifests()`:

```python
# Queue scaling
if scaling.type == ScalingType.KEDA_QUEUE:
    trigger_auth = generate_trigger_authentication(app, env)
    if trigger_auth:
        manifests.append(trigger_auth)

    scaledobject = generate_keda_scaledobject_queue(app, env)
    if scaledobject:
        manifests.append(scaledobject)
```

### Environment Considerations

| Environment | Redis/Valkey Address | Notes |
|-------------|---------------------|-------|
| local | valkey-master.valkey.svc.cluster.local:6379 | Deployed via Helm in k3d |
| dev | valkey-master.valkey.svc.cluster.local:6379 | Same as local |
| gcp | valkey-master.valkey.svc.cluster.local:6379 | Or Memorystore Redis |

---

## 2. KEDA Cron Scaling (keda-cron)

### Overview

Enable time-based autoscaling using KEDA Cron scaler for predictable traffic patterns.

**References:**
- [KEDA Cron Scaler](https://keda.sh/docs/2.18/scalers/cron/)
- [KEDA Cron Scaling Guide](https://medium.com/@Ibraheemcisse/kubernetes-autoscaling-with-keda-cron-trigger-a-complete-step-by-step-guide-8bc3b86011b3)

### Schema Updates Required

Add to `schemas/apps-schema.json` under scaling:

```json
"cron_schedules": {
  "type": "array",
  "items": {
    "type": "object",
    "required": ["timezone", "start", "end", "replicas"],
    "properties": {
      "timezone": { "type": "string" },
      "start": { "type": "string", "description": "Cron expression for start" },
      "end": { "type": "string", "description": "Cron expression for end" },
      "replicas": { "type": "integer", "minimum": 1 }
    }
  }
}
```

### Type Updates

**File:** `libs/k3sapp/k3sapp/types.py`

```python
@dataclass
class CronSchedule:
    """Cron schedule for time-based scaling."""
    timezone: str = "UTC"
    start: str = "0 8 * * *"   # 8 AM
    end: str = "0 18 * * *"    # 6 PM
    replicas: int = 5

    @classmethod
    def from_dict(cls, data: Dict) -> "CronSchedule":
        return cls(
            timezone=data.get("timezone", "UTC"),
            start=data["start"],
            end=data["end"],
            replicas=data["replicas"],
        )
```

Add to `ScalingConfig`:

```python
cron_schedules: List[CronSchedule] = field(default_factory=list)
```

### Implementation Plan

#### Generator Function

**File:** `libs/k3sapp/k3sapp/generators.py`

```python
def generate_keda_scaledobject_cron(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """Generate KEDA ScaledObject for cron-based scaling."""
    scaling = app.get_effective_scaling(env)
    if scaling.type != ScalingType.KEDA_CRON:
        return None

    if not scaling.cron_schedules:
        return None

    name = _to_k8s_name(app.name)

    triggers = []
    for i, schedule in enumerate(scaling.cron_schedules):
        triggers.append({
            "type": "cron",
            "metadata": {
                "timezone": schedule.timezone,
                "start": schedule.start,
                "end": schedule.end,
                "desiredReplicas": str(schedule.replicas),
            },
        })

    return {
        "apiVersion": "keda.sh/v1alpha1",
        "kind": "ScaledObject",
        "metadata": {
            "name": f"{name}-cron",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "scaleTargetRef": {
                "name": name,
                "kind": "Deployment",
            },
            "cooldownPeriod": scaling.cooldown_period,
            "minReplicaCount": scaling.min_instances,
            "maxReplicaCount": scaling.max_instances,
            "triggers": triggers,
        },
    }
```

### Example Usage in apps.yaml

```yaml
apps:
  - name: batch-processor
    path: apps/batch-processor
    scaling:
      type: keda-cron
      min_instances: 0
      max_instances: 20
      cron_schedules:
        - timezone: "America/New_York"
          start: "0 8 * * 1-5"   # 8 AM weekdays
          end: "0 18 * * 1-5"   # 6 PM weekdays
          replicas: 10
        - timezone: "America/New_York"
          start: "0 9 * * 0,6"  # 9 AM weekends
          end: "0 17 * * 0,6"  # 5 PM weekends
          replicas: 3
```

---

## 3. Ephemeral Storage

### Overview

Configure ephemeral storage requests and limits for container local storage.

### Schema (already defined)

```yaml
resources:
  ephemeral_storage: "10Gi"
```

### Implementation Plan

#### Update generate_deployment

**File:** `libs/k3sapp/k3sapp/generators.py`

In `generate_deployment()`:

```python
# Container resources
container_resources = {
    "requests": {
        "memory": resources.memory,
        "cpu": resources.cpu,
    },
    "limits": {
        "memory": resources.memory_limit,
    },
}

# Ephemeral storage
if resources.ephemeral_storage:
    container_resources["requests"]["ephemeral-storage"] = resources.ephemeral_storage
    container_resources["limits"]["ephemeral-storage"] = resources.ephemeral_storage
```

---

## 4. Network Policy Egress (allow_to)

### Overview

Implement egress NetworkPolicy rules to restrict outbound traffic from pods.

**References:**
- [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [Red Hat Guide to Egress Policies](https://www.redhat.com/en/blog/guide-to-kubernetes-egress-network-policies)
- [GKE Network Policy Guide](https://cloud.google.com/kubernetes-engine/docs/tutorials/network-policy)

### Schema (already defined)

```yaml
security:
  network_policy:
    enabled: true
    allow_to:
      - namespace: "valkey"
        pod_labels:
          app: valkey
      - cidr: "10.0.0.0/8"
```

### Implementation Plan

#### Update generate_network_policy

**File:** `libs/k3sapp/k3sapp/generators.py`

Extend `generate_network_policy()` to include egress rules:

```python
def generate_network_policy(
    app: AppConfig,
    env: Environment,
    config: AppsYamlConfig,
) -> Optional[Dict[str, Any]]:
    """Generate Kubernetes NetworkPolicy manifest with ingress and egress."""
    if not app.security.network_policy.enabled:
        return None

    name = _to_k8s_name(app.name)
    primary_port = app.get_primary_port()

    # ... existing ingress_rules code ...

    # Egress rules
    egress_rules = []
    policy_types = ["Ingress"]

    # Always allow DNS (kube-dns)
    egress_rules.append({
        "to": [
            {
                "namespaceSelector": {},
                "podSelector": {
                    "matchLabels": {
                        "k8s-app": "kube-dns",
                    },
                },
            },
        ],
        "ports": [
            {"protocol": "UDP", "port": 53},
            {"protocol": "TCP", "port": 53},
        ],
    })

    # Custom allow_to rules
    if app.security.network_policy.allow_to:
        policy_types.append("Egress")

        for rule in app.security.network_policy.allow_to:
            to_spec: Dict[str, Any] = {}

            if rule.namespace:
                to_spec["namespaceSelector"] = {
                    "matchLabels": {
                        "kubernetes.io/metadata.name": rule.namespace,
                    },
                }
            if rule.pod_labels:
                to_spec["podSelector"] = {"matchLabels": rule.pod_labels}
            if rule.cidr:
                to_spec["ipBlock"] = {"cidr": rule.cidr}

            if to_spec:
                egress_rules.append({
                    "to": [to_spec],
                })

    network_policy = {
        "apiVersion": "networking.k8s.io/v1",
        "kind": "NetworkPolicy",
        "metadata": {
            "name": f"{name}-policy",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "podSelector": {
                "matchLabels": {
                    "app": name,
                },
            },
            "policyTypes": policy_types,
            "ingress": ingress_rules,
        },
    }

    if "Egress" in policy_types:
        network_policy["spec"]["egress"] = egress_rules

    return network_policy
```

### Important Considerations

1. **DNS Access**: Always allow DNS to prevent breaking service discovery
2. **CIDR Limitations**: External IPs must be specified as CIDR blocks
3. **FQDN Support**: Native K8s doesn't support FQDN; consider Calico for this

---

## 5. ServiceAccount Creation

### Overview

Automatically create ServiceAccounts with optional GCP Workload Identity annotations.

**References:**
- [Kubernetes Service Accounts](https://kubernetes.io/docs/concepts/security/service-accounts/)
- [GCP Workload Identity](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
- [RBAC Guide](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)

### Schema (already defined)

```yaml
security:
  service_account: "my-app-sa"
  create_service_account: true
  service_account_annotations:
    iam.gke.io/gcp-service-account: "my-app@project.iam.gserviceaccount.com"
```

### Implementation Plan

#### Add generate_service_account Function

**File:** `libs/k3sapp/k3sapp/generators.py`

```python
def generate_service_account(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """Generate Kubernetes ServiceAccount manifest."""
    if not app.security.create_service_account:
        return None

    if not app.security.service_account:
        return None

    sa = {
        "apiVersion": "v1",
        "kind": "ServiceAccount",
        "metadata": {
            "name": app.security.service_account,
            "namespace": app.namespace,
            "labels": {
                "k3sapp.io/app": app.name,
            },
        },
    }

    # Add annotations (e.g., for GCP Workload Identity)
    if app.security.service_account_annotations:
        sa["metadata"]["annotations"] = app.security.service_account_annotations

    return sa
```

#### Update generate_all_manifests

```python
# ServiceAccount
if app.security.create_service_account:
    sa = generate_service_account(app, env)
    if sa:
        manifests.insert(0, sa)  # Create SA before Deployment
```

### GCP Workload Identity Example

```yaml
apps:
  - name: gcs-uploader
    path: apps/gcs-uploader
    security:
      service_account: gcs-uploader-sa
      create_service_account: true
      service_account_annotations:
        iam.gke.io/gcp-service-account: "gcs-uploader@my-project.iam.gserviceaccount.com"
```

### Environment Considerations

| Environment | Workload Identity | Notes |
|-------------|------------------|-------|
| local | No | Standard K8s SA only |
| dev | No | Standard K8s SA only |
| gcp | Yes | Requires GKE + Workload Identity enabled |

---

## 6. Gateway Rate Limiting

### Overview

Implement rate limiting for gateway routes using HAProxy and Traefik.

**References:**
- [HAProxy Rate Limiting](https://www.haproxy.com/blog/rate-limiting-with-the-haproxy-kubernetes-ingress-controller)
- [Traefik Rate Limiting](https://traefik.io/blog/rate-limiting-on-kubernetes-applications)
- [HAProxy Ingress Annotations](https://haproxy-ingress.github.io/docs/configuration/keys/)

### Schema (already defined in k3sgateway types)

```yaml
gateway:
  rate_limit:
    enabled: true
    requests_per_second: 100
    burst: 200
  routes:
    - path: /api
      service: api-service.apps:80
      rate_limit:
        requests_per_second: 50
```

### Implementation Plan

#### HAProxy Rate Limiting

**File:** `libs/k3sgateway/k3sgateway/generators.py`

Update `generate_haproxy_ingress()`:

```python
def generate_haproxy_ingress(
    route: GatewayRoute,
    gateway_config: GatewayConfig,
    domain: Optional[str] = None,
    tls_enabled: bool = False,
    tls_secret: Optional[str] = None,
) -> Dict[str, Any]:
    # ... existing code ...

    # Rate limiting annotations
    if route.rate_limit:
        annotations["haproxy.org/rate-limit-requests"] = str(route.rate_limit.requests_per_second)
        annotations["haproxy.org/rate-limit-period"] = "1s"
        annotations["haproxy.org/rate-limit-status-code"] = "429"
    elif gateway_config.rate_limit.enabled:
        annotations["haproxy.org/rate-limit-requests"] = str(gateway_config.rate_limit.requests_per_second)
        annotations["haproxy.org/rate-limit-period"] = "1s"
        annotations["haproxy.org/rate-limit-status-code"] = "429"

    # ... rest of function ...
```

#### Traefik Rate Limiting

**File:** `libs/k3sgateway/k3sgateway/generators.py`

Add rate limiting middleware generator:

```python
def generate_traefik_ratelimit_middleware(
    route: GatewayRoute,
    gateway_config: GatewayConfig,
    namespace: str = "apps",
) -> Optional[Dict[str, Any]]:
    """Generate Traefik RateLimit Middleware."""
    rate_limit = route.rate_limit or (
        gateway_config.rate_limit if gateway_config.rate_limit.enabled else None
    )

    if not rate_limit:
        return None

    route_name = route.path.strip("/").replace("/", "-") or "root"

    return {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "Middleware",
        "metadata": {
            "name": f"gateway-{route_name}-ratelimit",
            "namespace": namespace,
            "labels": {
                "k3sgateway.io/route": route_name,
                "k3sgateway.io/component": "ratelimit",
            },
        },
        "spec": {
            "rateLimit": {
                "average": rate_limit.requests_per_second,
                "burst": rate_limit.burst or rate_limit.requests_per_second * 2,
            },
        },
    }
```

Update `generate_traefik_ingressroute()` to include rate limit middleware in route middlewares list.

---

## 7. Gateway CORS for HAProxy

### Overview

Implement CORS headers for HAProxy Ingress using annotations.

**References:**
- [HAProxy CORS Configuration](https://haproxy-ingress.github.io/docs/configuration/keys/)
- [HAProxy Response Headers](https://github.com/haproxytech/kubernetes-ingress/blob/master/documentation/annotations.md)

### Implementation Plan

#### Update generate_haproxy_ingress

**File:** `libs/k3sgateway/k3sgateway/generators.py`

```python
def generate_haproxy_ingress(
    route: GatewayRoute,
    gateway_config: GatewayConfig,
    # ... other params ...
) -> Dict[str, Any]:
    # ... existing code ...

    # CORS configuration
    if gateway_config.cors.enabled:
        cors = gateway_config.cors

        # Enable CORS
        annotations["ingress.kubernetes.io/cors-enabled"] = "true"

        # Allow origins
        if cors.allow_origins == ["*"]:
            annotations["ingress.kubernetes.io/cors-allow-origin"] = "*"
        else:
            # HAProxy uses regex for multiple origins
            origins_regex = "|".join(
                f"({re.escape(origin)})" for origin in cors.allow_origins
            )
            annotations["ingress.kubernetes.io/cors-allow-origin"] = origins_regex

        # Allow methods
        annotations["ingress.kubernetes.io/cors-allow-methods"] = ",".join(cors.allow_methods)

        # Allow headers
        annotations["ingress.kubernetes.io/cors-allow-headers"] = ",".join(cors.allow_headers)

        # Max age
        if cors.max_age:
            annotations["ingress.kubernetes.io/cors-max-age"] = str(cors.max_age)

    # ... rest of function ...
```

---

## 8. Gateway Authentication

### Overview

Add authentication support to gateway routes (basic auth, API keys, OAuth).

### Schema Updates Required

```yaml
gateway:
  routes:
    - path: /api
      service: api-service.apps:80
      auth:
        type: basic  # or "api-key", "oauth2"
        secret: "api-basic-auth"  # K8s secret name
```

### Implementation Plan

#### HAProxy Basic Auth

**File:** `libs/k3sgateway/k3sgateway/generators.py`

```python
def generate_haproxy_ingress(
    route: GatewayRoute,
    # ... other params ...
) -> Dict[str, Any]:
    # ... existing code ...

    # Authentication
    if route.auth:
        if route.auth.type == "basic":
            annotations["haproxy.org/auth-type"] = "basic-auth"
            annotations["haproxy.org/auth-secret"] = route.auth.secret
        elif route.auth.type == "api-key":
            # API key via custom config-backend
            config_backend += f"http-request deny unless {{ req.hdr(X-API-Key) -m str -f /etc/haproxy/api-keys.list }}\\n"
```

#### Traefik Basic Auth

```python
def generate_traefik_basicauth_middleware(
    route: GatewayRoute,
    namespace: str = "apps",
) -> Optional[Dict[str, Any]]:
    """Generate Traefik BasicAuth Middleware."""
    if not route.auth or route.auth.type != "basic":
        return None

    route_name = route.path.strip("/").replace("/", "-") or "root"

    return {
        "apiVersion": "traefik.io/v1alpha1",
        "kind": "Middleware",
        "metadata": {
            "name": f"gateway-{route_name}-auth",
            "namespace": namespace,
        },
        "spec": {
            "basicAuth": {
                "secret": route.auth.secret,
            },
        },
    }
```

---

## 9. Secrets and Environment Variables

### Overview

Implement a unified schema for environment variables that handles both:
- **Secrets**: Sensitive values fetched at runtime from external providers (GCP Secret Manager, etc.)
- **Environment Variables**: Non-sensitive values substituted at compile time from .env files or shell environment

**References:**
- [External Secrets Operator (ESO)](https://external-secrets.io/latest/)
- [ESO GCP Secret Manager Provider](https://external-secrets.io/latest/provider/google-secrets-manager/)
- [GCP Workload Identity Federation](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
- [Kubernetes Secrets Best Practices](https://kubernetes.io/docs/concepts/security/secrets-good-practices/)

### Architecture Overview

```
apps.yaml
    |
    v
+-------------+     +-------------------------+
|  k3sapp     |---->| Deployment              |
|  generate   |     |   env:                  |
+-------------+     |     LOG_LEVEL: "info"   |
    |               |   envFrom:              |
    |               |     - secretRef:        |
    |               |         name: app-secrets|
    v               +-------------------------+
+-------------------------+
| ExternalSecret          |
|   secretStoreRef: gcp   |
|   data:                 |
|     - DATABASE_PASSWORD |
|     - API_KEY           |
+-------------------------+
    |
    v (ESO controller syncs)
+-------------------------+
| Secret: app-secrets     |
|   DATABASE_PASSWORD: ** |
|   API_KEY: **           |
+-------------------------+
```

### How Runtime Secret Fetching Works

1. **External Secrets Operator (ESO)** runs as a controller in the cluster
2. **ClusterSecretStore** defines connection to secret provider (GCP Secret Manager)
3. **ExternalSecret** CRD specifies which secrets to fetch and maps them to K8s Secrets
4. ESO automatically syncs secrets based on `refreshInterval`
5. Pods reference the synced K8s Secret normally via `envFrom` or volume mounts

### Proposed Unified Schema

```yaml
apps:
  - name: my-app
    environment:
      # Type 1: Literal value (compile-time, directly in Deployment)
      LOG_LEVEL: "info"
      APP_NAME: "my-app"

      # Type 2: Environment variable reference (compile-time substitution)
      DATABASE_HOST: "${DB_HOST}"
      API_ENDPOINT: "${API_URL:-https://default.api.com}"

      # Type 3: Secret reference (runtime fetch via ESO)
      DATABASE_PASSWORD:
        secret: "projects/my-project/secrets/db-password"
        provider: gcp  # defaults to gcp, extensible later
      API_KEY:
        secret: "api-key-name"
        version: "latest"  # optional, defaults to latest
```

### Schema Updates Required

**File:** `schemas/apps-schema.json`

Update the environment property to support both string and object values:

```json
"environment": {
  "type": "object",
  "description": "Environment variables. String values are literal or ${VAR} references. Object values are secret references.",
  "additionalProperties": {
    "oneOf": [
      {
        "type": "string",
        "description": "Literal value or ${VAR} reference for compile-time substitution"
      },
      {
        "type": "object",
        "description": "Secret reference for runtime fetching via External Secrets Operator",
        "required": ["secret"],
        "additionalProperties": false,
        "properties": {
          "secret": {
            "type": "string",
            "description": "Secret name/path in the provider (e.g., 'db-password' or 'projects/my-proj/secrets/db-password')"
          },
          "provider": {
            "type": "string",
            "enum": ["gcp", "aws", "vault", "azure"],
            "default": "gcp",
            "description": "Secret provider (defaults to gcp)"
          },
          "version": {
            "type": "string",
            "default": "latest",
            "description": "Secret version (defaults to 'latest')"
          },
          "key": {
            "type": "string",
            "description": "Key within secret if it contains multiple values (JSON)"
          }
        }
      }
    ]
  }
}
```

### Type Updates

**File:** `libs/k3sapp/k3sapp/types.py`

```python
@dataclass
class SecretRef:
    """Reference to an external secret."""
    secret: str  # Secret name/path in provider
    provider: str = "gcp"  # gcp, aws, vault, azure
    version: str = "latest"
    key: Optional[str] = None  # For multi-value secrets

    @classmethod
    def from_dict(cls, data: Dict) -> "SecretRef":
        return cls(
            secret=data["secret"],
            provider=data.get("provider", "gcp"),
            version=data.get("version", "latest"),
            key=data.get("key"),
        )


@dataclass
class EnvironmentValue:
    """Environment variable value - either literal string or secret reference."""
    value: Optional[str] = None  # Literal or ${VAR} reference
    secret_ref: Optional[SecretRef] = None  # Secret reference

    @classmethod
    def from_value(cls, data: Any) -> "EnvironmentValue":
        if isinstance(data, str):
            return cls(value=data)
        elif isinstance(data, dict) and "secret" in data:
            return cls(secret_ref=SecretRef.from_dict(data))
        else:
            raise ValueError(f"Invalid environment value: {data}")

    def is_secret(self) -> bool:
        return self.secret_ref is not None
```

Update `AppConfig`:

```python
@dataclass
class AppConfig:
    # Change environment type
    environment: Dict[str, EnvironmentValue] = field(default_factory=dict)

    # ... existing fields ...

    def get_literal_env_vars(self, env: Environment) -> Dict[str, str]:
        """Get non-secret environment variables for Deployment."""
        result = {}
        for key, val in self.environment.items():
            if not val.is_secret() and val.value is not None:
                result[key] = self._substitute_env_var(val.value)
        # Apply env override
        override = self.get_env_override(env)
        if override:
            for key, val in override.environment.items():
                if not val.is_secret() and val.value is not None:
                    result[key] = self._substitute_env_var(val.value)
        return result

    def get_secret_refs(self) -> Dict[str, SecretRef]:
        """Get secret references for ExternalSecret generation."""
        result = {}
        for key, val in self.environment.items():
            if val.is_secret() and val.secret_ref:
                result[key] = val.secret_ref
        return result

    def _substitute_env_var(self, value: str) -> str:
        """Substitute ${VAR} and ${VAR:-default} patterns."""
        import os
        import re

        def replace(match):
            var_name = match.group(1)
            default = match.group(3) if match.group(3) else None
            return os.environ.get(var_name, default or "")

        pattern = r'\$\{([A-Z_][A-Z0-9_]*)(:-(.*?))?\}'
        return re.sub(pattern, replace, value)
```

### Generator Functions

**File:** `libs/k3sapp/k3sapp/generators.py`

#### Generate ClusterSecretStore (platform-level, once per provider)

```python
def generate_cluster_secret_store_gcp(
    project_id: str,
    cluster_name: str,
    cluster_location: str,
) -> Dict[str, Any]:
    """Generate ClusterSecretStore for GCP Secret Manager."""
    return {
        "apiVersion": "external-secrets.io/v1beta1",
        "kind": "ClusterSecretStore",
        "metadata": {
            "name": "gcp-secret-manager",
            "labels": {
                "k3sapp.io/component": "secrets",
            },
        },
        "spec": {
            "provider": {
                "gcpsm": {
                    "projectID": project_id,
                    "auth": {
                        "workloadIdentity": {
                            "clusterLocation": cluster_location,
                            "clusterName": cluster_name,
                            "serviceAccountRef": {
                                "name": "external-secrets-sa",
                                "namespace": "external-secrets",
                            },
                        },
                    },
                },
            },
        },
    }
```

#### Generate ExternalSecret (per-app)

```python
def generate_external_secret(
    app: AppConfig,
    env: Environment,
) -> Optional[Dict[str, Any]]:
    """Generate ExternalSecret for apps with secret references."""
    secret_refs = app.get_secret_refs()
    if not secret_refs:
        return None

    name = _to_k8s_name(app.name)

    # Group secrets by provider
    gcp_secrets = {k: v for k, v in secret_refs.items() if v.provider == "gcp"}

    if not gcp_secrets:
        return None

    data = []
    for env_key, ref in gcp_secrets.items():
        entry = {
            "secretKey": env_key,
            "remoteRef": {
                "key": ref.secret,
            },
        }
        if ref.version != "latest":
            entry["remoteRef"]["version"] = ref.version
        if ref.key:
            entry["remoteRef"]["property"] = ref.key
        data.append(entry)

    return {
        "apiVersion": "external-secrets.io/v1beta1",
        "kind": "ExternalSecret",
        "metadata": {
            "name": f"{name}-secrets",
            "namespace": app.namespace,
            "labels": {
                "app": name,
                "k3sapp.io/app": app.name,
            },
        },
        "spec": {
            "refreshInterval": "1h",
            "secretStoreRef": {
                "kind": "ClusterSecretStore",
                "name": "gcp-secret-manager",
            },
            "target": {
                "name": f"{name}-secrets",
                "creationPolicy": "Owner",
            },
            "data": data,
        },
    }
```

#### Update generate_deployment

```python
def generate_deployment(
    app: AppConfig,
    env: Environment,
    image: str,
    config: AppsYamlConfig,
) -> Dict[str, Any]:
    # ... existing code ...

    # Environment variables (literal values only)
    env_vars = []
    for key, value in app.get_literal_env_vars(env).items():
        env_vars.append({"name": key, "value": value})

    if env_vars:
        container["env"] = env_vars

    # envFrom for secrets
    env_from = _build_env_from(app)

    # Add secret reference if app has secrets
    if app.get_secret_refs():
        name = _to_k8s_name(app.name)
        env_from.append({
            "secretRef": {
                "name": f"{name}-secrets",
            }
        })

    if env_from:
        container["envFrom"] = env_from

    # ... rest of function ...
```

#### Update generate_all_manifests

```python
def generate_all_manifests(
    app: AppConfig,
    env: Environment,
    config: AppsYamlConfig,
) -> List[Dict[str, Any]]:
    # ... existing code ...

    # External secrets (before Deployment)
    external_secret = generate_external_secret(app, env)
    if external_secret:
        manifests.insert(0, external_secret)

    # ... rest of function ...
```

### Platform Prerequisites

#### 1. Install External Secrets Operator

**File:** `platform/deploy.sh`

Add ESO installation:

```bash
# Install External Secrets Operator
echo "Installing External Secrets Operator..."
helm repo add external-secrets https://charts.external-secrets.io
helm repo update

helm upgrade --install external-secrets external-secrets/external-secrets \
    --namespace external-secrets \
    --create-namespace \
    --set installCRDs=true \
    --wait
```

#### 2. Create ClusterSecretStore for GCP

**File:** `platform/external-secrets/cluster-secret-store-gcp.yaml`

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ClusterSecretStore
metadata:
  name: gcp-secret-manager
spec:
  provider:
    gcpsm:
      projectID: ${GCP_PROJECT_ID}
      auth:
        workloadIdentity:
          clusterLocation: ${GCP_REGION}
          clusterName: ${CLUSTER_NAME}
          serviceAccountRef:
            name: external-secrets-sa
            namespace: external-secrets
```

#### 3. GCP Workload Identity Setup

```bash
# Create GCP service account for ESO
gcloud iam service-accounts create external-secrets-sa \
    --display-name="External Secrets Operator"

# Grant access to Secret Manager
gcloud projects add-iam-policy-binding ${PROJECT_ID} \
    --member="serviceAccount:external-secrets-sa@${PROJECT_ID}.iam.gserviceaccount.com" \
    --role="roles/secretmanager.secretAccessor"

# Bind K8s SA to GCP SA (Workload Identity)
gcloud iam service-accounts add-iam-policy-binding external-secrets-sa@${PROJECT_ID}.iam.gserviceaccount.com \
    --role="roles/iam.workloadIdentityUser" \
    --member="serviceAccount:${PROJECT_ID}.svc.id.goog[external-secrets/external-secrets-sa]"
```

### Environment Considerations

| Environment | Secret Provider | Authentication |
|-------------|-----------------|----------------|
| local | None (skip ExternalSecret) | Use .env files directly |
| dev | None or GCP | Optional, .env fallback |
| gcp | GCP Secret Manager | Workload Identity Federation |

### Example Usage

```yaml
apps:
  - name: api-server
    path: apps/api-server
    environment:
      # Literal values
      LOG_LEVEL: "info"
      APP_ENV: "production"

      # Compile-time substitution from .env or shell
      DATABASE_HOST: "${DB_HOST:-localhost}"
      REDIS_URL: "${REDIS_URL}"

      # Runtime secrets from GCP Secret Manager
      DATABASE_PASSWORD:
        secret: "api-server-db-password"
        provider: gcp
      JWT_SECRET:
        secret: "api-server-jwt-secret"
        provider: gcp
        version: "2"  # Specific version
      STRIPE_API_KEY:
        secret: "stripe-credentials"
        provider: gcp
        key: "api_key"  # Extract specific key from JSON secret
```

### Future Provider Support

The `provider` field allows future expansion:

| Provider | Value | Status |
|----------|-------|--------|
| GCP Secret Manager | `gcp` | Planned |
| AWS Secrets Manager | `aws` | Future |
| HashiCorp Vault | `vault` | Future |
| Azure Key Vault | `azure` | Future |

Each provider would need:
1. ClusterSecretStore configuration in `platform/`
2. Authentication setup (IAM, Workload Identity, etc.)

---

## Implementation Priority

| Priority | Feature | Complexity | Impact |
|----------|---------|------------|--------|
| 1 | ServiceAccount Creation | Low | High (GCP WI) |
| 2 | Ephemeral Storage | Low | Medium |
| 3 | Network Policy Egress | Medium | High (Security) |
| 4 | Gateway Rate Limiting | Medium | High |
| 5 | KEDA Queue Scaling | Medium | Medium |
| 6 | Gateway CORS HAProxy | Low | Medium |
| 7 | KEDA Cron Scaling | Medium | Medium |
| 8 | Secrets & Env Variables | High | High (Security) |
| 9 | Gateway Authentication | High | Medium |

---

## Testing Strategy

### Unit Tests

Each new generator function should have unit tests in `libs/k3sapp/tests/test_generators.py`:

```python
def test_generate_service_account():
    app = create_test_app(
        security={"service_account": "my-sa", "create_service_account": True}
    )
    sa = generate_service_account(app, Environment.LOCAL)
    assert sa["kind"] == "ServiceAccount"
    assert sa["metadata"]["name"] == "my-sa"

def test_generate_keda_scaledobject_queue():
    app = create_test_app(
        scaling={"type": "keda-queue", "queue_name": "jobs", "queue_length": 5}
    )
    so = generate_keda_scaledobject_queue(app, Environment.GCP)
    assert so["kind"] == "ScaledObject"
    assert so["spec"]["triggers"][0]["type"] == "redis"

def test_generate_external_secret():
    app = create_test_app(
        environment={
            "LOG_LEVEL": "info",
            "DB_PASSWORD": {"secret": "db-pass", "provider": "gcp"},
        }
    )
    es = generate_external_secret(app, Environment.GCP)
    assert es["kind"] == "ExternalSecret"
    assert len(es["spec"]["data"]) == 1
    assert es["spec"]["data"][0]["secretKey"] == "DB_PASSWORD"
```

### Integration Tests

Test generated manifests against live cluster:

```bash
# Generate manifests
k3sapp generate --env local --output /tmp/manifests

# Validate with kubectl
kubectl apply --dry-run=client -f /tmp/manifests/

# Apply and verify
kubectl apply -f /tmp/manifests/
kubectl get all -n apps
```

---

## Exhaustive Implementation Steps

This section provides a complete, ordered checklist for implementing all features.

### Phase 1: Foundation (Low Complexity)

#### Step 1.1: ServiceAccount Creation
- [x] **File:** `libs/k3sapp/k3sapp/generators.py`
  - [x] Add `generate_service_account()` function
  - [x] Update `generate_all_manifests()` to call it before Deployment
- [x] **File:** `libs/k3sapp/tests/test_generators.py`
  - [x] Add `test_generate_service_account()`
  - [x] Add `test_generate_service_account_with_annotations()`
- [x] **Verify:** Generate manifests and check ServiceAccount is created

#### Step 1.2: Ephemeral Storage
- [x] **File:** `libs/k3sapp/k3sapp/generators.py`
  - [x] In `generate_deployment()`, add ephemeral-storage to requests/limits
- [x] **File:** `libs/k3sapp/tests/test_generators.py`
  - [x] Add `test_deployment_with_ephemeral_storage()`
- [x] **Verify:** Check Deployment manifest has ephemeral-storage

### Phase 2: Security Features

#### Step 2.1: Network Policy Egress (allow_to)
- [x] **File:** `libs/k3sapp/k3sapp/generators.py`
  - [x] Extend `generate_network_policy()` to handle `allow_to` rules
  - [x] Add DNS egress rule (always allow kube-dns)
  - [x] Add policyTypes: ["Ingress", "Egress"] when egress rules exist
- [x] **File:** `libs/k3sapp/tests/test_generators.py`
  - [x] Add `test_network_policy_with_egress()`
  - [x] Add `test_network_policy_egress_dns_always_allowed()`
- [x] **Verify:** Apply NetworkPolicy and test egress works

### Phase 3: Gateway Features

#### Step 3.1: Gateway Rate Limiting - HAProxy
- [x] **File:** `libs/k3sgateway/k3sgateway/generators.py`
  - [x] In `generate_haproxy_ingress()`, add rate limit annotations
- [x] **File:** `libs/k3sgateway/tests/test_generators.py`
  - [x] Add `test_haproxy_rate_limiting()`
- [x] **Verify:** Test rate limiting with `hey` or `wrk`

#### Step 3.2: Gateway Rate Limiting - Traefik
- [x] **File:** `libs/k3sgateway/k3sgateway/generators.py`
  - [x] Add `generate_traefik_ratelimit_middleware()`
  - [x] Update `generate_traefik_ingressroute()` to include middleware
- [x] **File:** `libs/k3sgateway/tests/test_generators.py`
  - [x] Add `test_traefik_rate_limiting()`
- [x] **Verify:** Test rate limiting on local with Traefik

#### Step 3.3: Gateway CORS for HAProxy
- [x] **File:** `libs/k3sgateway/k3sgateway/generators.py`
  - [x] In `generate_haproxy_ingress()`, add CORS annotations
- [x] **File:** `libs/k3sgateway/tests/test_generators.py`
  - [x] Add `test_haproxy_cors()`
- [x] **Verify:** Test CORS preflight requests

#### Step 3.4: Gateway Authentication - Basic Auth
- [x] **File:** `libs/k3sgateway/k3sgateway/types.py`
  - [x] Add `AuthConfig` dataclass
  - [x] Update `GatewayRoute` to include `auth` field
- [x] **File:** `libs/k3sgateway/k3sgateway/generators.py`
  - [x] In `generate_haproxy_ingress()`, add basic auth annotations
  - [x] Add `generate_traefik_basicauth_middleware()`
- [x] **File:** `schemas/apps-schema.json`
  - [x] Add `auth` to gatewayRoute properties
- [x] **Verify:** Test protected routes with curl

### Phase 4: KEDA Scaling

#### Step 4.1: KEDA Queue Scaling
- [x] **File:** `libs/k3sapp/k3sapp/generators.py`
  - [x] Add `generate_trigger_authentication()`
  - [x] Add `generate_keda_scaledobject_queue()`
  - [x] Update `generate_all_manifests()` for keda-queue
- [x] **File:** `libs/k3sapp/tests/test_generators.py`
  - [x] Add `test_generate_trigger_authentication()`
  - [x] Add `test_generate_keda_scaledobject_queue()`
- [x] **Verify:** Deploy app with queue scaling, push messages, observe scaling

#### Step 4.2: KEDA Cron Scaling
- [x] **File:** `schemas/apps-schema.json`
  - [x] Add `cron_schedules` array to scaling properties
- [x] **File:** `libs/k3sapp/k3sapp/types.py`
  - [x] Add `CronSchedule` dataclass
  - [x] Add `cron_schedules` to `ScalingConfig`
  - [x] Update `ScalingConfig.from_dict()` to parse cron_schedules
- [x] **File:** `libs/k3sapp/k3sapp/generators.py`
  - [x] Add `generate_keda_scaledobject_cron()`
  - [x] Update `generate_all_manifests()` for keda-cron
- [x] **File:** `libs/k3sapp/tests/test_generators.py`
  - [x] Add `test_generate_keda_scaledobject_cron()`
- [x] **Verify:** Deploy app with cron scaling, observe scaling at scheduled times

### Phase 5: Secrets and Environment Variables

#### Step 5.1: Schema and Type Updates
- [x] **File:** `schemas/apps-schema.json`
  - [x] Update `environment` to use oneOf (string or object)
  - [x] Add secret reference schema with provider, version, key
- [x] **File:** `libs/k3sapp/k3sapp/types.py`
  - [x] Add `SecretRef` dataclass
  - [x] Add `EnvironmentValue` dataclass with `is_secret()` method
  - [x] Update `AppConfig.environment` type
  - [x] Add `get_literal_env_vars()` method
  - [x] Add `get_secret_refs()` method
  - [x] Add `_substitute_env_var()` for ${VAR} substitution

#### Step 5.2: Generator Updates
- [x] **File:** `libs/k3sapp/k3sapp/generators.py`
  - [x] Add `generate_cluster_secret_store_gcp()` (platform-level, not per-app - implemented in platform/external-secrets/)
  - [x] Add `generate_external_secret()`
  - [x] Update `generate_deployment()` to split literal vs secret env vars
  - [x] Update `generate_all_manifests()` to include ExternalSecret

#### Step 5.3: Platform Setup
- [x] **File:** `platform/deploy.sh`
  - [x] Add ESO Helm installation
  - [x] Add ClusterSecretStore creation
- [x] **File:** `platform/external-secrets/cluster-secret-store-gcp.yaml`
  - [x] Create ClusterSecretStore manifest
- [x] **File:** `platform/external-secrets/kustomization.yaml`
  - [x] Add kustomization for ESO resources

#### Step 5.4: GCP Setup Script
- [x] **File:** `providers/gcp/setup-secrets.sh`
  - [x] Create script for GCP SA creation
  - [x] Add Secret Manager IAM bindings
  - [x] Add Workload Identity binding

#### Step 5.5: Testing
- [x] **File:** `libs/k3sapp/tests/test_generators.py`
  - [x] Add `test_environment_literal_values()`
  - [x] Add `test_environment_variable_substitution()`
  - [x] Add `test_environment_secret_refs()`
  - [x] Add `test_generate_external_secret()`
  - [x] Add `test_deployment_with_secrets()`
- [x] **Verify:** End-to-end test with GCP Secret Manager (tested with K8S_VALKEY_PASSWORD)

### Phase 5b: k3scompose Library GAPS Features

The k3scompose library also needs the same security features for docker-compose style deployments.

#### Step 5b.1: Types Updates
- [x] **File:** `libs/k3scompose/k3scompose/types.py`
  - [x] Add `SecretProvider` enum (gcp, aws, vault, azure)
  - [x] Add `SecretRef` dataclass
  - [x] Add `EgressRule` dataclass
  - [x] Add `NetworkPolicyConfig` dataclass (enabled, allow_to)
  - [x] Add `SecurityConfig` dataclass (service_account, annotations, network_policy)
  - [x] Add `security` field to `ComposeOverrides`
  - [x] Add `security` field to `ComposeConfig`
  - [x] Add `get_effective_security()` method to `ComposeConfig`

#### Step 5b.2: Generator Functions
- [x] **File:** `libs/k3scompose/k3scompose/generators.py`
  - [x] Add `generate_service_account()` function
  - [x] Add `generate_network_policy()` with ingress and egress rules
  - [x] Add `generate_external_secret()` for ESO integration
  - [x] Update `generate_all_manifests()` to call new generators
  - [x] Add ServiceAccount reference to Deployment
  - [x] Add envFrom secretRef to Deployment for secrets
  - [x] Add NetworkPolicy for each service when enabled

#### Step 5b.3: Syntax Verification
- [x] Verify k3scompose types.py compiles
- [x] Verify k3scompose generators.py compiles

### Phase 5c: k3sfn Library GAPS Features

The k3sfn library for serverless functions already has most features implemented.

#### Step 5c.1: Verification
- [x] **File:** `libs/k3sfn/k3sfn/types.py`
  - [x] Has `SecretProvider` enum
  - [x] Has `SecretRef` dataclass
  - [x] Has `EgressRule` dataclass
  - [x] Has `SecurityConfig` dataclass with allow_to
  - [x] Has `FunctionMetadata.security` field
  - [x] Has `ResourceSpec.ephemeral_storage` field

- [x] **File:** `libs/k3sfn/k3sfn/cli.py`
  - [x] Has `generate_service_account()` function
  - [x] Has `generate_external_secret()` function
  - [x] Has `generate_network_policy()` with egress support
  - [x] Has `_build_resources()` with ephemeral storage support
  - [x] Syntax error fixed (removed orphaned duplicate code)

### Phase 6: Documentation and Cleanup

#### Step 6.1: Update Documentation
- [ ] **File:** `README.md`
  - [ ] Document secrets management
  - [ ] Add examples for each feature
- [ ] **File:** `docs/secrets.md` (create)
  - [ ] Comprehensive secrets documentation
  - [ ] Provider setup guides

#### Step 6.2: Update STATUS.md
- [ ] Mark completed features
- [ ] Update implementation percentages

---

## Sources

- [KEDA Redis Lists Scaler](https://keda.sh/docs/2.18/scalers/redis-lists/)
- [KEDA Cron Scaler](https://keda.sh/docs/2.18/scalers/cron/)
- [Kubernetes Network Policies](https://kubernetes.io/docs/concepts/services-networking/network-policies/)
- [Kubernetes Service Accounts](https://kubernetes.io/docs/concepts/security/service-accounts/)
- [GCP Workload Identity](https://cloud.google.com/kubernetes-engine/docs/how-to/workload-identity)
- [HAProxy Rate Limiting](https://www.haproxy.com/blog/rate-limiting-with-the-haproxy-kubernetes-ingress-controller)
- [Traefik Rate Limiting](https://traefik.io/blog/rate-limiting-on-kubernetes-applications)
- [HAProxy Ingress Configuration](https://haproxy-ingress.github.io/docs/configuration/keys/)
- [KEDA TriggerAuthentication](https://github.com/kedacore/keda-docs/blob/main/content/docs/2.3/concepts/authentication.md)
- [External Secrets Operator](https://external-secrets.io/latest/)
- [ESO GCP Secret Manager Provider](https://external-secrets.io/latest/provider/google-secrets-manager/)
