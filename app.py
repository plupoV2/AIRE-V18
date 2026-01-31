
import os, re, json, hashlib, sqlite3, base64
from datetime import datetime
from typing import Dict, Any, Optional, Tuple, List

import streamlit as st
import requests
import pandas as pd
import numpy as np

# -----------------------------
# AIRE (Proof-of-Concept) v4
# Proprietary Notice:
# This software and its scoring methodology ("AIRE Vector Grade™") are confidential and proprietary.
# © AIRE PROJECT. All rights reserved.
#
# v4 adds:
# - Workspace invitations + role management UI
# - Audit logs for governance
# - Deal version history ("model version history") with re-evaluation
#
# IMPORTANT (about "self-learning"):
# This app supports an auditable feedback loop (calibration) and re-evaluation that can revise grades over time.
# It does NOT autonomously retrain an ML model. That keeps it enterprise-safe and explainable.
# -----------------------------

st.set_page_config(page_title="AIRE | AI Underwriting", layout="wide")

def stable_hash(s: str) -> int:
    h = hashlib.sha256(s.encode("utf-8")).hexdigest()
    return int(h[:8], 16)

def slugify(text: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9\s-]", "", (text or "")).strip().lower()
    s = re.sub(r"[\s_-]+", "-", s)
    return s[:60] if s else "memo"

def now_utc() -> str:
    return datetime.utcnow().isoformat()

def hex_to_rgb01(hx: str):
    hx = (hx or "#2563eb").lstrip("#")
    return tuple(int(hx[i:i+2], 16)/255.0 for i in (0,2,4))

def gen_invite_code(workspace_id: int, email: str) -> str:
    raw = f"{workspace_id}|{email.lower().strip()}|{now_utc()}|{stable_hash(email)}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]

# =============================
# Theme + Branding
# =============================
def _init_defaults():
    if "theme" not in st.session_state:
        st.session_state.theme = "Light"
    if "brand_accent" not in st.session_state:
        st.session_state.brand_accent = "#2563eb"
    if "brand_name" not in st.session_state:
        st.session_state.brand_name = "AIRE"
    if "brand_logo_b64" not in st.session_state:
        st.session_state.brand_logo_b64 = ""

_init_defaults()

with st.sidebar:
    st.markdown("### Appearance")
    st.session_state.theme = st.radio("Theme", ["Light", "Dark"], index=0 if st.session_state.theme=="Light" else 1)
    st.markdown("### Branding")
    st.session_state.brand_name = st.text_input("Brand name", value=st.session_state.brand_name)
    st.session_state.brand_accent = st.color_picker("Accent color", value=st.session_state.brand_accent)
    logo = st.file_uploader("Logo (PNG/JPG for memo)", type=["png","jpg","jpeg"])
    if logo:
        st.session_state.brand_logo_b64 = base64.b64encode(logo.read()).decode("utf-8")

THEME = st.session_state.theme
ACCENT = st.session_state.brand_accent
BRAND = st.session_state.brand_name

if THEME == "Dark":
    bg = "#0b1220"; card = "#0f172a"; border = "#22314b"; text = "#e5e7eb"; muted = "#cbd5e1"
else:
    bg = "#ffffff"; card = "#ffffff"; border = "#e5e7eb"; text = "#0f172a"; muted = "#334155"

st.markdown(f"""
<style>
#MainMenu, footer, header {{ visibility: hidden; }}
html, body, [class*="css"] {{
  background: {bg} !important;
  color: {text} !important;
  font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, "Helvetica Neue", Arial, "Noto Sans", "Liberation Sans", sans-serif !important;
}}
a {{ color: {ACCENT} !important; }}
.nav {{ display:flex; align-items:center; justify-content:space-between; padding: 14px 8px 6px 8px; margin-bottom: 10px; }}
.brand {{ font-weight: 800; letter-spacing: 0.4px; font-size: 18px; }}
.navlinks span {{ margin-right: 16px; color: {muted}; }}
.pill {{ border: 1px solid {border}; border-radius: 999px; padding: 8px 12px; background: {card}; display:inline-block; }}
.card {{ border: 1px solid {border}; border-radius: 14px; padding: 18px; margin-bottom: 14px; background: {card}; }}
.h1 {{ font-size: 38px; font-weight: 800; line-height: 1.08; margin: 6px 0 6px 0; }}
.h2 {{ font-size: 18px; font-weight: 700; margin: 0 0 8px 0; color: {text}; }}
.p {{ color: {muted}; font-size: 14px; line-height: 1.5; }}
.kpi {{ display:flex; gap:12px; flex-wrap:wrap; }}
.kpi .box {{ border: 1px solid {border}; border-radius: 12px; padding: 12px 14px; background:{card}; min-width: 170px; }}
.kpi .label {{ color:{muted}; font-size:12px; }}
.kpi .value {{ color:{text}; font-weight:800; font-size:18px; margin-top:2px; }}
.divider {{ height:1px; background:{border}; margin: 12px 0; }}
.small {{ font-size: 12px; color:{muted}; }}
.badge {{ display:inline-block; border:1px solid {border}; border-radius:999px; padding:4px 10px; font-size:12px; color:{muted}; }}
</style>
""", unsafe_allow_html=True)

def nav():
    st.markdown(f"""
    <div class="nav">
      <div class="brand">{BRAND}</div>
      <div class="navlinks">
        <span>AI Agents</span><span>Pipelines</span><span>Batch</span><span>Admin</span><span>Resources</span>
      </div>
      <div class="pill">Book a demo</div>
    </div>
    """, unsafe_allow_html=True)
nav()

# =============================
# Database
# =============================
DB_PATH = "aire.db"

def db_conn():
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    cur = conn.cursor()

    cur.execute("""CREATE TABLE IF NOT EXISTS workspaces (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        email TEXT NOT NULL,
        workspace_id INTEGER NOT NULL,
        role TEXT NOT NULL,
        created_at TEXT NOT NULL,
        UNIQUE(email, workspace_id)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS invitations (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        email TEXT NOT NULL,
        role TEXT NOT NULL,
        code TEXT NOT NULL,
        created_at TEXT NOT NULL,
        accepted_at TEXT,
        UNIQUE(workspace_id, email)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS audit_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        actor_email TEXT NOT NULL,
        action TEXT NOT NULL,
        target_type TEXT,
        target_id INTEGER,
        meta TEXT,
        created_at TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS deals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        source TEXT NOT NULL,
        address TEXT NOT NULL,
        folder TEXT NOT NULL,
        slug TEXT NOT NULL,
        grade_letter TEXT NOT NULL,
        grade_score REAL NOT NULL,
        irr_base REAL NOT NULL,
        oer REAL NOT NULL,
        noi REAL NOT NULL,
        payload TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS deal_versions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        deal_id INTEGER NOT NULL,
        version_num INTEGER NOT NULL,
        reason TEXT NOT NULL,
        created_at TEXT NOT NULL,
        grade_letter TEXT NOT NULL,
        grade_score REAL NOT NULL,
        irr_base REAL NOT NULL,
        oer REAL NOT NULL,
        noi REAL NOT NULL,
        payload TEXT NOT NULL,
        UNIQUE(workspace_id, deal_id, version_num)
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS memos (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        workspace_id INTEGER NOT NULL,
        created_at TEXT NOT NULL,
        slug TEXT NOT NULL,
        brand TEXT NOT NULL,
        accent TEXT NOT NULL,
        payload TEXT NOT NULL
    )""")
    cur.execute("""CREATE TABLE IF NOT EXISTS calibration (
        workspace_id INTEGER PRIMARY KEY,
        created_at TEXT NOT NULL,
        vacancy_bias REAL NOT NULL,
        oer_bias REAL NOT NULL,
        irr_bias REAL NOT NULL
    )""")
    conn.commit()
    return conn

CONN = db_conn()

def audit(workspace_id: int, actor_email: str, action: str, target_type: str=None, target_id: int=None, meta: Dict[str, Any]=None):
    cur = CONN.cursor()
    cur.execute("""INSERT INTO audit_log (workspace_id, actor_email, action, target_type, target_id, meta, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (workspace_id, actor_email or "", action, target_type, target_id, json.dumps(meta or {}), now_utc()))
    CONN.commit()

def ensure_workspace(name: str) -> int:
    cur = CONN.cursor()
    cur.execute("SELECT id FROM workspaces WHERE name=?", (name,))
    row = cur.fetchone()
    if row:
        return int(row[0])
    cur.execute("INSERT INTO workspaces (name, created_at) VALUES (?, ?)", (name, now_utc()))
    CONN.commit()
    return int(cur.lastrowid)

def ensure_user(email: str, workspace_id: int, role: str) -> None:
    cur = CONN.cursor()
    cur.execute("INSERT OR IGNORE INTO users (email, workspace_id, role, created_at) VALUES (?, ?, ?, ?)",
                (email, workspace_id, role, now_utc()))
    CONN.commit()

def get_user_role(email: str, workspace_id: int) -> str:
    cur = CONN.cursor()
    cur.execute("SELECT role FROM users WHERE email=? AND workspace_id=?", (email, workspace_id))
    row = cur.fetchone()
    return row[0] if row else "analyst"

def list_users(workspace_id: int) -> pd.DataFrame:
    cur = CONN.cursor()
    cur.execute("SELECT email, role, created_at FROM users WHERE workspace_id=? ORDER BY created_at ASC", (workspace_id,))
    rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["email","role","created_at"])

def set_user_role(workspace_id: int, email: str, role: str):
    cur = CONN.cursor()
    cur.execute("UPDATE users SET role=? WHERE workspace_id=? AND email=?", (role, workspace_id, email))
    CONN.commit()

def upsert_invite(workspace_id: int, email: str, role: str) -> str:
    code = gen_invite_code(workspace_id, email)
    cur = CONN.cursor()
    cur.execute("""INSERT INTO invitations (workspace_id, email, role, code, created_at, accepted_at)
                   VALUES (?, ?, ?, ?, ?, NULL)
                   ON CONFLICT(workspace_id, email) DO UPDATE SET
                     role=excluded.role,
                     code=excluded.code,
                     created_at=excluded.created_at,
                     accepted_at=NULL""",
                (workspace_id, email.lower().strip(), role, code, now_utc()))
    CONN.commit()
    return code

def accept_invite(workspace_id: int, email: str, code: str):
    cur = CONN.cursor()
    cur.execute("SELECT role, code, accepted_at FROM invitations WHERE workspace_id=? AND email=?", (workspace_id, email.lower().strip()))
    row = cur.fetchone()
    if not row:
        return False, "No invite found."
    role, real_code, accepted_at = row
    if real_code != code:
        return False, "Invite code mismatch."
    if accepted_at:
        return False, "Invite already accepted."
    ensure_user(email.lower().strip(), workspace_id, role)
    cur.execute("UPDATE invitations SET accepted_at=? WHERE workspace_id=? AND email=?", (now_utc(), workspace_id, email.lower().strip()))
    CONN.commit()
    return True, f"Invite accepted. Role: {role.upper()}."

def list_invites(workspace_id: int) -> pd.DataFrame:
    cur = CONN.cursor()
    cur.execute("SELECT email, role, code, created_at, accepted_at FROM invitations WHERE workspace_id=? ORDER BY created_at DESC", (workspace_id,))
    rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["email","role","code","created_at","accepted_at"])

def upsert_calibration(workspace_id: int, vacancy_bias: float, oer_bias: float, irr_bias: float):
    cur = CONN.cursor()
    cur.execute("""
        INSERT INTO calibration (workspace_id, created_at, vacancy_bias, oer_bias, irr_bias)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(workspace_id) DO UPDATE SET
            created_at=excluded.created_at,
            vacancy_bias=excluded.vacancy_bias,
            oer_bias=excluded.oer_bias,
            irr_bias=excluded.irr_bias
    """, (workspace_id, now_utc(), vacancy_bias, oer_bias, irr_bias))
    CONN.commit()

def get_calibration(workspace_id: int) -> Dict[str, float]:
    cur = CONN.cursor()
    cur.execute("SELECT vacancy_bias, oer_bias, irr_bias FROM calibration WHERE workspace_id=?", (workspace_id,))
    row = cur.fetchone()
    if not row:
        upsert_calibration(workspace_id, 0.0, 0.0, 0.0)
        return {"vacancy_bias": 0.0, "oer_bias": 0.0, "irr_bias": 0.0}
    return {"vacancy_bias": float(row[0]), "oer_bias": float(row[1]), "irr_bias": float(row[2])}

def save_deal_version(workspace_id: int, actor_email: str, deal_id: int, version_num: int, reason: str,
                      grade_letter: str, grade_score: float, irr_base: float, oer: float, noi: float, payload: Dict[str, Any]):
    cur = CONN.cursor()
    cur.execute("""INSERT OR REPLACE INTO deal_versions
                   (workspace_id, deal_id, version_num, reason, created_at, grade_letter, grade_score, irr_base, oer, noi, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (workspace_id, deal_id, version_num, reason, now_utc(), grade_letter, grade_score, irr_base, oer, noi, json.dumps(payload)))
    CONN.commit()
    audit(workspace_id, actor_email, "deal_version_saved", "deal_version", None, {"deal_id": deal_id, "version": version_num, "reason": reason})

def next_version_num(workspace_id: int, deal_id: int) -> int:
    cur = CONN.cursor()
    cur.execute("SELECT COALESCE(MAX(version_num), 0) FROM deal_versions WHERE workspace_id=? AND deal_id=?", (workspace_id, deal_id))
    return int(cur.fetchone()[0]) + 1

def save_deal(workspace_id: int, actor_email: str, source: str, address: str, folder: str, slug: str,
              grade_letter: str, grade_score: float, irr_base: float, oer: float, noi: float, payload: Dict[str, Any]) -> int:
    cur = CONN.cursor()
    cur.execute("""INSERT INTO deals (workspace_id, created_at, source, address, folder, slug, grade_letter, grade_score, irr_base, oer, noi, payload)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (workspace_id, now_utc(), source, address, folder, slug, grade_letter, grade_score, irr_base, oer, noi, json.dumps(payload)))
    CONN.commit()
    deal_id = int(cur.lastrowid)
    audit(workspace_id, actor_email, "deal_saved", "deal", deal_id, {"folder": folder, "slug": slug})
    save_deal_version(workspace_id, actor_email, deal_id, 1, "initial_save", grade_letter, grade_score, irr_base, oer, noi, payload)
    return deal_id

def list_deals(workspace_id: int, folder: Optional[str]=None):
    cur = CONN.cursor()
    if folder:
        cur.execute("""SELECT id, created_at, folder, address, slug, grade_letter, grade_score, irr_base, oer, noi, payload
                       FROM deals WHERE workspace_id=? AND folder=? ORDER BY id DESC""", (workspace_id, folder))
    else:
        cur.execute("""SELECT id, created_at, folder, address, slug, grade_letter, grade_score, irr_base, oer, noi, payload
                       FROM deals WHERE workspace_id=? ORDER BY id DESC""", (workspace_id,))
    return cur.fetchall()

def move_deal(workspace_id: int, actor_email: str, deal_id: int, folder: str):
    cur = CONN.cursor()
    cur.execute("UPDATE deals SET folder=? WHERE workspace_id=? AND id=?", (folder, workspace_id, deal_id))
    CONN.commit()
    audit(workspace_id, actor_email, "deal_moved", "deal", deal_id, {"new_folder": folder})

def get_deal_row(workspace_id: int, deal_id: int):
    cur = CONN.cursor()
    cur.execute("""SELECT id, created_at, folder, address, slug, grade_letter, grade_score, irr_base, oer, noi, payload
                   FROM deals WHERE workspace_id=? AND id=?""", (workspace_id, deal_id))
    return cur.fetchone()

def list_versions(workspace_id: int, deal_id: int) -> pd.DataFrame:
    cur = CONN.cursor()
    cur.execute("""SELECT version_num, reason, created_at, grade_letter, grade_score, irr_base, oer, noi
                   FROM deal_versions WHERE workspace_id=? AND deal_id=? ORDER BY version_num DESC""",
                (workspace_id, deal_id))
    rows = cur.fetchall()
    return pd.DataFrame(rows, columns=["version","reason","created_at","grade","score","irr","oer","noi"])

def save_memo(workspace_id: int, actor_email: str, slug: str, payload: Dict[str, Any], brand: str, accent: str) -> int:
    cur = CONN.cursor()
    cur.execute("""INSERT INTO memos (workspace_id, created_at, slug, brand, accent, payload)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (workspace_id, now_utc(), slug, brand, accent, json.dumps(payload)))
    CONN.commit()
    memo_id = int(cur.lastrowid)
    audit(workspace_id, actor_email, "memo_saved", "memo", memo_id, {"slug": slug})
    return memo_id

def load_memo_by_id(workspace_id: int, memo_id: int):
    cur = CONN.cursor()
    cur.execute("SELECT id, created_at, slug, brand, accent, payload FROM memos WHERE workspace_id=? AND id=?", (workspace_id, memo_id))
    row = cur.fetchone()
    if not row:
        return None
    mid, created, slug, brand, accent, payload = row
    obj = json.loads(payload)
    obj["_meta"] = {"memo_id": mid, "created_at": created, "slug": slug, "brand": brand, "accent": accent}
    return obj

def load_memo_by_slug(workspace_id: int, slug: str):
    cur = CONN.cursor()
    cur.execute("SELECT id, created_at, slug, brand, accent, payload FROM memos WHERE workspace_id=? AND slug=? ORDER BY id DESC LIMIT 1",
                (workspace_id, slug))
    row = cur.fetchone()
    if not row:
        return None
    mid, created, slug, brand, accent, payload = row
    obj = json.loads(payload)
    obj["_meta"] = {"memo_id": mid, "created_at": created, "slug": slug, "brand": brand, "accent": accent}
    return obj

def list_audit(workspace_id: int, limit: int=200) -> pd.DataFrame:
    cur = CONN.cursor()
    cur.execute("""SELECT created_at, actor_email, action, target_type, target_id, meta
                   FROM audit_log WHERE workspace_id=? ORDER BY id DESC LIMIT ?""", (workspace_id, limit))
    rows = cur.fetchall()
    df = pd.DataFrame(rows, columns=["created_at","actor","action","target_type","target_id","meta"])
    if not df.empty:
        df["meta"] = df["meta"].apply(lambda x: json.loads(x) if isinstance(x, str) and x else {})
    return df

# =============================
# Listing import (demo + RESO scaffold)
# =============================
def demo_listing_from_link(link_or_address: str) -> Dict[str, Any]:
    seed = stable_hash(link_or_address.strip().lower())
    units = 1 + (seed % 64)
    avg_rent = 1100 + (seed % 2200)
    price = int((max(1, units) * avg_rent * 12) / (0.055 + ((seed % 25)/1000)))
    vacancy = round(0.05 + ((seed % 70)/1000), 3)
    taxes = int(price * (0.010 + ((seed % 30)/10000)))
    insurance = int(max(1800, price * (0.002 + ((seed % 20)/10000))))
    utilities_party = "Tenant Paid" if (seed % 2 == 0) else "Landlord Paid"
    return {
        "source": "demo",
        "address": f"{100 + (seed % 900)} Market St, Phoenix, AZ",
        "property_type": "Multifamily" if units >= 10 else "Single Family",
        "price": price,
        "units": units if units >= 2 else 1,
        "sqft": 900 * max(1, units),
        "avg_rent": avg_rent if units >= 2 else avg_rent * 1.6,
        "vacancy": vacancy,
        "other_income_mo": int((seed % 250) * (1 if units > 10 else 0)),
        "taxes": taxes,
        "insurance": insurance,
        "hoa_mo": int((seed % 250) * (1 if units <= 8 else 0)),
        "utilities_mo": int((seed % 600) * (1 if utilities_party == "Landlord Paid" else 0)),
        "management_pct": 0.08,
        "repairs_pct": 0.06,
        "capex_pct": 0.04,
        "utilities_party": utilities_party,
        "year_built": 1950 + (seed % 70),
        "city": "Phoenix",
        "state": "AZ",
    }

def reso_import(link_or_address: str) -> Optional[Dict[str, Any]]:
    base_url = st.secrets.get("RESO_BASE_URL", "")
    token = st.secrets.get("RESO_BEARER_TOKEN", "")
    if not base_url or not token:
        return None
    q = link_or_address.strip()
    headers = {"Authorization": f"Bearer {token}"}
    url = base_url.rstrip("/") + "/Property?$top=1&$filter=contains(UnparsedAddress,'" + q.replace("'", "''") + "')"
    try:
        r = requests.get(url, headers=headers, timeout=12)
        if r.status_code != 200:
            return None
        data = r.json()
        items = data.get("value", [])
        if not items:
            return None
        p = items[0]
        return {
            "source": "reso",
            "address": p.get("UnparsedAddress") or q,
            "property_type": p.get("PropertySubType") or p.get("PropertyType") or "Unknown",
            "price": p.get("ListPrice") or 0,
            "units": p.get("NumberOfUnitsTotal") or 0,
            "sqft": p.get("LivingArea") or p.get("BuildingAreaTotal") or 0,
            "year_built": p.get("YearBuilt") or None,
            "avg_rent": 0,
            "vacancy": 0.07,
            "other_income_mo": 0,
            "taxes": 0,
            "insurance": 0,
            "hoa_mo": 0,
            "utilities_mo": 0,
            "management_pct": 0.08,
            "repairs_pct": 0.06,
            "capex_pct": 0.04,
            "utilities_party": "Unknown",
            "city": p.get("City") or "",
            "state": p.get("StateOrProvince") or "",
        }
    except Exception:
        return None

def import_listing(link_or_address: str) -> Dict[str, Any]:
    reso = reso_import(link_or_address)
    return reso if reso else demo_listing_from_link(link_or_address)

# =============================
# Metrics + IRR
# =============================
def compute_metrics(deal: Dict[str, Any], calib: Dict[str, float]) -> Dict[str, Any]:
    units = max(1, int(deal.get("units") or 1))
    avg_rent = float(deal.get("avg_rent") or 0) or (1600 if deal.get("property_type") in ("Single Family","Condo","Townhouse") else 1400)
    gpr = units * avg_rent * 12
    other_income = float(deal.get("other_income_mo") or 0) * 12
    vacancy = float(deal.get("vacancy") or 0.07) + calib.get("vacancy_bias", 0.0)
    vacancy = max(0.0, min(0.25, vacancy))
    egi = (gpr + other_income) * (1 - vacancy)

    taxes = float(deal.get("taxes") or 0)
    insurance = float(deal.get("insurance") or 0)
    hoa = float(deal.get("hoa_mo") or 0) * 12
    utilities = float(deal.get("utilities_mo") or 0) * 12

    mgmt = egi * float(deal.get("management_pct") or 0.08)
    repairs = egi * float(deal.get("repairs_pct") or 0.06)
    capex = egi * float(deal.get("capex_pct") or 0.04)

    opex = taxes + insurance + hoa + utilities + mgmt + repairs + capex
    opex = max(0.0, opex * (1 + calib.get("oer_bias", 0.0)))
    oer = opex / egi if egi > 0 else 0
    noi = egi - opex

    price = float(deal.get("price") or 0)
    cap_rate = noi / price if price > 0 else 0
    return {"units": units, "avg_rent": avg_rent, "gpr": gpr, "other_income": other_income, "vacancy": vacancy,
            "egi": egi, "taxes": taxes, "insurance": insurance, "hoa": hoa, "utilities": utilities, "mgmt": mgmt,
            "repairs": repairs, "capex": capex, "opex": opex, "oer": oer, "noi": noi, "cap_rate": cap_rate}

def pmt(rate: float, nper: int, pv: float) -> float:
    if rate == 0: return pv / nper
    return pv * rate / (1 - (1 + rate) ** (-nper))

def np_irr(cashflows: List[float]) -> float:
    try:
        r = np.irr(cashflows)  # type: ignore
        if r is None or np.isnan(r): raise Exception()
        return float(r)
    except Exception:
        r = 0.01
        for _ in range(100):
            f = 0.0; df = 0.0
            for t, cf in enumerate(cashflows):
                f += cf / ((1 + r) ** t)
                if t > 0: df -= t * cf / ((1 + r) ** (t + 1))
            if abs(df) < 1e-9: break
            nr = r - f / df
            if abs(nr - r) < 1e-7: r = nr; break
            r = nr
        return float(r)

def build_cashflows(deal: Dict[str, Any], m: Dict[str, Any], hold_years: int, rent_growth: float, expense_growth: float,
                    exit_cap: float, sale_cost_pct: float,
                    down_payment_pct: float, interest_rate: float, amort_years: int,
                    refi_enabled: bool, refi_year: int, refi_ltv: float, refi_rate: float, refi_amort_years: int, refi_cost_pct: float) -> Dict[str, Any]:
    months = hold_years * 12
    price = float(deal.get("price") or 0) or (m["noi"] / max(0.05, m["cap_rate"] or 0.06))
    equity0 = -price * down_payment_pct
    loan0 = price * (1 - down_payment_pct)

    r_m = interest_rate / 12.0
    nper = amort_years * 12
    pay = pmt(r_m, nper, loan0)

    cashflows = [equity0]
    loan_balance = loan0

    egi_m0 = m["egi"] / 12.0
    opex_m0 = m["opex"] / 12.0

    for month in range(1, months + 1):
        y = (month - 1) // 12
        egi_m = egi_m0 * ((1 + rent_growth) ** y)
        opex_m = opex_m0 * ((1 + expense_growth) ** y)
        noi_m = egi_m - opex_m

        interest = loan_balance * r_m
        principal = max(0.0, pay - interest)
        loan_balance = max(0.0, loan_balance - principal)
        cashflows.append(noi_m - pay)

    last_noi_annual = (egi_m0 * ((1+rent_growth) ** (hold_years-1)) - opex_m0 * ((1+expense_growth) ** (hold_years-1))) * 12.0
    sale_price = last_noi_annual / max(0.01, exit_cap)
    sale_cost = sale_price * sale_cost_pct
    net_sale = sale_price - sale_cost - loan_balance
    cashflows[-1] += net_sale

    irr_m = np_irr(cashflows)
    irr_a = (1 + irr_m) ** 12 - 1 if irr_m > -0.999 else -1.0
    eq_mult = (sum(cf for cf in cashflows[1:] if cf > 0) / abs(cashflows[0])) if cashflows[0] != 0 else 0
    return {"cashflows": cashflows, "irr_monthly": irr_m, "irr_annual": irr_a, "equity_multiple": eq_mult,
            "sale_price": sale_price, "net_sale": net_sale, "end_loan_balance": loan_balance}

def aire_grade(m: Dict[str, Any], irr_a: float, calib: Dict[str, float]) -> Dict[str, Any]:
    score = 100.0
    flags = []
    oer = m["oer"]; cap = m["cap_rate"]; vac = m["vacancy"]
    irr_adj = irr_a + calib.get("irr_bias", 0.0)

    if oer > 0.55: score -= 18; flags.append("High operating expense ratio (>55%).")
    elif oer > 0.45: score -= 10; flags.append("Elevated operating expense ratio (>45%).")
    elif oer < 0.25: score -= 6; flags.append("Unusually low expense ratio — verify inputs.")

    if cap <= 0: score -= 18; flags.append("Cap rate unavailable — missing NOI or price.")
    elif cap < 0.045: score -= 12; flags.append("Low cap rate — thin yield.")
    elif cap > 0.09: score += 4; flags.append("High cap rate — verify condition/risks.")

    if vac > 0.12: score -= 10; flags.append("High vacancy assumption (>12%).")
    elif vac < 0.04: score -= 4; flags.append("Very low vacancy — confirm market realism.")

    if irr_adj < 0.08: score -= 8; flags.append("Low IRR (<8%) in base case.")
    elif irr_adj > 0.18: score += 4; flags.append("High IRR (>18%) — double-check assumptions.")

    score = max(0, min(100, score))
    letter = "A" if score >= 90 else "B" if score >= 80 else "C" if score >= 70 else "D" if score >= 60 else "F"
    return {"score": score, "letter": letter, "confidence": 0.75, "flags": flags, "irr_adj": irr_adj}

def apply_chat_update(user_text: str, deal: Dict[str, Any]) -> Tuple[Dict[str, Any], str]:
    t = user_text.lower()
    def find_pct(pats):
        for p in pats:
            m = re.search(p, t)
            if m:
                v = float(m.group(1))
                return v/100.0 if v > 1 else v
        return None
    def find_money(pats):
        for p in pats:
            m = re.search(p, t)
            if m:
                return float(m.group(1).replace(",",""))
        return None
    v = find_pct([r"vacancy\s*(?:to|at|=)\s*([0-9]+(?:\.[0-9]+)?)\s*%?"])
    if v is not None:
        deal["vacancy"] = max(0.0, min(0.25, v)); return deal, f"Updated vacancy to {deal['vacancy']:.1%}."
    tx = find_money([r"tax(?:es)?\s*(?:to|at|=)\s*\$?\s*([0-9][0-9,]*)"])
    if tx is not None:
        deal["taxes"] = int(tx); return deal, f"Updated annual taxes to ${deal['taxes']:,}."
    rent = find_money([r"rent\s*(?:to|at|=)\s*\$?\s*([0-9][0-9,]*)"])
    if rent is not None:
        deal["avg_rent"] = float(rent); return deal, f"Updated average rent to ${deal['avg_rent']:,.0f}/month."
    return deal, "Try: “vacancy to 10%”, “taxes to 22000”, “rent to 1750”."

def generate_memo_pdf_bytes(brand: str, accent: str, logo_b64: str, memo: Dict[str, Any]) -> bytes:
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas
    from reportlab.lib.utils import ImageReader
    import io
    deal = memo["deal"]; m = memo["metrics"]; g = memo["grade"]; mod = memo["model"]; inputs = memo["model_inputs"]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=LETTER)
    w, h = LETTER
    ar, ag, ab = hex_to_rgb01(accent)
    c.setFillColorRGB(ar, ag, ab); c.rect(0, h-44, w, 44, stroke=0, fill=1)
    c.setFillColorRGB(1,1,1); c.setFont("Helvetica-Bold", 14)
    c.drawString(44, h-28, f"{brand} — Investment Memo")
    if logo_b64:
        try:
            img_bytes = base64.b64decode(logo_b64)
            img = ImageReader(io.BytesIO(img_bytes))
            c.drawImage(img, w-120, h-40, width=70, height=28, mask='auto')
        except Exception:
            pass
    c.setFillColorRGB(0.1,0.1,0.1)
    y = h - 70
    c.setFont("Helvetica", 9)
    c.drawString(44, y, f"Property: {deal.get('address','')}")
    c.drawString(44, y-12, f"Generated: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Source: {deal.get('source','demo').upper()}")
    y -= 26
    c.setFont("Helvetica-Bold", 10); c.drawString(44, y, "AIRE Vector Grade™")
    c.setFont("Helvetica", 10); c.drawString(170, y, f"{g['letter']} ({g['score']:.0f}/100) · IRR {mod.get('irr_annual',0):.1%}")
    y -= 18
    c.setFont("Helvetica", 9)
    c.drawString(44, y, f"EGI ${m['egi']:,.0f} · OpEx ${m['opex']:,.0f} (OER {m['oer']:.1%}) · NOI ${m['noi']:,.0f}")
    y -= 16
    c.setFont("Helvetica-Bold", 10); c.drawString(44, y, "Expense Breakdown (Annual)"); y -= 14
    c.setFont("Helvetica", 9)
    for label, val in [("Taxes", m["taxes"]),("Insurance", m["insurance"]),("HOA", m["hoa"]),("Utilities", m["utilities"]),
                       ("Management", m["mgmt"]),("Repairs", m["repairs"]),("CapEx Reserve", m["capex"]),("Total OpEx", m["opex"])]:
        c.drawString(60, y, f"{label}:"); c.drawRightString(250, y, f"${val:,.0f}"); y -= 12
    y -= 4
    c.setFont("Helvetica-Bold", 10); c.drawString(44, y, "Deal Terms & Exit"); y -= 14
    c.setFont("Helvetica", 9)
    c.drawString(60, y, f"Hold {inputs['hold_years']}y · Rent {inputs['rent_growth']:.1%} · Exp {inputs['expense_growth']:.1%}"); y -= 12
    c.drawString(60, y, f"Exit cap {inputs['exit_cap']:.2%} · Sale costs {inputs['sale_cost_pct']:.1%} · Sale ${mod.get('sale_price',0):,.0f}"); y -= 16
    c.setFont("Helvetica-Bold", 10); c.drawString(44, y, "AI Notes"); y -= 14
    c.setFont("Helvetica", 9)
    for n in (g.get("flags", [])[:5] or ["No major flags based on provided inputs."]):
        c.drawString(60, y, f"• {n}"); y -= 12
    c.showPage(); c.save()
    buf.seek(0)
    return buf.read()

# =============================
# Workspace + login (POC)
# =============================
with st.sidebar:
    st.markdown("### Workspace")
    ws_name = st.text_input("Workspace name", value=st.session_state.get("ws_name", "Demo Workspace"))
    st.session_state.ws_name = ws_name
    workspace_id = ensure_workspace(ws_name)

    st.markdown("### User")
    email = st.text_input("Email", value=st.session_state.get("email",""))
    st.session_state.email = email

# Accept invite flow via ?invite=<code>
qp = st.query_params
invite_code = qp.get("invite")
if invite_code and st.session_state.get("email"):
    ok, msg = accept_invite(workspace_id, st.session_state["email"], str(invite_code))
    if ok:
        audit(workspace_id, st.session_state["email"], "invite_accepted", "workspace", workspace_id, {"code": str(invite_code)})
        st.success(msg)

if email:
    cur = CONN.cursor()
    cur.execute("SELECT COUNT(*) FROM users WHERE workspace_id=?", (workspace_id,))
    cnt = int(cur.fetchone()[0])
    role_default = "admin" if cnt == 0 else "analyst"
    ensure_user(email.lower().strip(), workspace_id, role_default)
    st.session_state.role = get_user_role(email.lower().strip(), workspace_id)
    st.caption(f"Role: {st.session_state.role.upper()}")

tabs = st.tabs(["AI Agents", "Pipelines", "Batch", "Admin", "Resources"])

def maybe_render_shareable_memo(workspace_id: int):
    qp = st.query_params
    memo_slug = qp.get("memo_slug")
    memo_id = qp.get("memo")
    if memo_id or memo_slug:
        memo_obj = None
        if memo_id:
            try:
                memo_obj = load_memo_by_id(workspace_id, int(memo_id))
            except Exception:
                memo_obj = None
        if memo_obj is None and memo_slug:
            memo_obj = load_memo_by_slug(workspace_id, str(memo_slug))
        if memo_obj:
            meta = memo_obj["_meta"]
            st.markdown(f"## Shareable Memo — {meta.get('slug')}")
            st.caption("View-only memo page. Clear URL parameters to run new analysis.")
            d = memo_obj["deal"]; m = memo_obj["metrics"]; g = memo_obj["grade"]; mod = memo_obj["model"]
            st.markdown(f"**{d.get('address','')}**  \nGrade: **{g['letter']} ({g['score']:.0f})** · IRR: **{mod.get('irr_annual',0):.1%}** · OER: **{m.get('oer',0):.1%}** · NOI: **${m.get('noi',0):,.0f}**")
            st.stop()

# =============================
# AI Agents
# =============================
with tabs[0]:
    if not st.session_state.get("email"):
        st.info("Enter your email in the sidebar to enable workspaces, roles, and saved pipelines.")
        st.stop()

    maybe_render_shareable_memo(workspace_id)
    calib = get_calibration(workspace_id)

    with st.sidebar:
        st.markdown("### Import")
        link = st.text_input("Paste listing link/address", key="import_link")
        if st.button("Import & Analyze", use_container_width=True):
            if link.strip():
                st.session_state.deal = import_listing(link)
                st.session_state.chat = [{"role":"assistant","content":"Imported. Tell me what to adjust (e.g., “vacancy to 10% and taxes to 22000”)."}]
                audit(workspace_id, st.session_state["email"], "listing_imported", "listing", None, {"input": link.strip()})
            else:
                st.warning("Paste a link or address.")

    if "deal" not in st.session_state:
        st.markdown('<div class="h1">Underwrite deals with one input</div>', unsafe_allow_html=True)
        st.markdown('<div class="p">Paste a listing. AIRE runs debt + IRR, grades it, and saves to pipelines.</div>', unsafe_allow_html=True)
        st.stop()

    deal = st.session_state.deal

    with st.expander("Deal Terms (Debt, Exit, Growth)", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            hold_years = st.number_input("Hold period (years)", 1, 30, 5)
            rent_growth = st.slider("Rent growth (annual)", 0.0, 0.12, 0.03, 0.0025)
            expense_growth = st.slider("Expense growth (annual)", 0.0, 0.12, 0.025, 0.0025)
        with c2:
            down_payment_pct = st.slider("Down payment", 0.05, 0.60, 0.25, 0.01)
            interest_rate = st.slider("Interest rate (annual)", 0.0, 0.15, 0.065, 0.0025)
            amort_years = st.number_input("Amortization (years)", 5, 40, 30)
        with c3:
            exit_cap = st.slider("Exit cap rate", 0.03, 0.12, 0.065, 0.0025)
            sale_cost_pct = st.slider("Sale costs (% of sale price)", 0.0, 0.10, 0.05, 0.005)

    m = compute_metrics(deal, calib)
    model = build_cashflows(deal, m, int(hold_years), float(rent_growth), float(expense_growth),
                            float(exit_cap), float(sale_cost_pct),
                            float(down_payment_pct), float(interest_rate), int(amort_years),
                            False, 1, 0.7, 0.07, 30, 0.01)
    g = aire_grade(m, float(model["irr_annual"]), calib)

    left, right = st.columns([2,1], gap="large")
    with left:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='h2'>Deal Snapshot</div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div class="kpi">
          <div class="box"><div class="label">Grade</div><div class="value">{g['letter']} <span class="small">({g['score']:.0f}/100)</span></div></div>
          <div class="box"><div class="label">IRR (Base)</div><div class="value">{model['irr_annual']:.1%}</div></div>
          <div class="box"><div class="label">Equity Multiple</div><div class="value">{model['equity_multiple']:.2f}×</div></div>
          <div class="box"><div class="label">OER</div><div class="value">{m['oer']:.1%}</div></div>
          <div class="box"><div class="label">NOI</div><div class="value">${m['noi']:,.0f}</div></div>
          <div class="box"><div class="label">Cap Rate</div><div class="value">{m['cap_rate']:.2%}</div></div>
        </div>
        """, unsafe_allow_html=True)
        st.markdown(f"<div class='p'><b>Address:</b> {deal.get('address','')}</div>", unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        memo_payload = {
            "deal": deal, "metrics": m, "grade": g, "model": model,
            "model_inputs": {
                "hold_years": int(hold_years), "rent_growth": float(rent_growth), "expense_growth": float(expense_growth),
                "exit_cap": float(exit_cap), "sale_cost_pct": float(sale_cost_pct),
                "down_payment_pct": float(down_payment_pct), "interest_rate": float(interest_rate), "amort_years": int(amort_years),
            }
        }

        pdf = generate_memo_pdf_bytes(BRAND, ACCENT, st.session_state.brand_logo_b64, memo_payload)
        st.download_button("Download Branded Memo (PDF)", data=pdf,
                           file_name=f"{BRAND}_Memo_{slugify(deal.get('address','property'))}.pdf", use_container_width=True)

        folder = st.selectbox("Pipeline folder", ["Hot","Maybe","Trash"], index=1)
        if st.button("Save to Pipeline", use_container_width=True):
            slug = slugify(f"{deal.get('city','')}-{m['units']}u-{g['letter']}-{deal.get('address','')}")
            did = save_deal(workspace_id, st.session_state["email"], deal.get("source","demo"), deal.get("address",""),
                            folder, slug, g["letter"], float(g["score"]), float(model["irr_annual"]), float(m["oer"]), float(m["noi"]),
                            {"memo": memo_payload})
            mid = save_memo(workspace_id, st.session_state["email"], slug, memo_payload, BRAND, ACCENT)
            st.success(f"Saved deal #{did} to {folder}. Share: ?memo_slug={slug} (or ?memo={mid}).")

    with right:
        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='h2'>Auto-Filled Summary</div>", unsafe_allow_html=True)
        st.markdown(f"""
        <div class="p">
          <span class="badge">Income</span><br/>
          GPR: ${m['gpr']:,.0f} · Other: ${m['other_income']:,.0f} · Vacancy: {m['vacancy']:.1%}<br/>
          <b>EGI:</b> ${m['egi']:,.0f}
        </div>
        <div class="divider"></div>
        <div class="p">
          <span class="badge">Expenses</span><br/>
          Total OpEx: ${m['opex']:,.0f} · <b>OER:</b> {m['oer']:.1%}
        </div>
        """, unsafe_allow_html=True)
        st.markdown("</div>", unsafe_allow_html=True)

        st.markdown("<div class='card'>", unsafe_allow_html=True)
        st.markdown("<div class='h2'>Assistant</div>", unsafe_allow_html=True)
        if "chat" not in st.session_state:
            st.session_state.chat = [{"role":"assistant","content":"Tell me what to adjust. Example: “vacancy to 10% and taxes to 22000”."}]
        for msg in st.session_state.chat:
            with st.chat_message(msg["role"]):
                st.write(msg["content"])
        user = st.chat_input("Ask or adjust assumptions…")
        if user:
            st.session_state.chat.append({"role":"user","content":user})
            deal, reply = apply_chat_update(user, deal)
            st.session_state.deal = deal
            st.session_state.chat.append({"role":"assistant","content":reply})
            audit(workspace_id, st.session_state["email"], "assistant_update", "deal_draft", None, {"user_text": user, "reply": reply})
            st.experimental_rerun()
        st.markdown("</div>", unsafe_allow_html=True)

# =============================
# Pipelines
# =============================
with tabs[1]:
    if not st.session_state.get("email"):
        st.info("Enter your email to enable pipelines.")
        st.stop()
    role = st.session_state.get("role","analyst")
    calib = get_calibration(workspace_id)

    st.markdown('<div class="h1">Pipelines</div>', unsafe_allow_html=True)
    st.markdown('<div class="p">Folders + exports + model version history.</div>', unsafe_allow_html=True)
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    folder = st.selectbox("Folder", ["Hot","Maybe","Trash","All"], index=0)
    rows = list_deals(workspace_id, None if folder=="All" else folder)
    if not rows:
        st.caption("No deals yet.")
        st.stop()

    records = []
    for (deal_id, created, folder_, address, slug, gl, gs, irr, oer, noi, payload) in rows:
        p = json.loads(payload)
        memo = p.get("memo", {})
        deal = memo.get("deal", {})
        m = memo.get("metrics", {})
        records.append({
            "deal_id": deal_id,
            "created_at": created,
            "folder": folder_,
            "address": address,
            "slug": slug,
            "grade": gl,
            "score": round(gs, 1),
            "irr_base": irr,
            "oer": oer,
            "noi": noi,
            "price": deal.get("price", 0),
            "units": m.get("units", deal.get("units", 0)),
            "avg_rent": m.get("avg_rent", deal.get("avg_rent", 0)),
            "egi": m.get("egi", 0),
            "opex": m.get("opex", 0),
            "source": deal.get("source", "demo"),
        })

    df = pd.DataFrame(records).sort_values(["folder","irr_base","score"], ascending=[True, False, False])
    st.dataframe(df.style.format({"irr_base":"{:.1%}","oer":"{:.1%}","noi":"${:,.0f}","price":"${:,.0f}","egi":"${:,.0f}","opex":"${:,.0f}"}), use_container_width=True)

    cA, cB = st.columns([1,1])
    with cA:
        st.markdown("### Move deal (admin)")
        sel_id = st.selectbox("Deal id", df["deal_id"].tolist())
        new_folder = st.selectbox("Move to", ["Hot","Maybe","Trash"], index=0)
        if st.button("Move", disabled=(role!="admin"), use_container_width=True):
            move_deal(workspace_id, st.session_state["email"], int(sel_id), new_folder)
            st.success("Moved."); st.experimental_rerun()
        if role != "admin":
            st.caption("Only Admins can move deals.")
    with cB:
        st.markdown("### Version history")
        vid = st.selectbox("Deal id to view versions", df["deal_id"].tolist(), key="vid")
        vdf = list_versions(workspace_id, int(vid))
        if vdf.empty:
            st.caption("No versions found.")
        else:
            st.dataframe(vdf.style.format({"irr":"{:.1%}","oer":"{:.1%}","noi":"${:,.0f}"}), use_container_width=True)

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
    st.markdown("### Re-evaluate deals (creates new versions)")
    r1, r2, r3 = st.columns(3)
    with r1:
        hold_years_r = st.number_input("Hold years", 1, 30, 5, key="rh")
        rent_growth_r = st.slider("Rent growth", 0.0, 0.12, 0.03, 0.0025, key="rrg")
        exp_growth_r = st.slider("Expense growth", 0.0, 0.12, 0.025, 0.0025, key="reg")
    with r2:
        down_r = st.slider("Down payment", 0.05, 0.60, 0.25, 0.01, key="rdp")
        rate_r = st.slider("Rate", 0.0, 0.15, 0.065, 0.0025, key="rir")
        amort_r = st.number_input("Amort years", 5, 40, 30, key="ram")
    with r3:
        exitcap_r = st.slider("Exit cap", 0.03, 0.12, 0.065, 0.0025, key="rec")
        salecost_r = st.slider("Sale costs", 0.0, 0.10, 0.05, 0.005, key="rsc")
        target = st.selectbox("Re-evaluate", ["Selected deal id", "All deals in current view"], index=0)

    if st.button("Run Re-evaluation", use_container_width=True):
        ids = [int(sel_id)] if target == "Selected deal id" else [int(x) for x in df["deal_id"].tolist()]
        updated = 0
        for did in ids:
            row = get_deal_row(workspace_id, did)
            if not row:
                continue
            payload = json.loads(row[-1])
            memo = payload.get("memo", {})
            deal_obj = memo.get("deal", {})
            m2 = compute_metrics(deal_obj, calib)
            model2 = build_cashflows(deal_obj, m2, int(hold_years_r), float(rent_growth_r), float(exp_growth_r),
                                     float(exitcap_r), float(salecost_r),
                                     float(down_r), float(rate_r), int(amort_r),
                                     False, 1, 0.7, 0.07, 30, 0.01)
            g2 = aire_grade(m2, float(model2["irr_annual"]), calib)

            new_payload = {"memo": {"deal": deal_obj, "metrics": m2, "grade": g2, "model": model2,
                                    "model_inputs": {"hold_years": int(hold_years_r), "rent_growth": float(rent_growth_r),
                                                     "expense_growth": float(exp_growth_r), "exit_cap": float(exitcap_r),
                                                     "sale_cost_pct": float(salecost_r), "down_payment_pct": float(down_r),
                                                     "interest_rate": float(rate_r), "amort_years": int(amort_r)}}}

            cur = CONN.cursor()
            cur.execute("""UPDATE deals SET grade_letter=?, grade_score=?, irr_base=?, oer=?, noi=?, payload=?
                           WHERE workspace_id=? AND id=?""",
                        (g2["letter"], float(g2["score"]), float(model2["irr_annual"]), float(m2["oer"]), float(m2["noi"]),
                         json.dumps(new_payload), workspace_id, did))
            CONN.commit()

            vnum = next_version_num(workspace_id, did)
            save_deal_version(workspace_id, st.session_state["email"], did, vnum, "re_evaluation",
                              g2["letter"], float(g2["score"]), float(model2["irr_annual"]), float(m2["oer"]), float(m2["noi"]),
                              new_payload)
            audit(workspace_id, st.session_state["email"], "deal_re_evaluated", "deal", did, {"new_grade": g2["letter"], "new_score": float(g2["score"])})
            updated += 1
        st.success(f"Re-evaluated {updated} deal(s). New versions created.")
        st.experimental_rerun()

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
    st.markdown("### Export")
    csv_bytes = df.to_csv(index=False).encode("utf-8")
    st.download_button("Download CSV", data=csv_bytes, file_name=f"{BRAND}_pipeline.csv", use_container_width=True)

    import io, zipfile as zf
    xbuf = io.BytesIO()
    with pd.ExcelWriter(xbuf, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="Pipeline", index=False)
        list_audit(workspace_id, limit=500).to_excel(writer, sheet_name="AuditLog", index=False)
        pd.DataFrame([get_calibration(workspace_id)]).to_excel(writer, sheet_name="Calibration", index=False)
    xbuf.seek(0)
    st.download_button("Download Excel (Unified + Audit)", data=xbuf.read(), file_name=f"{BRAND}_workspace_export.xlsx", use_container_width=True)

# =============================
# Batch
# =============================
with tabs[2]:
    if not st.session_state.get("email"):
        st.info("Enter your email to use batch screening.")
        st.stop()
    calib = get_calibration(workspace_id)

    st.markdown('<div class="h1">Batch Screening</div>', unsafe_allow_html=True)
    st.markdown('<div class="p">Paste up to 20 links/addresses. Rank by IRR + score, then save winners.</div>', unsafe_allow_html=True)
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    text_in = st.text_area("Paste links (one per line)", height=160)
    b1, b2, b3 = st.columns(3)
    with b1:
        hold_years_b = st.number_input("Hold (years)", 1, 30, 5, key="bh")
        rent_growth_b = st.slider("Rent growth", 0.0, 0.12, 0.03, 0.0025, key="brg")
        expense_growth_b = st.slider("Expense growth", 0.0, 0.12, 0.025, 0.0025, key="beg")
    with b2:
        down_b = st.slider("Down payment", 0.05, 0.60, 0.25, 0.01, key="bdp")
        rate_b = st.slider("Rate", 0.0, 0.15, 0.065, 0.0025, key="bir")
        amort_b = st.number_input("Amort (years)", 5, 40, 30, key="bam")
    with b3:
        exitcap_b = st.slider("Exit cap", 0.03, 0.12, 0.065, 0.0025, key="bec")
        salecost_b = st.slider("Sale costs", 0.0, 0.10, 0.05, 0.005, key="bsc")

    if st.button("Screen & Rank", use_container_width=True) and text_in.strip():
        lines = [ln.strip() for ln in text_in.splitlines() if ln.strip()][:20]
        rows = []
        for ln in lines:
            d = import_listing(ln)
            m = compute_metrics(d, calib)
            mod = build_cashflows(d, m, int(hold_years_b), float(rent_growth_b), float(expense_growth_b),
                                  float(exitcap_b), float(salecost_b),
                                  float(down_b), float(rate_b), int(amort_b),
                                  False, 1, 0.7, 0.07, 30, 0.01)
            g = aire_grade(m, float(mod["irr_annual"]), calib)
            rows.append({"address": d.get("address",""), "irr": mod["irr_annual"], "eq": mod["equity_multiple"],
                         "oer": m["oer"], "noi": m["noi"], "grade": g["letter"], "score": g["score"],
                         "deal": d, "metrics": m, "model": mod, "grade_obj": g})
        out = pd.DataFrame([{"Address": r["address"], "IRR": r["irr"], "Equity Mult": r["eq"], "OER": r["oer"],
                             "NOI": r["noi"], "Grade": r["grade"], "Score": r["score"]} for r in rows])
        out = out.sort_values(["IRR","Score"], ascending=[False, False]).reset_index(drop=True)
        st.dataframe(out.style.format({"IRR":"{:.1%}","Equity Mult":"{:.2f}","OER":"{:.1%}","NOI":"${:,.0f}"}), use_container_width=True)

        idx = st.number_input("Row # (1-based)", 1, len(rows), 1)
        folder = st.selectbox("Folder", ["Hot","Maybe","Trash"], index=0, key="bs_folder")
        if st.button("Save selected", use_container_width=True):
            r = rows[int(idx)-1]
            slug = slugify(f"{r['deal'].get('city','')}-{r['metrics']['units']}u-{r['grade_obj']['letter']}-{r['deal'].get('address','')}")
            memo_payload = {"deal": r["deal"], "metrics": r["metrics"], "grade": r["grade_obj"], "model": r["model"],
                            "model_inputs": {"hold_years": int(hold_years_b), "rent_growth": float(rent_growth_b), "expense_growth": float(expense_growth_b),
                                             "exit_cap": float(exitcap_b), "sale_cost_pct": float(salecost_b), "down_payment_pct": float(down_b),
                                             "interest_rate": float(rate_b), "amort_years": int(amort_b)}}
            did = save_deal(workspace_id, st.session_state["email"], r["deal"].get("source","demo"), r["deal"].get("address",""),
                            folder, slug, r["grade_obj"]["letter"], float(r["grade_obj"]["score"]), float(r["model"]["irr_annual"]),
                            float(r["metrics"]["oer"]), float(r["metrics"]["noi"]), {"memo": memo_payload})
            save_memo(workspace_id, st.session_state["email"], slug, memo_payload, BRAND, ACCENT)
            st.success(f"Saved deal #{did}.")
            audit(workspace_id, st.session_state["email"], "batch_saved_deal", "deal", did, {"folder": folder})

# =============================
# Admin
# =============================
with tabs[3]:
    if not st.session_state.get("email"):
        st.info("Enter your email to access Admin.")
        st.stop()

    role = st.session_state.get("role","analyst")
    st.markdown('<div class="h1">Admin</div>', unsafe_allow_html=True)
    st.markdown('<div class="p">Invitations, roles, and audit trail.</div>', unsafe_allow_html=True)
    st.markdown('<div class="divider"></div>', unsafe_allow_html=True)

    if role != "admin":
        st.warning("Admin is read-only for Analysts in this POC.")
    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### Team")
        users_df = list_users(workspace_id)
        st.dataframe(users_df, use_container_width=True)
        if role == "admin" and not users_df.empty:
            st.markdown("#### Change role")
            uemail = st.selectbox("User", users_df["email"].tolist())
            new_role = st.selectbox("Role", ["admin","analyst"], index=1)
            if st.button("Update Role", use_container_width=True):
                set_user_role(workspace_id, uemail, new_role)
                audit(workspace_id, st.session_state["email"], "role_updated", "user", None, {"user": uemail, "role": new_role})
                st.success("Role updated.")
                st.experimental_rerun()
    with col2:
        st.markdown("### Invitations")
        inv_df = list_invites(workspace_id)
        st.dataframe(inv_df, use_container_width=True)
        if role == "admin":
            st.markdown("#### Create invite")
            inv_email = st.text_input("Invite email", value="")
            inv_role = st.selectbox("Invite role", ["analyst","admin"], index=0)
            if st.button("Generate Invite Link", use_container_width=True):
                if not inv_email.strip():
                    st.warning("Enter an email.")
                else:
                    code = upsert_invite(workspace_id, inv_email.strip(), inv_role)
                    audit(workspace_id, st.session_state["email"], "invite_created", "invitation", None, {"invitee": inv_email.strip(), "role": inv_role})
                    st.success("Invite created.")
                    st.info(f"Share this link (append to your deployed URL):  ?invite={code}")

    st.markdown("<div class='divider'></div>", unsafe_allow_html=True)
    st.markdown("### Audit log (last 200)")
    st.dataframe(list_audit(workspace_id, limit=200), use_container_width=True)

# =============================
# Resources
# =============================
with tabs[4]:
    st.markdown("<div class='h1'>Resources</div>", unsafe_allow_html=True)
    st.markdown("<div class='p'>v4 makes AIRE feel enterprise-ready: roles, audit, version history.</div>", unsafe_allow_html=True)
