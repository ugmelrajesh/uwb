"""WeighBridge Pro - Streamlit port of the weighbridge-management React app.

Storage: SQLite file (weighbridge.db). Streamlit Community Cloud has an
ephemeral disk: data resets on reboot/redeploy. Use Management > Backup
to export/restore JSON.
"""
import html
import json
import re
import sqlite3
import time
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

TZ = ZoneInfo("Asia/Kolkata")
DB_PATH = "weighbridge.db"
DEFAULT_PIN = "1234"
PAGE_SIZE = 15
STATUSES = ["pending", "first_weighed", "completed", "voided"]
STATUS_LABEL = {
    "pending": "Pending",
    "first_weighed": "First Weighed",
    "completed": "Completed",
    "voided": "Voided",
}
VEHICLE_TYPES = ["truck", "tanker", "trailer", "other"]
UNITS = ["kg", "ton", "liter"]
PAPERS = ["A4", "A5", "thermal80"]
PAPER_LABEL = {
    "A4": "A4 (210 × 297 mm)",
    "A5": "A5 (148 × 210 mm)",
    "thermal80": "Thermal 80mm",
}

st.set_page_config(page_title="WeighBridge Pro", page_icon="⚖️", layout="wide")


# ---------------------------------------------------------------- storage
def now_ms() -> int:
    return int(time.time() * 1000)


def new_id(prefix="WB") -> str:
    return f"{prefix}-{uuid.uuid4().hex[:8].upper()}"


def _conn():
    c = sqlite3.connect(DB_PATH, timeout=10)
    c.execute("CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT NOT NULL)")
    return c


def load(key, fallback):
    with _conn() as c:
        row = c.execute("SELECT v FROM kv WHERE k=?", (key,)).fetchone()
    return json.loads(row[0]) if row else fallback


def save(key, data):
    with _conn() as c:
        c.execute(
            "INSERT INTO kv(k,v) VALUES(?,?) ON CONFLICT(k) DO UPDATE SET v=excluded.v",
            (key, json.dumps(data)),
        )


def seed():
    if load("initialized", False):
        return
    day = 86_400_000
    t = now_ms()
    vehicles = [
        ("ABC-1234", 20000, "truck"),
        ("XYZ-5678", 35000, "tanker"),
        ("DEF-9012", 28000, "trailer"),
        ("GHI-3456", 22000, "truck"),
    ]
    materials = ["M SAND", "P SAND", "DUST", "20 MM", "16 MM", "12 MM", "6 MM", "WMM", "CLAY"]
    save(
        "vehicles",
        [
            dict(id=new_id("V"), plateNumber=p, grossWeight=w, vehicleType=ty,
                 isActive=True, createdAt=t - day * (10 - i))
            for i, (p, w, ty) in enumerate(vehicles)
        ],
    )
    save(
        "materials",
        [
            dict(id=new_id("M"), name=n, category="Construction", unit="ton",
                 isActive=True, createdAt=t - day * (10 - i))
            for i, n in enumerate(materials)
        ],
    )
    save("transactions", [])
    save("pin", DEFAULT_PIN)
    save("print_settings", {"gatePass": "A5", "finalWeigh": "A5", "estimateOrientation": "portrait"})
    save("initialized", True)


# ------------------------------------------------------------- GP helpers
def build_gp_remarks(vehicle, material, tare):
    return f"[GATE PASS] Vehicle: {vehicle} | Material: {material} | Tare: {tare}kg"


def parse_gp(remarks):
    if not (remarks or "").startswith("[GATE PASS]"):
        return None
    v = re.search(r"Vehicle:\s*([^|]+)", remarks)
    m = re.search(r"Material:\s*([^|]+)", remarks)
    w = re.search(r"(?:Tare|Gross):\s*([\d.]+)kg", remarks)
    return dict(
        vehicleNumber=v.group(1).strip() if v else "",
        materialName=m.group(1).strip() if m else "",
        tareWeight=float(w.group(1)) if w else 0.0,
    )


def fmt_num(x):
    if x is None:
        return "—"
    return f"{x:,.2f}".rstrip("0").rstrip(".") if isinstance(x, float) else f"{x:,}"


def fmt_dt(ms):
    return datetime.fromtimestamp(ms / 1000, TZ).strftime("%d-%m-%Y %H.%M") if ms else ""


def tx_display(tx, vehicles, materials):
    gp = parse_gp(tx.get("remarks"))
    if gp:
        veh, mat, tare, gross = gp["vehicleNumber"], gp["materialName"], tx.get("firstWeight", gp["tareWeight"]), tx.get("secondWeight")
    else:
        veh = next((v["plateNumber"] for v in vehicles if v["id"] == tx.get("vehicleId")), "—")
        mat = next((m["name"] for m in materials if m["id"] == tx.get("materialId")), "—")
        tare, gross = tx.get("secondWeight"), tx.get("firstWeight")
    return veh, mat, tare, gross


# ----------------------------------------------------------- print slips
def _print_wrap(body, page_css, height):
    doc = f"""<html><head><style>
    @media print {{ @page {{ size: {page_css}; margin: 10mm; }} .np {{ display:none }} }}
    body {{ margin:0; background:#fff; color:#000; }}
    button {{ padding:8px 18px; font-size:14px; cursor:pointer; border-radius:6px;
              border:1px solid #1e5aa8; background:#1e5aa8; color:#fff; }}
    </style></head><body>{body}
    <div class="np" style="text-align:center;margin-top:16px">
      <button onclick="window.print()">🖨 Print</button></div></body></html>"""
    components.html(doc, height=height, scrolling=True)


def gate_pass_slip(vehicle, material, tare, ts, settings):
    """Gate pass slip: same bordered table as final slip; 2nd/net weight blank."""
    final_slip(dict(date=fmt_dt(ts), material=material, vehicle=vehicle,
                    tare=fmt_num(tare), gross="", net=""), settings, "gatePass")


def final_slip(d, settings, paper_key="finalWeigh"):
    paper = settings.get(paper_key, "A5")
    if paper == "thermal80":
        size = "80mm auto"
    else:
        size = f"{paper} {settings.get('estimateOrientation', 'portrait')}"
    rows = [
        ("DATE", d["date"]),
        ("ITEM", d["material"]),
        ("TRUCK NO", d["vehicle"]),
        ("FIRST WEIGHT", d["tare"]),
        ("SECOND WEIGHT", d["gross"]),
        ("NET WEIGHT", d["net"]),
    ]
    cell = "border:1.5px solid #333;padding:8px 14px;font-size:14px;color:#111;"
    trs = "".join(
        f'<tr><td style="{cell}font-weight:bold;width:45%">{k}</td>'
        f'<td style="{cell}text-align:center;{"font-weight:bold;" if k == "NET WEIGHT" else ""}">{html.escape(str(v))}</td></tr>'
        for k, v in rows
    )
    body = f"""<div style="font-family:Arial,sans-serif;max-width:700px;margin:0 auto">
      <table style="width:100%;border-collapse:collapse;border:1.5px solid #333">
      <tr><td colspan="2" style="{cell}height:40px"></td></tr>{trs}</table></div>"""
    _print_wrap(body, size, 420)


def ticket_html(tx, veh, mat):
    cell = "border:1px solid #999;padding:6px 10px;font-size:13px;"
    rows = [
        ("Transaction", tx["id"]), ("Vehicle", veh), ("Material", mat),
        ("Status", STATUS_LABEL.get(tx["status"], tx["status"])),
        ("First weight (kg)", fmt_num(tx.get("firstWeight"))),
        ("Second weight (kg)", fmt_num(tx.get("secondWeight"))),
        ("Net weight (kg)", fmt_num(tx.get("netWeight"))),
        ("Created", fmt_dt(tx.get("createdAt"))),
        ("Completed", fmt_dt(tx.get("completedAt"))),
        ("Remarks", tx.get("remarks", "")),
    ]
    return ("<table style='width:100%;border-collapse:collapse;font-family:Arial'>"
            + "".join(f"<tr><td style='{cell}font-weight:bold;width:35%'>{k}</td>"
                      f"<td style='{cell}'>{html.escape(str(v))}</td></tr>" for k, v in rows)
            + "</table>")


# ------------------------------------------------------------------ PIN
def pin_gate():
    if st.session_state.get("unlocked"):
        return True
    _, mid, _ = st.columns([1, 1, 1])
    with mid:
        st.markdown("## ⚖️ WeighBridge Pro")
        st.caption("Enter PIN to continue")
        with st.form("pin_form", clear_on_submit=True):
            pin = st.text_input("PIN", type="password", max_chars=8)
            if st.form_submit_button("Unlock", use_container_width=True):
                if pin == load("pin", DEFAULT_PIN):
                    st.session_state.unlocked = True
                    st.rerun()
                st.error("Incorrect PIN")
        st.caption("Default PIN: 1234")
    return False


# ----------------------------------------------------------- Gate Pass
def _on_vehicle_change():
    sel = st.session_state.get("gp_vehicle")
    if not sel:
        return
    sel = sel.strip().upper()
    st.session_state.gp_vehicle = sel
    match = next((v for v in load("vehicles", []) if v["isActive"] and v["plateNumber"].upper() == sel), None)
    if match:
        st.session_state.gp_tare = float(match["grossWeight"])


def page_gate_pass():
    st.title("Gate Pass")
    st.caption("Issue a gate pass for vehicle entry. Saved as First Weigh In record.")
    settings = load("print_settings", {})
    vehicles = [v for v in load("vehicles", []) if v["isActive"]]
    materials = [m for m in load("materials", []) if m["isActive"]]

    with st.container(border=True):
        st.subheader("Gate Pass Entry")
        st.caption("Pick a saved vehicle/material or type a new one and press Enter.")
        vehicle = st.selectbox(
            "Vehicle Number *", [v["plateNumber"] for v in vehicles], index=None,
            accept_new_options=True, placeholder="e.g. KL-1234",
            key="gp_vehicle", on_change=_on_vehicle_change,
        )
        saved = next((v for v in vehicles if vehicle and v["plateNumber"].upper() == vehicle.upper()), None)
        if saved:
            st.caption("✅ Matched saved vehicle — tare weight auto-filled")
        material = st.selectbox(
            "Material Name *", [m["name"] for m in materials], index=None,
            accept_new_options=True, placeholder="e.g. M SAND, P SAND, DUST", key="gp_material",
        )
        tare = st.number_input("Tare Weight (kg) *", min_value=0.0, step=0.01, key="gp_tare", format="%.2f")
        if vehicle and not saved:
            st.caption("New vehicle — tare weight will be saved to the management panel")

        if st.button("Save & Print Gate Pass", type="primary"):
            if not vehicle or not material or not tare:
                st.error("All fields are required")
            elif tare <= 0:
                st.error("Enter a valid tare weight")
            else:
                plate, mat = vehicle.strip().upper(), material.strip()
                all_v = load("vehicles", [])
                if not any(v["plateNumber"].upper() == plate for v in all_v):
                    all_v.append(dict(id=new_id("V"), plateNumber=plate, grossWeight=tare,
                                      vehicleType="truck", isActive=True, createdAt=now_ms()))
                    save("vehicles", all_v)
                    st.toast(f"New vehicle {plate} saved to management panel")
                ts = now_ms()
                txs = load("transactions", [])
                tx = dict(id=f"WB-{uuid.uuid4().hex[:8].upper()}", vehicleId=f"gp-{ts}",
                          materialId=f"gp-mat-{ts}", operatorId="gate-operator",
                          status="first_weighed", firstWeight=tare, firstWeighTime=ts,
                          remarks=build_gp_remarks(plate, mat, tare), createdAt=ts)
                txs.append(tx)
                save("transactions", txs)
                st.session_state.last_gp = (plate, mat, tare, ts)
                st.success("Gate pass saved as First Weigh In.")

    if "last_gp" in st.session_state:
        st.markdown("##### Gate Pass slip")
        gate_pass_slip(*st.session_state.last_gp, settings)
        if st.button("Close / New entry"):
            del st.session_state.last_gp
            for k in ("gp_vehicle", "gp_material", "gp_tare"):
                st.session_state.pop(k, None)
            st.rerun()


# --------------------------------------------------------- Transactions
@st.dialog("Edit Transaction")
def edit_dialog(tx):
    gp = parse_gp(tx.get("remarks"))
    if gp:
        veh = st.text_input("Vehicle Number", gp["vehicleNumber"])
        mat = st.text_input("Material Name", gp["materialName"])
        tare = st.number_input("Tare Weight (kg) — First Weigh",
                               value=float(tx.get("firstWeight") or gp["tareWeight"]), step=0.01)
        status = st.selectbox("Status", STATUSES, index=STATUSES.index(tx["status"]),
                              format_func=STATUS_LABEL.get)
        gross = None
        if status == "completed":
            with st.container(border=True):
                st.markdown("**Final Weighing**")
                gross = st.number_input("Gross Weight (kg) — Final Weigh *", min_value=0.0, step=0.01,
                                        value=float(tx.get("secondWeight") or 0.0))
                if gross > 0 and tare > 0:
                    st.info(f"Calculated Net Weight: {abs(gross - tare):,.2f} kg")
                st.caption("Saving will mark as Completed and show the print slip.")
        label = "Complete & Print" if status == "completed" else "Save Changes"
        if st.button(label, type="primary"):
            upd = dict(status=status, remarks=build_gp_remarks(veh.strip(), mat.strip(), tare), firstWeight=tare)
            if status == "completed" and gross and gross > 0:
                t = now_ms()
                upd.update(secondWeight=gross, secondWeighTime=t, netWeight=abs(gross - tare), completedAt=t)
                st.session_state.slip = dict(
                    date=fmt_dt(t), material=mat.strip(), vehicle=veh.strip(),
                    tare=fmt_num(tare), gross=fmt_num(gross), net=fmt_num(abs(gross - tare)))
            update_tx(tx["id"], upd)
            st.rerun()
    else:
        remarks = st.text_area("Remarks", tx.get("remarks", ""))
        status = st.selectbox("Status", STATUSES, index=STATUSES.index(tx["status"]),
                              format_func=STATUS_LABEL.get)
        sec = None
        if status == "completed":
            sec = st.number_input("Tare Weight (kg)", min_value=0.0, step=0.01,
                                  value=float(tx.get("secondWeight") or 0.0))
        if st.button("Save Changes", type="primary"):
            upd = dict(status=status, remarks=remarks)
            if status == "completed" and sec:
                upd["secondWeight"] = sec
                if tx.get("firstWeight") is not None:
                    upd["netWeight"] = tx["firstWeight"] - sec
                    upd["completedAt"] = tx.get("completedAt") or now_ms()
            update_tx(tx["id"], upd)
            st.rerun()


def update_tx(tx_id, upd):
    txs = load("transactions", [])
    save("transactions", [{**t, **upd} if t["id"] == tx_id else t for t in txs])


@st.dialog("Delete Transaction")
def delete_dialog(tx):
    st.write(f"Delete transaction **{tx['id']}**? This cannot be undone.")
    c1, c2 = st.columns(2)
    if c1.button("Delete", type="primary", use_container_width=True):
        save("transactions", [t for t in load("transactions", []) if t["id"] != tx["id"]])
        st.rerun()
    if c2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Delete All Transactions")
def delete_all_dialog(n):
    st.write(f"This permanently deletes all **{n}** transaction(s). This cannot be undone.")
    c1, c2 = st.columns(2)
    if c1.button("Delete All", type="primary", use_container_width=True):
        save("transactions", [])
        st.rerun()
    if c2.button("Cancel", use_container_width=True):
        st.rerun()


@st.dialog("Final Weighing Slip")
def final_slip_dialog(d):
    final_slip(d, load("print_settings", {}))


@st.dialog("Gate Pass")
def gp_slip_dialog(veh, mat, tare, ts):
    gate_pass_slip(veh, mat, tare, ts, load("print_settings", {}))


@st.dialog("Transaction Details", width="large")
def ticket_dialog(tx, veh, mat):
    components.html(ticket_html(tx, veh, mat), height=380, scrolling=True)


def page_transactions():
    vehicles, materials = load("vehicles", []), load("materials", [])
    all_tx = sorted(load("transactions", []), key=lambda t: t["createdAt"], reverse=True)
    st.title("Transaction History")
    st.caption(f"{len(all_tx)} total transactions")

    if "slip" in st.session_state:
        final_slip_dialog(st.session_state.pop("slip"))

    c1, c2, c3, c4 = st.columns([3, 2, 1, 1])
    q = c1.text_input("Search", placeholder="Search ID, vehicle, material...", label_visibility="collapsed").lower()
    sf = c2.selectbox("Status", ["all"] + STATUSES, label_visibility="collapsed",
                      format_func=lambda s: "All Status" if s == "all" else STATUS_LABEL[s])

    rows = []
    for tx in all_tx:
        veh, mat, tare, gross = tx_display(tx, vehicles, materials)
        if q and not (q in tx["id"].lower() or q in veh.lower() or q in mat.lower()):
            continue
        if sf != "all" and tx["status"] != sf:
            continue
        rows.append(dict(tx=tx, Vehicle=veh, Material=mat, **{"Tare (kg)": tare, "Gross (kg)": gross},
                         **{"Net (kg)": tx.get("netWeight")}, Status=STATUS_LABEL.get(tx["status"], tx["status"]),
                         Created=fmt_dt(tx["createdAt"]), ID=tx["id"]))

    export = pd.DataFrame([{k: v for k, v in r.items() if k != "tx"} for r in rows])
    c3.download_button("Export CSV", export.to_csv(index=False).encode(),
                       f"transactions-{datetime.now(TZ):%Y-%m-%d}.csv", "text/csv",
                       use_container_width=True, disabled=export.empty)
    if c4.button("Delete All", type="primary", use_container_width=True, disabled=not all_tx):
        delete_all_dialog(len(all_tx))

    pages = max(1, -(-len(rows) // PAGE_SIZE))
    page = st.number_input("Page", 1, pages, 1) if pages > 1 else 1
    chunk = rows[(page - 1) * PAGE_SIZE: page * PAGE_SIZE]
    if not chunk:
        st.info("No transactions found.")
        return
    df = pd.DataFrame([{k: v for k, v in r.items() if k != "tx"} for r in chunk])
    ev = st.dataframe(df, hide_index=True, use_container_width=True, on_select="rerun",
                      selection_mode="single-row", key=f"tx_table_{page}_{sf}_{q}")
    sel = ev.selection.rows
    if not sel:
        st.caption("Select a row to view, reprint, edit or delete.")
        return
    tx = chunk[sel[0]]["tx"]
    veh, mat = chunk[sel[0]]["Vehicle"], chunk[sel[0]]["Material"]
    a, b, c, d = st.columns(4)
    if a.button("👁 View", use_container_width=True):
        gp_slip_dialog(veh, mat, tx.get("firstWeight"), tx.get("firstWeighTime") or tx["createdAt"]) if parse_gp(tx.get("remarks")) else ticket_dialog(tx, veh, mat)
    if b.button("🖨 Reprint", use_container_width=True):
        gp = parse_gp(tx.get("remarks"))
        if gp and tx["status"] == "completed" and tx.get("secondWeight") is not None:
            final_slip_dialog(dict(date=fmt_dt(tx.get("completedAt")), material=mat, vehicle=veh,
                                   tare=fmt_num(tx.get("firstWeight")), gross=fmt_num(tx["secondWeight"]),
                                   net=fmt_num(tx.get("netWeight"))))
        elif gp:
            gp_slip_dialog(veh, mat, tx.get("firstWeight"), tx.get("firstWeighTime") or tx["createdAt"])
        else:
            ticket_dialog(tx, veh, mat)
    if c.button("✏️ Edit", use_container_width=True):
        edit_dialog(tx)
    if d.button("🗑 Delete", use_container_width=True):
        delete_dialog(tx)


# ----------------------------------------------------------- Management
@st.dialog("Vehicle")
def vehicle_dialog(v):
    plate = st.text_input("Plate Number", v["plateNumber"] if v else "")
    wt = st.number_input("Tare Weight (kg)", min_value=0.0, step=1.0, value=float(v["grossWeight"]) if v else 0.0)
    ty = st.selectbox("Vehicle Type", VEHICLE_TYPES, index=VEHICLE_TYPES.index(v["vehicleType"]) if v else 0)
    if st.button("Save", type="primary"):
        if not plate.strip() or wt <= 0:
            st.error("All fields required")
            return
        vs = load("vehicles", [])
        if v:
            vs = [{**x, "plateNumber": plate.strip(), "grossWeight": wt, "vehicleType": ty} if x["id"] == v["id"] else x for x in vs]
        else:
            vs.append(dict(id=new_id("V"), plateNumber=plate.strip(), grossWeight=wt, vehicleType=ty,
                           isActive=True, createdAt=now_ms()))
        save("vehicles", vs)
        st.rerun()


@st.dialog("Material")
def material_dialog(m):
    name = st.text_input("Name", m["name"] if m else "")
    cat = st.text_input("Category", m["category"] if m else "")
    unit = st.selectbox("Unit", UNITS, index=UNITS.index(m["unit"]) if m else 1)
    if st.button("Save", type="primary"):
        if not name.strip() or not cat.strip():
            st.error("All fields required")
            return
        ms = load("materials", [])
        if m:
            ms = [{**x, "name": name.strip(), "category": cat.strip(), "unit": unit} if x["id"] == m["id"] else x for x in ms]
        else:
            ms.append(dict(id=new_id("M"), name=name.strip(), category=cat.strip(), unit=unit,
                           isActive=True, createdAt=now_ms()))
        save("materials", ms)
        st.rerun()


@st.dialog("Confirm delete")
def confirm_delete(kind, item, label):
    st.write(f"Permanently delete {kind} **{label}**?")
    c1, c2 = st.columns(2)
    if c1.button("Delete", type="primary", use_container_width=True):
        key = "vehicles" if kind == "vehicle" else "materials"
        save(key, [x for x in load(key, []) if x["id"] != item["id"]])
        st.rerun()
    if c2.button("Cancel", use_container_width=True):
        st.rerun()


def _entity_tab(kind, key, cols, edit_fn, label_fn, to_df, import_cb=None):
    items = load(key, [])
    top = st.columns([4, 1, 1] if import_cb else [5, 1])
    top[0].subheader(f"{kind.title()}s ({len(items)})")
    if top[-1].button(f"➕ Add {kind.title()}", use_container_width=True):
        edit_fn(None)
    if import_cb:
        top[1].download_button("Export CSV", to_df(items).to_csv(index=False).encode(),
                               f"{kind}s.csv", "text/csv", use_container_width=True)
        up = st.file_uploader("Import CSV", type="csv", key=f"imp_{kind}")
        st.caption("Columns: Plate Number, Tare Weight (kg), Vehicle Type (truck / tanker / trailer / other). Duplicate plates skipped.")
        if up is not None and st.button("Run import"):
            import_cb(up)
    if not items:
        st.info(f"No {kind}s yet.")
        return
    ev = st.dataframe(to_df(items), hide_index=True, use_container_width=True,
                      on_select="rerun", selection_mode="single-row", key=f"tbl_{kind}")
    if ev.selection.rows:
        it = items[ev.selection.rows[0]]
        a, b, c = st.columns(3)
        if a.button("✏️ Edit", key=f"e_{kind}", use_container_width=True):
            edit_fn(it)
        if b.button("Set " + ("Inactive" if it["isActive"] else "Active"), key=f"t_{kind}", use_container_width=True):
            save(key, [{**x, "isActive": not x["isActive"]} if x["id"] == it["id"] else x for x in items])
            st.rerun()
        if c.button("🗑 Delete", key=f"d_{kind}", use_container_width=True):
            confirm_delete(kind, it, label_fn(it))


def import_vehicles(up):
    try:
        df = pd.read_csv(up)
        cols = {c.lower().strip(): c for c in df.columns}
        pc = next((cols[c] for c in cols if "plate" in c), None)
        wc = next((cols[c] for c in cols if "tare" in c or "weight" in c), None)
        tc = next((cols[c] for c in cols if "type" in c), None)
        if not pc or not wc:
            st.error("CSV needs columns: Plate Number, Tare Weight (kg), Vehicle Type")
            return
    except Exception:
        st.error("Failed to parse file. Please check the format.")
        return
    vs = load("vehicles", [])
    plates = {v["plateNumber"].upper() for v in vs}
    ok = skipped = 0
    for _, r in df.iterrows():
        plate = str(r[pc]).strip()
        try:
            w = float(r[wc])
        except (TypeError, ValueError):
            w = 0
        ty = str(r[tc]).strip().lower() if tc else "truck"
        ty = ty if ty in VEHICLE_TYPES else "other"
        if not plate or plate == "nan" or w <= 0 or plate.upper() in plates:
            skipped += 1
            continue
        vs.append(dict(id=new_id("V"), plateNumber=plate, grossWeight=w, vehicleType=ty,
                       isActive=True, createdAt=now_ms()))
        plates.add(plate.upper())
        ok += 1
    save("vehicles", vs)
    (st.success if ok else st.warning)(f"Imported {ok} vehicle(s). {skipped} row(s) skipped (duplicate or invalid).")


def tab_backup():
    vs, ms, ts = load("vehicles", []), load("materials", []), load("transactions", [])
    with st.container(border=True):
        st.markdown("**Export Backup**")
        st.caption("Streamlit Cloud disk is ephemeral. Export regularly.")
        payload = dict(version=1, exportedAt=datetime.now(TZ).isoformat(), vehicles=vs, materials=ms, transactions=ts)
        st.download_button(
            f"Export Backup ({len(vs)} vehicles, {len(ms)} materials, {len(ts)} transactions)",
            json.dumps(payload, indent=2), f"weighbridge-backup-{datetime.now(TZ):%Y-%m-%d}.json",
            "application/json")
    with st.container(border=True):
        st.markdown("**Restore Backup**")
        up = st.file_uploader("Backup JSON", type="json", key="restore_up")
        if up is not None:
            try:
                data = json.load(up)
                assert all(isinstance(data.get(k), list) for k in ("vehicles", "materials", "transactions"))
            except Exception:
                st.error("Invalid backup file. Missing vehicles, materials, or transactions.")
                return
            st.warning(f"Replaces current data with {len(data['vehicles'])} vehicles, "
                       f"{len(data['materials'])} materials, {len(data['transactions'])} transactions.")
            if st.button("Confirm restore", type="primary"):
                save("vehicles", data["vehicles"])
                save("materials", data["materials"])
                save("transactions", data["transactions"])
                save("initialized", True)
                st.success("Restore complete.")
                st.rerun()


def tab_pin():
    with st.form("pin_change", clear_on_submit=True):
        st.markdown("**Change PIN**")
        cur = st.text_input("Current PIN", type="password")
        new = st.text_input("New PIN", type="password")
        conf = st.text_input("Confirm New PIN", type="password")
        if st.form_submit_button("Update PIN"):
            if cur != load("pin", DEFAULT_PIN):
                st.error("Current PIN is incorrect.")
            elif len(new) < 4:
                st.error("New PIN must be at least 4 characters.")
            elif new != conf:
                st.error("PINs do not match.")
            else:
                save("pin", new)
                st.success("PIN updated successfully.")


def tab_print():
    s = load("print_settings", {})
    gp = st.radio("Gate Pass Slip paper", PAPERS, index=PAPERS.index(s.get("gatePass", "A5")),
                  format_func=PAPER_LABEL.get, horizontal=True)
    fw = st.radio("Final Weighing Slip paper", PAPERS, index=PAPERS.index(s.get("finalWeigh", "A5")),
                  format_func=PAPER_LABEL.get, horizontal=True)
    ori = st.radio("Final slip orientation", ["portrait", "landscape"],
                   index=["portrait", "landscape"].index(s.get("estimateOrientation", "portrait")), horizontal=True)
    new = {"gatePass": gp, "finalWeigh": fw, "estimateOrientation": ori}
    if new != s:
        save("print_settings", new)
        st.toast("Print settings saved")


def page_management():
    st.title("Management Panel")
    t1, t2, t3, t4, t5 = st.tabs(["Vehicles", "Materials", "Print Settings", "Backup", "Security"])
    with t1:
        _entity_tab("vehicle", "vehicles", None, vehicle_dialog, lambda v: v["plateNumber"],
                    lambda items: pd.DataFrame([{"Plate Number": v["plateNumber"], "Tare Weight (kg)": v["grossWeight"],
                                                 "Vehicle Type": v["vehicleType"],
                                                 "Status": "Active" if v["isActive"] else "Inactive"} for v in items]),
                    import_vehicles)
    with t2:
        _entity_tab("material", "materials", None, material_dialog, lambda m: m["name"],
                    lambda items: pd.DataFrame([{"Name": m["name"], "Category": m["category"], "Unit": m["unit"],
                                                 "Status": "Active" if m["isActive"] else "Inactive"} for m in items]))
    with t3:
        tab_print()
    with t4:
        tab_backup()
    with t5:
        tab_pin()


# ----------------------------------------------------------------- main
seed()
if pin_gate():
    with st.sidebar:
        st.markdown("### ⚖️ WeighBridge Pro")
        st.caption("Management System")
        page = st.radio("Navigate", ["Gate Pass", "Transactions", "Management"], label_visibility="collapsed")
        st.divider()
        if st.button("🔒 Lock", use_container_width=True):
            st.session_state.unlocked = False
            st.rerun()
    {"Gate Pass": page_gate_pass, "Transactions": page_transactions, "Management": page_management}[page]()
