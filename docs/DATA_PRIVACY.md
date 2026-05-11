# Data Privacy

## PII Processed
- User email
- IP address (audit logging)
- Product descriptions (business transaction content)

## Retention Policy
- `audit_log`: 7 years
- predictions: 3 years

## DPDP Act 2023 Notes
- Purpose limitation: data is used for HSN/GST classification workflows.
- Access controls and auditability are enforced via RBAC and logging.
- Security safeguards include TLS, key hashing, and environment-scoped secrets.

## Right to Erasure
1. Deactivate user credentials and API keys.
2. Delete/anonymize user profile and personal references.
3. Retain legally required audit records with minimal retained identifiers.
