
# AIRE — AI Real Estate Underwriting (Streamlit) v4

v4 adds:
- **Invitations** (`?invite=<code>`) + **role management** (Admin vs Analyst)
- **Audit log** (who did what, when)
- **Deal version history** (grade/IRR revisions are stored as versions)
- **Re-evaluation** (re-score selected/all deals → new versions)
- **Excel export** includes Pipeline + AuditLog + Calibration sheets

## Run
```bash
pip install -r requirements.txt
streamlit run app.py
```

## Deploy (Streamlit Community Cloud)
- App file: `app.py`

## Invite links (POC flow)
1) Admin → Admin tab → Generate invite link  
2) Send `?invite=<code>` to teammate  
3) Teammate opens link and enters the invited email in sidebar  
4) Invite is accepted and user is created with the assigned role

> Production: replace invite param with real auth/SSO.

## Shareable memo links
- `?memo_slug=<slug>` or `?memo=<id>` show a view-only memo page.
