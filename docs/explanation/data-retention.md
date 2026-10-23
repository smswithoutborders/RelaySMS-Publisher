# Data and retention

The cleanup jobs run on the [`CELERY_CLEANUP_CRON` and `CELERY_TOKEN_CLEANUP_CRON` schedules](../configuration/settings.md#cleanup-jobs), and delete data past its limit at the next run.

| Data | Kept until |
| --- | --- |
| Linked accounts' tokens | The user unlinks, or the account has no publication or key sync for `TOKEN_IDLE_MAX_AGE_DAYS` (90); then the Publisher also tries to revoke it on its platform |
| Ephemeral key pools | Each pair is deleted when a publication or token check uses it; the pools go with their token |
| Incomplete multi-part payloads | All segments arrive, or `PAYLOAD_SESSION_MAX_AGE_HOURS` (3) passes |
| Publication stats | Kept |
| Audit events and adapter jobs | `AUDIT_RETENTION_DAYS` (365) |
| Web sessions | Logout, `AUTH_SESSION_IDLE_MINUTES` (30) idle, or `AUTH_SESSION_MAX_HOURS` (12) |
| Credentials, adapters and gateway clients | You remove them |
| Server identity keys | Kept |
| Adapters' own files | Up to each adapter; they live in its state directory |
| Logs | The system journal's retention, and SigNoz's when `OTEL_EXPORTER_OTLP_ENDPOINT` is set |

See the [security model](security-model.md) for what each record holds.
