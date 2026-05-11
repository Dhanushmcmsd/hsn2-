# SLA

- Uptime target: 99.9% monthly
- RTO: 4 hours
- RPO: 1 hour (Neon PITR)

## Latency Targets
- `/predict` p50 < 200ms
- `/predict` p99 < 800ms
- `/predict/bulk/upload` p99 < 3000ms
- `/reports/gst/summary` p99 < 2000ms

## Incident Response
- Sev1: Full outage or severe data integrity issue.
- Sev2: Major degradation or critical feature unavailable.
- Sev3: Partial impairment with workaround.
- Escalation chain: On-call engineer -> Engineering lead -> Product/Stakeholder updates.
