{{/*
Expand the name of the chart.
*/}}
{{- define "agent-system.name" -}}
{{- default .Chart.Name .Values.nameOverride | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Create a default fully qualified app name.
*/}}
{{- define "agent-system.fullname" -}}
{{- if .Values.fullnameOverride }}
{{- .Values.fullnameOverride | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- $name := default .Chart.Name .Values.nameOverride }}
{{- if contains $name .Release.Name }}
{{- .Release.Name | trunc 63 | trimSuffix "-" }}
{{- else }}
{{- printf "%s-%s" .Release.Name $name | trunc 63 | trimSuffix "-" }}
{{- end }}
{{- end }}
{{- end }}

{{/*
Create chart name and version as used by the chart label.
*/}}
{{- define "agent-system.chart" -}}
{{- printf "%s-%s" .Chart.Name .Chart.Version | replace "+" "_" | trunc 63 | trimSuffix "-" }}
{{- end }}

{{/*
Common labels
*/}}
{{- define "agent-system.labels" -}}
helm.sh/chart: {{ include "agent-system.chart" . }}
{{ include "agent-system.selectorLabels" . }}
{{- if .Chart.AppVersion }}
app.kubernetes.io/version: {{ .Chart.AppVersion | quote }}
{{- end }}
app.kubernetes.io/managed-by: {{ .Release.Service }}
{{- end }}

{{/*
Selector labels
*/}}
{{- define "agent-system.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agent-system.name" . }}
app.kubernetes.io/instance: {{ .Release.Name }}
{{- end }}

{{/*
Backend selector labels
*/}}
{{- define "agent-system.backend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agent-system.name" . }}-backend
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: backend
{{- end }}

{{/*
Frontend selector labels
*/}}
{{- define "agent-system.frontend.selectorLabels" -}}
app.kubernetes.io/name: {{ include "agent-system.name" . }}-frontend
app.kubernetes.io/instance: {{ .Release.Name }}
app.kubernetes.io/component: frontend
{{- end }}

{{/*
Database URL for PostgreSQL
*/}}
{{- define "agent-system.databaseUrl" -}}
{{- if .Values.postgresql.enabled }}
postgresql+asyncpg://{{ .Values.postgresql.auth.username }}:$(DATABASE_PASSWORD)@{{ .Release.Name }}-postgresql:5432/{{ .Values.postgresql.auth.database }}
{{- else }}
{{ .Values.externalDatabase.url }}
{{- end }}
{{- end }}

{{/*
Neo4j URI
*/}}
{{- define "agent-system.neo4jUri" -}}
{{- if .Values.neo4j.enabled }}
bolt://{{ .Release.Name }}-neo4j:7687
{{- else }}
{{ .Values.externalNeo4j.uri }}
{{- end }}
{{- end }}
