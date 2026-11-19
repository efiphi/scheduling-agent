"""Checks on the rendered Helm chart (deploy/helm/scheduling-agent): T13, T17, T21.

The security properties of the cluster live in YAML, so they are tested like code:
render the chart and check every pod. Needs the helm binary; skipped without it
(CI installs it in step 2.7).
"""

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[1]
CHART = ROOT / "deploy/helm/scheduling-agent"
HELM = shutil.which("helm")
needs_helm = pytest.mark.skipif(HELM is None, reason="helm is not installed")
# The Job is named after its image (templates/migrations.yaml); the default values use :dev.
MIGRATIONS = "migrations-" + hashlib.sha256(b"scheduling-agent-migrations:dev").hexdigest()[:8]


def test_postgres_roles_script_is_the_same_file_compose_uses() -> None:
    # Two copies, because a Helm chart can only read files inside itself. One drifting
    # from the other would give the cluster different roles or GRANTs than Compose.
    compose = ROOT / "deploy/compose/postgres/init/01-roles.sh"
    assert (CHART / "files/01-roles.sh").read_bytes() == compose.read_bytes()


@pytest.fixture(scope="module")
def objects() -> list[dict[str, Any]]:
    assert HELM is not None
    out = subprocess.run(  # noqa: S603 - a fixed command, no user input
        [HELM, "template", "test", str(CHART)], capture_output=True, text=True, check=True
    ).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


def pod_templates(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Every pod the chart can start, by owner name: Deployments, StatefulSets, Jobs, CronJobs."""
    templates = {}
    for o in objects:
        if o["kind"] in {"Deployment", "StatefulSet", "Job"}:
            templates[o["metadata"]["name"]] = o["spec"]["template"]
        elif o["kind"] == "CronJob":
            templates[o["metadata"]["name"]] = o["spec"]["jobTemplate"]["spec"]["template"]
    return templates


def pod_specs(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {name: t["spec"] for name, t in pod_templates(objects).items()}


@needs_helm
def test_t21_every_pod_is_hardened(objects: list[dict[str, Any]]) -> None:
    specs = pod_specs(objects)
    assert len(specs) >= 13  # eight workers, two CronJobs, Postgres, Redis, migrations
    for name, spec in specs.items():
        assert spec["automountServiceAccountToken"] is False, name
        assert spec["enableServiceLinks"] is False, name
        assert spec["securityContext"]["runAsNonRoot"] is True, name
        assert spec["securityContext"]["runAsUser"] != 0, name
        assert spec["securityContext"]["seccompProfile"] == {"type": "RuntimeDefault"}, name
        for container in spec["containers"] + spec.get("initContainers", []):
            sc = container["securityContext"]
            assert sc["allowPrivilegeEscalation"] is False, name
            assert sc["readOnlyRootFilesystem"] is True, name
            assert sc["capabilities"] == {"drop": ["ALL"]}, name


@needs_helm
def test_every_image_is_a_local_dev_tag_or_pinned_by_digest(objects: list[dict[str, Any]]) -> None:
    # T20: third-party images by digest. Our own move to immutable GHCR tags in step 2.5.
    for name, spec in pod_specs(objects).items():
        for container in spec["containers"]:
            image = container["image"]
            assert "@sha256:" in image or image.startswith("scheduling-agent-"), name


def secrets_of(spec: dict[str, Any]) -> set[str]:
    return {
        source["secretRef"]["name"]
        for container in spec["containers"]
        for source in container.get("envFrom", [])
        if "secretRef" in source
    }


@needs_helm
def test_t13_t17_each_component_reads_only_its_own_secret(objects: list[dict[str, Any]]) -> None:
    expected = {
        "api": {"api"},
        "whatsapp-webhook": {"api"},
        "notifier": {"api"},
        "alert-relay": {"api"},
        "google-gateway": {"gateway"},
        "gmail-poll": {"gateway"},
        "calendar-responder": {"gateway"},
        "plan-handler": {"gateway"},
        "action-executor": {"gateway"},
        "agent": {"agent"},
        "postgres": {"postgres"},
        "redis": {"redis"},
        MIGRATIONS: {"migrations"},
        "purge-skipped": {"migrations"},
    }
    assert {name: secrets_of(spec) for name, spec in pod_specs(objects).items()} == expected


@needs_helm
def test_adr_011_the_agent_is_not_told_where_the_database_is(objects: list[dict[str, Any]]) -> None:
    agent = pod_specs(objects)["agent"]["containers"][0]
    assert "DB_HOST" not in {e["name"] for e in agent["env"]}


@needs_helm
def test_no_secret_values_in_the_chart(objects: list[dict[str, Any]]) -> None:
    # Secrets live outside the chart, sealed, in deploy/cluster/secrets/ (ADR-008).
    assert [o for o in objects if o["kind"] == "Secret"] == []


# --- Sealed Secrets (ADR-008) --------------------------------------------------------------

# One folder per cluster (k3d, aws), each sealed with that cluster's own key.
SEALED = ROOT / "deploy/cluster/secrets"
ENVIRONMENTS = sorted(p.name for p in SEALED.iterdir() if p.is_dir())
per_env = pytest.mark.parametrize("env", ENVIRONMENTS)

# The only keys each component's Secret may hold: the same split as Compose. A key added
# to the wrong Secret (say, a Google key in the agent's) fails here, before any cluster.
ALLOWED_KEYS = {
    "postgres": {
        "POSTGRES_PASSWORD",
        "OWNER_DB_PASSWORD",
        "API_DB_PASSWORD",
        "GATEWAY_DB_PASSWORD",
    },
    "redis": {"REDIS_PASSWORD"},
    "api": {
        "API_DB_PASSWORD",
        "REDIS_PASSWORD",
        "GOOGLE_LOGIN_CLIENT_ID",
        "GOOGLE_LOGIN_CLIENT_SECRET",
        "WEB_APP_URL",
        "WHATSAPP_ACCESS_TOKEN",
        "WHATSAPP_PHONE_NUMBER_ID",
        "WHATSAPP_APP_SECRET",
        "WHATSAPP_VERIFY_TOKEN",
        "WHATSAPP_NOTIFY_TEMPLATE",
        # The alert relay runs from the api image with the api Secret (ADR-022).
        "WHATSAPP_ALERT_TEMPLATE",
        "ALERT_RELAY_TOKEN",
        "ALERT_USER_ID",
    },
    "gateway": {
        "GATEWAY_DB_PASSWORD",
        "REDIS_PASSWORD",
        "GOOGLE_CONNECT_CLIENT_ID",
        "GOOGLE_CONNECT_CLIENT_SECRET",
        "TOKEN_ENCRYPTION_KEYS",
    },
    "agent": {"REDIS_PASSWORD", "ANTHROPIC_API_KEY", "AGENT_DAILY_BUDGET_USD"},
    "migrations": {"MIGRATION_DATABASE_URL", "OWNER_DB_PASSWORD"},
}


def sealed(env: str) -> dict[str, dict[str, Any]]:
    docs = [yaml.safe_load(p.read_text()) for p in sorted((SEALED / env).glob("*.yaml"))]
    return {d["metadata"]["name"]: d for d in docs}


@per_env
def test_t17_committed_secrets_are_sealed_never_plain(env: str) -> None:
    for name, doc in sealed(env).items():
        assert doc["kind"] == "SealedSecret", name
        assert "data" not in doc and "stringData" not in doc, name
        # Strict scope: bound to its own name and namespace (no scope annotations).
        annotations = doc["metadata"].get("annotations") or {}
        assert not any("sealedsecrets.bitnami.com/" in a for a in annotations), name
        assert doc["metadata"]["namespace"] == "scheduling-agent", name


@per_env
def test_t13_invariant_1_each_sealed_secret_holds_only_its_components_keys(env: str) -> None:
    docs = sealed(env)
    assert set(docs) == set(ALLOWED_KEYS)
    for name, doc in docs.items():
        assert set(doc["spec"]["encryptedData"]) <= ALLOWED_KEYS[name], name
    # The two that matter most, spelled out: the agent cannot reach the database or Google.
    agent = set(docs["agent"]["spec"]["encryptedData"])
    assert not any(k.endswith("DB_PASSWORD") or k.startswith("GOOGLE_") for k in agent)
    assert "TOKEN_ENCRYPTION_KEYS" not in set(docs["api"]["spec"]["encryptedData"])


@needs_helm
@per_env
def test_every_secret_the_chart_reads_is_sealed(objects: list[dict[str, Any]], env: str) -> None:
    used = set().union(*(secrets_of(spec) for spec in pod_specs(objects).values()))
    assert used == set(sealed(env))


# --- NetworkPolicies (T21, ADR-011) --------------------------------------------------------
# deploy/k3d/test-network-policies.sh proves these on a running cluster; here, the rendered
# labels and rules, so a values change that opens a path fails before any cluster.


def pod_labels(objects: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    return {name: t["metadata"]["labels"] for name, t in pod_templates(objects).items()}


@needs_helm
def test_t21_the_namespace_denies_all_traffic_by_default(objects: list[dict[str, Any]]) -> None:
    policies = {o["metadata"]["name"]: o["spec"] for o in objects if o["kind"] == "NetworkPolicy"}
    assert policies["default-deny"] == {"podSelector": {}, "policyTypes": ["Ingress", "Egress"]}


@needs_helm
def test_adr_011_the_agent_is_not_labeled_for_the_database(objects: list[dict[str, Any]]) -> None:
    labels = pod_labels(objects)
    assert "scheduling-agent/database" not in labels["agent"]
    database = {name for name, lab in labels.items() if lab.get("scheduling-agent/database")}
    assert database == {
        "api",
        "whatsapp-webhook",
        "notifier",
        "alert-relay",
        "google-gateway",
        "gmail-poll",
        "calendar-responder",
        "plan-handler",
        "action-executor",
        MIGRATIONS,
        "purge-skipped",
    }


@needs_helm
def test_t21_data_stores_and_migrations_cannot_reach_the_internet(
    objects: list[dict[str, Any]],
) -> None:
    labels = pod_labels(objects)
    for name in ("postgres", "redis", MIGRATIONS, "purge-skipped"):
        assert "scheduling-agent/internet" not in labels[name], name


@needs_helm
def test_t21_internet_egress_excludes_private_ranges_and_cloud_metadata(
    objects: list[dict[str, Any]],
) -> None:
    policy = next(o for o in objects if o["metadata"]["name"] == "egress-internet")
    [rule] = policy["spec"]["egress"]
    [block] = rule["to"]
    assert block["ipBlock"]["cidr"] == "0.0.0.0/0"
    assert {"10.0.0.0/8", "169.254.0.0/16", "172.16.0.0/12", "192.168.0.0/16"} <= set(
        block["ipBlock"]["except"]
    )
    assert rule["ports"] == [{"protocol": "TCP", "port": 443}]


@needs_helm
def test_http_services_accept_only_the_ingress_controller(objects: list[dict[str, Any]]) -> None:
    ingress = [
        o
        for o in objects
        if o["metadata"]["name"].startswith("ingress-")
        and o["metadata"]["name"] != "ingress-alert-relay"
    ]
    assert {o["metadata"]["name"] for o in ingress} == {
        "ingress-api",
        "ingress-google-gateway",
        "ingress-whatsapp-webhook",
    }
    for o in ingress:
        [rule] = o["spec"]["ingress"]
        [source] = rule["from"]
        assert source["podSelector"] == {"matchLabels": {"app.kubernetes.io/name": "traefik"}}


# --- CronJobs (E7, UC-M8) ------------------------------------------------------------------


def cronjobs(objects: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {o["metadata"]["name"]: o["spec"] for o in objects if o["kind"] == "CronJob"}


@needs_helm
def test_mail_is_polled_every_minute_and_runs_never_overlap(objects: list[dict[str, Any]]) -> None:
    poll = cronjobs(objects)["gmail-poll"]
    assert poll["schedule"] == "* * * * *"
    assert poll["concurrencyPolicy"] == "Forbid"
    # A run still going when the next one is due is stopped, not stacked.
    assert poll["jobTemplate"]["spec"]["activeDeadlineSeconds"] < 60
    assert "gmail-poller" not in {o["metadata"]["name"] for o in objects}


@needs_helm
def test_uc_m8_skipped_emails_are_purged_daily_by_the_owner_only(
    objects: list[dict[str, Any]],
) -> None:
    purge = cronjobs(objects)["purge-skipped"]
    assert purge["schedule"].split()[2:] == ["*", "*", "*"]  # every day
    [container] = purge["jobTemplate"]["spec"]["template"]["spec"]["containers"]
    assert container["command"][-2:] == ["db.maintenance", "purge-skipped"]
    labels = pod_labels(objects)["purge-skipped"]
    assert "scheduling-agent/redis" not in labels and "scheduling-agent/internet" not in labels


@needs_helm
def test_cronjob_pods_wait_for_the_network_before_running(objects: list[dict[str, Any]]) -> None:
    for name, spec in cronjobs(objects).items():
        pod = spec["jobTemplate"]["spec"]["template"]["spec"]
        assert [c["name"] for c in pod["initContainers"]] == ["wait-for-network"], name


# --- Ingress (step 3.0) --------------------------------------------------------------------


@needs_helm
def test_only_the_three_http_services_are_exposed_each_on_its_own_entry_point(
    objects: list[dict[str, Any]],
) -> None:
    ingresses = {o["metadata"]["name"]: o for o in objects if o["kind"] == "Ingress"}
    exposed = {
        name: (
            o["metadata"]["annotations"]["traefik.ingress.kubernetes.io/router.entrypoints"],
            [p["path"] for rule in o["spec"]["rules"] for p in rule["http"]["paths"]],
        )
        for name, o in ingresses.items()
    }
    assert exposed == {
        "api": ("sa-api", ["/"]),
        # T16: the gateway exposes its OAuth callback and nothing else (no /healthz, no docs).
        "google-gateway": ("sa-gateway", ["/oauth/google/callback"]),
        # The only part reachable from the internet, through the tunnel (ADR-017).
        "whatsapp-webhook": ("sa-webhook", ["/whatsapp/webhook"]),
    }


# --- Observability (step 3.1) --------------------------------------------------------------

OBSERVABILITY = ROOT / "deploy/cluster/observability"


def observability_manifests() -> list[dict[str, Any]]:
    return [
        doc
        for path in sorted((OBSERVABILITY / "manifests").glob("*.yaml"))
        for doc in yaml.safe_load_all(path.read_text())
        if doc
    ]


@per_env
def test_t17_monitoring_secrets_are_sealed_per_cluster_never_plain(env: str) -> None:
    # Not in the shared manifests: each cluster's key opens only its own copy.
    assert "Secret" not in {doc["kind"] for doc in observability_manifests()}
    paths = sorted((SEALED / env / "observability").glob("*.yaml"))
    docs = {d["metadata"]["name"]: d for d in (yaml.safe_load(p.read_text()) for p in paths)}
    assert set(docs) == {"grafana-admin", "alert-relay-token"}
    for name, doc in docs.items():
        assert (doc["kind"], doc["metadata"]["namespace"]) == ("SealedSecret", "observability"), (
            name
        )


def test_t21_the_monitoring_tools_deny_ingress_by_default() -> None:
    policies = {
        doc["metadata"]["name"]: doc["spec"]
        for doc in observability_manifests()
        if doc["kind"] == "NetworkPolicy"
    }
    assert policies["default-deny-ingress"] == {"podSelector": {}, "policyTypes": ["Ingress"]}
    # Grafana is reached only through port-forward: no policy lets any pod in.
    selected = [p["podSelector"].get("matchLabels", {}) for p in policies.values()]
    assert {"app.kubernetes.io/name": "grafana"} not in selected


def test_grafana_does_not_phone_home_or_allow_anonymous_access() -> None:
    values = yaml.safe_load((OBSERVABILITY / "grafana.yaml").read_text())
    ini = values["grafana.ini"]
    assert ini["analytics"]["reporting_enabled"] is False
    assert ini["auth.anonymous"]["enabled"] is False
    assert values["admin"]["existingSecret"] == "grafana-admin"


def test_logs_and_traces_are_not_kept_forever() -> None:
    # Logs carry user ids: 7 days like skipped emails (UC-M8); traces 3 days.
    loki = yaml.safe_load((OBSERVABILITY / "loki.yaml").read_text())
    tempo = yaml.safe_load((OBSERVABILITY / "tempo.yaml").read_text())
    prometheus = yaml.safe_load((OBSERVABILITY / "prometheus.yaml").read_text())
    assert loki["loki"]["limits_config"]["retention_period"] == "168h"
    assert loki["loki"]["compactor"]["retention_enabled"] is True
    assert tempo["tempo"]["retention"] == "72h"
    assert prometheus["server"]["retention"] == "7d"


# --- Telemetry (step 3.3) ------------------------------------------------------------------


@needs_helm
def test_workers_send_telemetry_only_to_the_collector(objects: list[dict[str, Any]]) -> None:
    policy = next(o for o in objects if o["metadata"]["name"] == "egress-telemetry")
    [rule] = policy["spec"]["egress"]
    [target] = rule["to"]
    assert target["podSelector"] == {"matchLabels": {"app.kubernetes.io/name": "alloy"}}
    assert rule["ports"] == [{"protocol": "TCP", "port": 4318}]
    labels = pod_labels(objects)
    senders = {name for name, lab in labels.items() if lab.get("scheduling-agent/telemetry")}
    assert "postgres" not in senders and "redis" not in senders and "purge-skipped" not in senders
    assert {"agent", "api", "gmail-poll", "action-executor"} <= senders


# --- Dashboards and alerts (step 3.6) ------------------------------------------------------


def test_the_dashboards_configmap_is_rendered_from_the_json_sources() -> None:
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "render_dashboards", OBSERVABILITY / "render_dashboards.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    committed = (OBSERVABILITY / "manifests/grafana-dashboards.yaml").read_text()
    assert committed == module.render(), "run deploy/cluster/observability/render_dashboards.py"


def test_every_dashboard_panel_reads_from_a_provisioned_data_source() -> None:
    import json

    uids = {"prometheus", "loki", "tempo"}
    for path in sorted((OBSERVABILITY / "dashboards").glob("*.json")):
        dashboard = json.loads(path.read_text())
        assert dashboard["editable"] is False, path.name  # changes go through git
        for panel in dashboard["panels"]:
            assert panel["datasource"]["uid"] in uids, (path.name, panel["title"])
            for target in panel["targets"]:
                assert target["datasource"]["uid"] in uids, (path.name, panel["title"])


def test_alert_rules_are_unique_explained_and_watch_for_silence() -> None:
    values = yaml.safe_load((OBSERVABILITY / "grafana.yaml").read_text())
    [group] = values["alerting"]["rules.yaml"]["groups"]
    rules = {rule["uid"]: rule for rule in group["rules"]}
    assert len(rules) == len(group["rules"]) >= 5
    assert all(rule["annotations"]["summary"] for rule in rules.values())
    # E13: if polling stops reporting at all, that is the failure itself, not "no data".
    assert rules["sa-poll-stale"]["noDataState"] == "Alerting"
    # Service errors only, and only when they last: telemetry export failures (Alloy down,
    # watched elsewhere) and one-off bursts during a server move paged the owner again and again.
    errors = rules["sa-error-logs"]
    [query] = [d for d in errors["data"] if d["refId"] == "A"]
    assert '!= "opentelemetry.exporter"' in query["model"]["expr"]
    assert errors["for"] == "5m"
    # A job suspended on purpose is not stale (ADR-023), but only through this factor.
    [query] = [d for d in rules["sa-poll-stale"]["data"] if d["refId"] == "A"]
    assert "(1 - kube_cronjob_spec_suspend{" in query["model"]["expr"]


@needs_helm
def test_t9_only_alertmanager_can_reach_the_alert_relay(objects: list[dict[str, Any]]) -> None:
    # The relay can write to the owner's WhatsApp, so nothing else may call it (ADR-022).
    [policy] = [o for o in objects if o["metadata"]["name"] == "ingress-alert-relay"]
    [rule] = policy["spec"]["ingress"]
    assert rule["from"] == [
        {
            "namespaceSelector": {"matchLabels": {"kubernetes.io/metadata.name": "observability"}},
            "podSelector": {"matchLabels": {"app.kubernetes.io/name": "alertmanager"}},
        }
    ]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8003}]
    assert not any(o["kind"] == "Ingress" and "alert-relay" in str(o["spec"]) for o in objects)


# --- The cloud environment (ADR-023) -------------------------------------------------------

ENVIRONMENT_VALUES = ROOT / "deploy/cluster/environments"


@pytest.fixture(scope="module")
def aws_objects() -> list[dict[str, Any]]:
    """The chart as Argo CD renders it on the cloud server: k3d's digests, then aws on top."""
    assert HELM is not None
    out = subprocess.run(  # noqa: S603 - a fixed command, no user input
        [
            HELM,
            "template",
            "test",
            str(CHART),
            "-f",
            str(ENVIRONMENT_VALUES / "k3d/values.yaml"),
            "-f",
            str(ENVIRONMENT_VALUES / "aws/values.yaml"),
        ],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


def render(*value_files: str) -> list[dict[str, Any]]:
    """The chart with these environment value files, in order, as Argo CD applies them."""
    assert HELM is not None
    args = [arg for f in value_files for arg in ("-f", str(ENVIRONMENT_VALUES / f))]
    out = subprocess.run(  # noqa: S603 - a fixed command, no user input
        [HELM, "template", "test", str(CHART), *args], capture_output=True, text=True, check=True
    ).stdout
    return [doc for doc in yaml.safe_load_all(out) if doc]


@needs_helm
def test_at_most_one_cluster_polls_the_mailbox() -> None:
    # Two clusters on one demo mailbox would each answer the same email (ADR-023).
    def polls(objs: list[dict[str, Any]]) -> bool:
        [job] = [
            o for o in objs if o["kind"] == "CronJob" and o["metadata"]["name"] == "gmail-poll"
        ]
        return job["spec"]["suspend"] is False

    k3d = render("k3d/values.yaml", "k3d/settings.yaml")
    aws = render("k3d/values.yaml", "aws/values.yaml")
    assert not (polls(k3d) and polls(aws))


@needs_helm
def test_exactly_one_cluster_polls_and_alerts_the_cloud(aws_objects: list[dict[str, Any]]) -> None:
    # Since step 6.5 the cloud reads the mailbox and sends the owner's alerts; k3d does neither.
    def state(objs: list[dict[str, Any]]) -> tuple[bool, int]:
        [poll] = [
            o for o in objs if o["kind"] == "CronJob" and o["metadata"]["name"] == "gmail-poll"
        ]
        [relay] = [
            o for o in objs if o["kind"] == "Deployment" and o["metadata"]["name"] == "alert-relay"
        ]
        return poll["spec"]["suspend"] is False, relay["spec"]["replicas"]

    assert state(aws_objects) == (True, 1)
    assert state(render("k3d/values.yaml", "k3d/settings.yaml")) == (False, 0)
    # One server, no spare memory: a rollout stops the old pod before starting the new one.
    for o in aws_objects:
        if o["kind"] == "Deployment":
            assert o["spec"]["strategy"]["rollingUpdate"] == {"maxSurge": 0, "maxUnavailable": 1}
            assert o["spec"]["replicas"] == 1, o["metadata"]["name"]


@needs_helm
def test_the_cloud_reserves_less_memory_and_cpu_but_keeps_every_limit(
    objects: list[dict[str, Any]], aws_objects: list[dict[str, Any]]
) -> None:
    def resources(objs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {
            name: spec["containers"][0]["resources"]
            for name, spec in pod_specs(objs).items()
            # Fixed reservations of their own; the migrations Job's name carries the image hash.
            if name not in {"postgres", "redis", "web"} and not name.startswith("migrations-")
        }

    k3d, aws = resources(objects), resources(aws_objects)
    assert set(k3d) == set(aws)
    for name in k3d:
        assert aws[name]["limits"] == k3d[name]["limits"], name
        assert aws[name]["requests"]["memory"] == "128Mi", name
        assert aws[name]["requests"]["cpu"] == "10m", name
        assert "cpu" not in aws[name]["limits"], name
        assert k3d[name]["requests"]["memory"] == k3d[name]["limits"]["memory"], name


@needs_helm
def test_the_cloud_uses_its_public_address(aws_objects: list[dict[str, Any]]) -> None:
    def env(name: str) -> dict[str, str]:
        [container] = pod_specs(aws_objects)[name]["containers"]
        return {e["name"]: e.get("value") for e in container["env"]}

    base = "https://agent.efi-agent.dev"
    assert env("api")["WEB_APP_URL"] == f"{base}/"
    assert env("api")["GOOGLE_LOGIN_REDIRECT_URI"] == f"{base}/api/auth/google/callback"
    assert env("notifier")["WEB_APP_URL"] == f"{base}/"
    assert env("google-gateway")["GOOGLE_CONNECT_REDIRECT_URI"] == f"{base}/oauth/google/callback"


def test_the_cloud_root_takes_shared_apps_only_never_k3ds() -> None:
    root = yaml.safe_load((ROOT / "deploy/cluster/argocd/root-aws.yaml").read_text())
    shared, own = root["spec"]["sources"]
    include = shared["directory"]["include"].strip("{}").split(",")
    apps = ROOT / shared["path"]
    assert all((apps / name).is_file() for name in include)
    # k3d's sealed Secrets cannot be opened on the cloud, and its Traefik ports do not exist there.
    assert not any(name.startswith(("secrets-", "traefik")) for name in include)
    assert "scheduling-agent.yaml" not in include
    own_apps = {p.name for p in (ROOT / own["path"]).glob("*.yaml")}
    assert own_apps == {
        "scheduling-agent.yaml",
        "secrets-aws.yaml",
        "secrets-aws-observability.yaml",
        "traefik-config.yaml",
        "falco.yaml",
    }
    # The same Application names as k3d, so the two clusters read alike.
    # The same Application names as k3d, so the two clusters read alike.
    names = {
        doc["metadata"]["name"]
        for p in (ROOT / own["path"]).glob("*.yaml")
        for doc in yaml.safe_load_all(p.read_text())
        if doc["kind"] == "Application"
    }
    assert names == {
        "scheduling-agent",
        "secrets-aws",
        "secrets-aws-observability",
        "traefik-config",
        "falco",
        "falco-config",
    }


@needs_helm
def test_the_cloud_serves_everything_on_one_https_host(
    objects: list[dict[str, Any]], aws_objects: list[dict[str, Any]]
) -> None:
    def ingresses(objs: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
        return {o["metadata"]["name"]: o for o in objs if o["kind"] == "Ingress"}

    def paths(o: dict[str, Any]) -> list[str]:
        return [p["path"] for p in o["spec"]["rules"][0]["http"]["paths"]]

    aws = ingresses(aws_objects)
    assert {name: paths(o) for name, o in aws.items()} == {
        "api": ["/api"],
        "google-gateway": ["/oauth/google/callback"],
        "whatsapp-webhook": ["/whatsapp/webhook"],
        "web": ["/"],
    }
    for name, o in aws.items():
        annotations = o["metadata"]["annotations"]
        assert o["spec"]["rules"][0]["host"] == "agent.efi-agent.dev", name
        # HTTPS only, with a real certificate: no route on plain HTTP (it only redirects).
        assert annotations["traefik.ingress.kubernetes.io/router.entrypoints"] == "websecure"
        assert annotations["traefik.ingress.kubernetes.io/router.tls.certresolver"] == "letsencrypt"
    # The api sees its own paths: /api is stripped before the request reaches it.
    [strip] = [o for o in aws_objects if o["kind"] == "Middleware"]
    assert strip["spec"] == {"stripPrefix": {"prefixes": ["/api"]}}
    assert aws["api"]["metadata"]["annotations"][
        "traefik.ingress.kubernetes.io/router.middlewares"
    ].endswith("-strip-api@kubernetescrd")
    # k3d is unchanged: no host, one local port per service, no web pod.
    k3d = ingresses(objects)
    assert set(k3d) == {"api", "google-gateway", "whatsapp-webhook"}
    assert all("host" not in o["spec"]["rules"][0] for o in k3d.values())
    assert not any(o["kind"] == "Middleware" for o in objects)


@needs_helm
def test_t21_the_web_pod_is_hardened_and_reaches_nothing(aws_objects: list[dict[str, Any]]) -> None:
    template = pod_templates(aws_objects)["web"]
    spec = template["spec"]
    [container] = spec["containers"]
    assert spec["automountServiceAccountToken"] is False
    assert spec["securityContext"]["runAsNonRoot"] is True
    assert container["securityContext"] == {
        "allowPrivilegeEscalation": False,
        "readOnlyRootFilesystem": True,
        "capabilities": {"drop": ["ALL"]},
    }
    # Static files only: no Secret, no environment, and no label that opens an egress path.
    assert "envFrom" not in container and "env" not in container
    labels = template["metadata"]["labels"]
    assert not any(key.startswith("scheduling-agent/") for key in labels)
    [policy] = [o for o in aws_objects if o["metadata"]["name"] == "ingress-web"]
    [rule] = policy["spec"]["ingress"]
    assert rule["ports"] == [{"protocol": "TCP", "port": 8080}]
    assert rule["from"][0]["podSelector"] == {"matchLabels": {"app.kubernetes.io/name": "traefik"}}


def test_the_cloud_traefik_redirects_to_https_and_keeps_its_certificates() -> None:
    config = yaml.safe_load((ROOT / "deploy/cluster/traefik-aws/helmchartconfig.yaml").read_text())
    values = yaml.safe_load(config["spec"]["valuesContent"])
    redirect = values["ports"]["web"]["http"]["redirections"]["entryPoint"]
    assert redirect == {"to": "websecure", "scheme": "https", "permanent": True}
    acme = values["certificatesResolvers"]["letsencrypt"]["acme"]
    # On the persistent volume, so a restart does not ask Let's Encrypt again.
    assert values["persistence"]["enabled"] is True
    assert acme["storage"].startswith(values["persistence"].get("path", "/data"))


def mebibytes(quantity: str) -> float:
    units = {"Ki": 1 / 1024, "Mi": 1, "Gi": 1024}
    return float(quantity[:-2]) * units[quantity[-2:]]


@needs_helm
def test_no_pod_reserves_more_memory_than_its_limit(
    objects: list[dict[str, Any]], aws_objects: list[dict[str, Any]]
) -> None:
    # Kubernetes refuses such a pod outright (seen with the web pod on the cloud, 6.4).
    for objs in (objects, aws_objects):
        for name, spec in pod_specs(objs).items():
            for c in spec["containers"] + spec.get("initContainers", []):
                r = c["resources"]
                assert mebibytes(r["requests"]["memory"]) <= mebibytes(r["limits"]["memory"]), name


def test_the_digest_file_holds_digests_only() -> None:
    # CI's merge into deploy/k3d keeps that branch's side of a nearby change, so a setting
    # put in the digest file can vanish without a conflict (seen 19.11).
    values = yaml.safe_load((ENVIRONMENT_VALUES / "k3d/values.yaml").read_text())
    assert set(values) == {"images"}
    # And the Argo CD apps read the files the tests render.
    app = yaml.safe_load((ROOT / "deploy/cluster/argocd/apps/scheduling-agent.yaml").read_text())
    assert [
        f.rsplit("environments/", 1)[1] for f in app["spec"]["source"]["helm"]["valueFiles"]
    ] == [
        "k3d/values.yaml",
        "k3d/settings.yaml",
    ]


@needs_helm
def test_every_http_process_gets_minutes_to_start_before_liveness_counts(
    aws_objects: list[dict[str, Any]],
) -> None:
    # A liveness kill during a slow start only starts the process over (seen 19.11).
    for name, spec in pod_specs(aws_objects).items():
        for c in spec["containers"]:
            if "livenessProbe" in c:
                startup = c["startupProbe"]
                assert startup["periodSeconds"] * startup["failureThreshold"] >= 300, name
                assert c["livenessProbe"]["timeoutSeconds"] >= 5, name


def test_t20_t21_falco_is_pinned_offline_and_not_privileged() -> None:
    values = yaml.safe_load((ROOT / "deploy/cluster/falco/values.yaml").read_text())
    # T20: the image by digest, and nothing downloaded while it runs (no falcoctl).
    assert re.fullmatch(r"[0-9.]+@sha256:[0-9a-f]{64}", values["image"]["tag"])
    assert values["falcoctl"]["artifact"]["install"]["enabled"] is False
    assert values["falcoctl"]["artifact"]["follow"]["enabled"] is False
    # T21: kernel capabilities only, not a privileged container.
    assert values["driver"] == {"kind": "modern_ebpf", "modernEbpf": {"leastPrivileged": True}}
    # Its findings reach the owner: Prometheus reads the counter per rule.
    assert values["metrics"]["enabled"] is True
    # Only the rule counter: Falco's internal statistics are hundreds of series (memory).
    extra = {
        k: v
        for k, v in values["metrics"].items()
        if k.endswith("Enabled") and k != "rulesCountersEnabled"
    }
    assert extra and not any(extra.values()), extra
    assert values["metrics"]["rulesCountersEnabled"] is True
    assert values["metrics"]["service"]["annotations"]["prometheus.io/scrape"] == "true"
    # Its namespace takes nothing but Prometheus on the metrics port.
    policies = list(
        yaml.safe_load_all(
            (ROOT / "deploy/cluster/falco/manifests/networkpolicies.yaml").read_text()
        )
    )
    assert {p["metadata"]["name"] for p in policies} == {
        "default-deny-ingress",
        "metrics-from-prometheus",
    }
