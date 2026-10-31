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
