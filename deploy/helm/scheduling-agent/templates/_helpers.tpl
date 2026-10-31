{{/* Labels every object carries. */}}
{{- define "sa.labels" -}}
app.kubernetes.io/part-of: scheduling-agent
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
The hardened security context for every container (T21): no root, no privilege
escalation, no Linux capabilities, a read-only root filesystem, the default seccomp
profile. Writable paths are explicit emptyDir volumes.
*/}}
{{- define "sa.containerSecurity" -}}
allowPrivilegeEscalation: false
readOnlyRootFilesystem: true
capabilities:
  drop: [ALL]
{{- end }}

{{- define "sa.podSecurity" -}}
runAsNonRoot: true
seccompProfile:
  type: RuntimeDefault
{{- end }}

{{/*
Labels on a worker pod: its name, and what it may reach (networkpolicies.yaml).
Called with (dict "root" $ "name" $name "w" $w).
*/}}
{{- define "sa.workerLabels" -}}
{{ include "sa.labels" .root }}
app.kubernetes.io/name: {{ .name }}
app.kubernetes.io/component: {{ .w.image }}
{{- if ne .w.redis false }}
scheduling-agent/redis: "true"
{{- end }}
{{- if ne .w.database false }}
scheduling-agent/database: "true"
{{- end }}
{{- if .w.internet }}
scheduling-agent/internet: "true"
{{- end }}
{{- if ne .w.telemetry false }}
scheduling-agent/telemetry: "true"
{{- end }}
{{- end }}

{{/*
The pod spec every worker shares, for Deployments and CronJobs alike: its own
ServiceAccount with no Kubernetes token mounted (nothing here talks to the Kubernetes
API), the hardened security context (T21), only its own Secret (invariants 1 and 7), and a
writable /tmp on an emptyDir, since the root filesystem is read-only.
Called with (dict "root" $ "name" $name "w" $w "restartPolicy" "Always" "waitForNetwork" bool).
*/}}
{{- define "sa.workerPodSpec" -}}
{{- $root := .root }}{{- $w := .w }}
serviceAccountName: {{ .name }}
automountServiceAccountToken: false
# No automatic SERVICE_HOST/SERVICE_PORT variables for every Service: they collide
# with our own (REDIS_PORT=tcp://...) and tell a pod about services it never uses.
enableServiceLinks: false
{{- if ne .restartPolicy "Always" }}
restartPolicy: {{ .restartPolicy }}
{{- end }}
securityContext:
  {{- include "sa.podSecurity" $root | nindent 2 }}
  runAsUser: 10001
  runAsGroup: 10001
{{- if .waitForNetwork }}
# A short-lived pod's first connections are refused until the NetworkPolicy controller
# learns its address (seen on k3s, see migrations.yaml). Wait for them here, so the job
# itself starts with a working network instead of failing every run.
initContainers:
  - name: wait-for-network
    image: {{ index $root.Values.images $w.image | quote }}
    imagePullPolicy: {{ $root.Values.pullPolicy }}
    command:
      - python
      - -c
      - |
        import socket, sys, time
        targets = {{ toJson (compact (list (ternary "postgres:5432" "" (ne $w.database false)) (ternary "redis:6379" "" (ne $w.redis false)))) }}
        for _ in range(60):
            try:
                for target in targets:
                    host, port = target.split(":")
                    socket.create_connection((host, int(port)), timeout=2).close()
                sys.exit(0)
            except OSError:
                time.sleep(0.5)
        sys.exit("network not ready")
    securityContext:
      {{- include "sa.containerSecurity" $root | nindent 6 }}
    resources:
      requests: {cpu: 10m, memory: 32Mi}
      limits: {memory: 64Mi}
{{- end }}
containers:
  - name: {{ .name }}
    image: {{ index $root.Values.images $w.image | quote }}
    imagePullPolicy: {{ $root.Values.pullPolicy }}
    command: {{ toJson $w.command }}
    securityContext:
      {{- include "sa.containerSecurity" $root | nindent 6 }}
    env:
      {{- if ne $w.redis false }}
      - name: REDIS_HOST
        value: redis
      {{- end }}
      {{- if ne $w.database false }}
      - name: DB_HOST
        value: postgres
      {{- end }}
      {{- if ne $w.telemetry false }}
      # Traces (and, from step 3.5, metrics) go to Alloy over OTLP/HTTP (shared.tracing).
      - name: OTEL_EXPORTER_OTLP_ENDPOINT
        value: {{ $root.Values.telemetry.endpoint | quote }}
      {{- end }}
      {{- range $key, $value := $w.env }}
      - name: {{ $key }}
        value: {{ $value | quote }}
      {{- end }}
    envFrom:
      - secretRef:
          name: {{ $w.secret }}
    {{- if $w.port }}
    ports:
      - name: http
        containerPort: {{ $w.port }}
    {{- end }}
    {{- if $w.health }}
    readinessProbe:
      httpGet: {path: {{ $w.health }}, port: http}
      periodSeconds: 10
    livenessProbe:
      httpGet: {path: {{ $w.health }}, port: http}
      initialDelaySeconds: 10
      periodSeconds: 30
    {{- end }}
    resources:
      requests: {cpu: {{ $w.resources.cpu }}, memory: {{ $w.resources.memory }}}
      limits: {memory: {{ $w.resources.memory }}}
    volumeMounts:
      - {name: tmp, mountPath: /tmp}
volumes:
  - name: tmp
    emptyDir: {sizeLimit: 64Mi}
{{- end }}

{{- define "sa.serviceAccount" -}}
apiVersion: v1
kind: ServiceAccount
metadata:
  name: {{ .name }}
  labels:
    {{- include "sa.labels" .root | nindent 4 }}
    app.kubernetes.io/name: {{ .name }}
automountServiceAccountToken: false
{{- end }}
