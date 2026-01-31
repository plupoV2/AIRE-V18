
# v4 notes

### New tables
- invitations
- audit_log
- deal_versions

### What “model version history” means here
Each time a deal is saved or re-evaluated:
- a new version record is created with grade/IRR/OER/NOI + full underwriting payload
- audit log captures who triggered the change and why

This is the enterprise-safe alternative to opaque “self-training”.
