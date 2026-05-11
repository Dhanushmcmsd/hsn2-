# Security

## Authentication
- JWT access/refresh token flow for user sessions.
- API key auth using SHA-256 key hashes in storage.

## RBAC Summary
| Role | Classification | Reports | Admin | User Mgmt | Audit |
|---|---|---|---|---|---|
| BRANCH_USER | Yes | Limited | No | No | No |
| BRANCH_MANAGER | Yes | Branch | Limited | No | No |
| REGIONAL_ADMIN | Yes | Regional | Partial | Partial | Read scoped |
| HQ_ADMIN | Yes | All | Full | Full | Full |
| AUDITOR | Read-only | Audit/report | No write | No | Read |

## Data Protection
- Data at rest: Neon-managed PostgreSQL encryption.
- Data in transit: TLS 1.3 via Railway edge + HSTS header.
- Secrets: Railway environment variables; no secrets committed.

## Audit Trail
- Append-only `audit_log` for material events and admin/security operations.

## Known Limitations / SOC 2 Type II Plan
- Expand automated control evidence collection.
- Harden periodic access review workflows.
- Add formal DR test cadence and evidence retention.
