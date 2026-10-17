"""WeighMaster Pro: Streamlit port of the Caffeine weighbridge app."""

from __future__ import annotations

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components

import store as db

PAGE_SIZE = 10

st.set_page_config(page_title="WeighMaster", page_icon="⚖️", layout="wide")


# ---------------------------------------------------------------- helpers


def flash(key: str) -> None:
    """Show and keep the (kind, text) message stored under session key."""
    msg = st.session_state.get(key)
    if msg:
        kind, text = msg
        (st.error if kind == "error" else st.success)(text)


def show_html(html_str: str, name: str, height: int = 620) -> None:
    components.html(html_str, height=height, scrolling=True)
    st.download_button(
        "Download as HTML",
        html_str.encode("utf-8"),
        file_name=f"{name}.html",
        mime="text/html",
        key=f"dl_{name}",
    )


def section(title: str):
    box = st.container(border=True)
    box.caption(title.upper())
    return box


def vehicle_selector(label: str, key: str, tare_key: str, src_key: str | None = None):
    def on_change():
        vehicle = st.session_state.get(key)
        if not vehicle:
            return
        tare = db.get_vehicle_tare(vehicle)
        if tare is not None:
            st.session_state[tare_key] = float(tare)
            if src_key:
                st.session_state[src_key] = "auto"
        elif src_key:
            st.session_state[src_key] = None

    return st.selectbox(
        label,
        db.vehicle_options(),
        index=None,
        accept_new_options=True,
        placeholder="Type or pick, e.g. MH-12-AB-1234",
        key=key,
        on_change=on_change,
    )


# --------------------------------------------------------------- gate pass


def _gp_submit() -> None:
    ss = st.session_state
    vehicle = (ss.get("gp_vehicle") or "").strip().upper()
    material = ss.get("gp_material")
    tare = float(ss.get("gp_tare") or 0)
    if not vehicle:
        ss.gp_msg = ("error", "Vehicle number is required.")
        return
    if not material:
        ss.gp_msg = ("error", "Please select a material.")
        return
    if tare <= 0:
        ss.gp_msg = ("error", "Enter a valid empty vehicle weight.")
        return
    txn = {
        "id": db.generate_id(),
        "vehicle_number": vehicle,
        "driver_name": "",
        "material": material,
        "gross_weight": 0.0,
        "tare_weight": tare,
        "net_weight": 0.0,
        "entry_time": db.now_iso(),
        "exit_time": None,
        "status": "pending",
        "operator": "Gate",
        "remarks": "Gate Pass Issued",
    }
    db.add_transaction(txn)
    ss.gp_last = txn
    ss.gp_msg = ("success", f"Gate pass {txn['id']} issued and added to pending list.")
    ss.gp_vehicle = None
    ss.gp_material = None
    ss.gp_tare = 0.0


def page_gate_pass() -> None:
    st.title("Gate Pass")
    st.caption("Issue a gate pass and add the vehicle to pending transactions.")
    st.session_state.setdefault("gp_tare", 0.0)

    left, right = st.columns([3, 2], gap="large")
    with left:
        with st.container(border=True):
            vehicle_selector("Vehicle Number", "gp_vehicle", "gp_tare")
            st.selectbox(
                "Material",
                db.get_materials(),
                index=None,
                placeholder="Select material…",
                key="gp_material",
            )
            st.number_input(
                "Empty Vehicle Weight (KG)",
                min_value=0.0,
                step=10.0,
                format="%.0f",
                key="gp_tare",
            )
            st.button(
                "Print Gate Pass",
                type="primary",
                icon=":material/print:",
                on_click=_gp_submit,
            )
            flash("gp_msg")
    with right:
        last = st.session_state.get("gp_last")
        if last:
            st.caption("LAST GATE PASS")
            show_html(db.gate_pass_html(last), f"gate-pass-{last['id']}", 460)


# --------------------------------------------------------- new transaction

NT_KEYS = ("nt_vehicle", "nt_driver", "nt_material", "nt_remarks")


def _nt_tare_changed() -> None:
    st.session_state.nt_tare_src = "manual"


def _nt_confirm_tare() -> None:
    ss = st.session_state
    vehicle = (ss.get("nt_vehicle") or "").strip()
    tare = float(ss.get("nt_tare") or 0)
    if vehicle and tare > 0:
        db.save_vehicle_tare(vehicle, tare)
        ss.nt_tare_src = "confirmed"
        ss.nt_msg = (
            "success",
            f"Tare weight {db.fmt_num(tare)} KG saved for {vehicle.upper()}.",
        )


def _nt_submit() -> None:
    ss = st.session_state
    vehicle = (ss.get("nt_vehicle") or "").strip().upper()
    driver = (ss.get("nt_driver") or "").strip()
    material = ss.get("nt_material")
    tare = float(ss.get("nt_tare") or 0)
    gross = float(ss.get("nt_gross") or 0)

    errors = []
    if not vehicle:
        errors.append("Vehicle number is required.")
    if not driver:
        errors.append("Driver name is required.")
    if not material:
        errors.append("Material type is required.")
    if tare <= 0:
        errors.append("Tare weight is required.")
    if gross > 0 and gross < tare:
        errors.append("Gross weight must be ≥ tare weight.")
    if errors:
        ss.nt_msg = ("error", "  \n".join(errors))
        return

    now = db.now_iso()
    txn = {
        "id": db.generate_id(),
        "vehicle_number": vehicle,
        "driver_name": driver,
        "material": material,
        "gross_weight": gross,
        "tare_weight": tare,
        "net_weight": max(0.0, gross - tare),
        "entry_time": now,
        "exit_time": now if gross > 0 else None,
        "status": "completed" if gross > 0 else "pending",
        "operator": "Admin",
        "remarks": (ss.get("nt_remarks") or "").strip() or None,
    }
    db.add_transaction(txn)
    ss.nt_last = txn
    ss.nt_msg = ("success", f"Transaction {txn['id']} recorded successfully.")
    for k in NT_KEYS:
        ss[k] = None
    ss.nt_tare = 0.0
    ss.nt_gross = 0.0
    ss.nt_tare_src = None


def page_new_transaction() -> None:
    ss = st.session_state
    st.title("New Transaction")
    st.caption("Record a new vehicle weighing transaction.")
    ss.setdefault("nt_tare", 0.0)
    ss.setdefault("nt_gross", 0.0)
    ss.setdefault("nt_tare_src", None)

    left, right = st.columns([3, 2], gap="large")
    with left:
        info = st.container(border=True)
        c1, c2, c3 = info.columns(3)
        c1.metric("Transaction ID", db.generate_id())
        c2.metric("Date & Time", db.fmt_dt(db.now_iso(), short=True))
        c3.metric("Operator", "Admin")

        with section("Vehicle details"):
            a, b = st.columns(2)
            with a:
                vehicle_selector("Vehicle Number *", "nt_vehicle", "nt_tare", "nt_tare_src")
            with b:
                st.text_input("Driver Name *", key="nt_driver", placeholder="Full name")
            st.selectbox(
                "Material Type *",
                db.get_materials(),
                index=None,
                placeholder="Select material",
                key="nt_material",
            )

        with section("Weight details"):
            a, b = st.columns(2)
            with a:
                st.number_input(
                    "Tare Weight (KG) *",
                    min_value=0.0,
                    step=10.0,
                    format="%.0f",
                    key="nt_tare",
                    on_change=_nt_tare_changed,
                )
                src = ss.nt_tare_src
                if src == "auto":
                    st.caption(":green[Auto-filled from vehicle history]")
                elif src == "confirmed":
                    st.caption(":green[Tare weight saved]")
                if (
                    float(ss.nt_tare or 0) > 0
                    and (ss.get("nt_vehicle") or "").strip()
                    and src != "confirmed"
                ):
                    st.button(
                        "Confirm & Save Tare Weight",
                        icon=":material/check_circle:",
                        on_click=_nt_confirm_tare,
                        use_container_width=True,
                    )
            with b:
                st.number_input(
                    "Gross Weight (KG)",
                    min_value=0.0,
                    step=10.0,
                    format="%.0f",
                    key="nt_gross",
                    help="Leave at 0 to save as pending.",
                )
            tare = float(ss.nt_tare or 0)
            gross = float(ss.nt_gross or 0)
            net = db.fmt_num(max(0.0, gross - tare)) if gross > 0 else "------"
            st.markdown(
                "<div style='text-align:center;padding:14px;border-radius:10px;"
                "background:#0B3A20;border:1px solid #22E66A33'>"
                "<div style='font-size:12px;letter-spacing:2px;color:#9AA6AE'>"
                "CALCULATED NET WEIGHT</div>"
                f"<div style='font-size:40px;font-weight:700;color:#22E66A;"
                f"font-family:monospace'>{net}</div>"
                "<div style='color:#22E66A'>KG</div></div>",
                unsafe_allow_html=True,
            )

        with section("Additional info"):
            st.text_area("Remarks (optional)", key="nt_remarks", placeholder="Any additional notes…")

        st.button("Save Transaction", type="primary", on_click=_nt_submit)
        flash("nt_msg")
    with right:
        last = ss.get("nt_last")
        if last:
            st.caption("LAST SLIP")
            show_html(db.slip_html(last), f"slip-{last['id']}", 640)


# ------------------------------------------------------------ transactions


def _status_label(status: str) -> str:
    return "✅ Completed" if status == "completed" else "🟡 Pending"


@st.dialog("Transaction details")
def view_dialog(txn_id: str) -> None:
    t = next((x for x in db.get_transactions() if x["id"] == txn_id), None)
    if not t:
        st.warning("Transaction not found.")
        return
    s = db.get_settings()
    rows = [
        ("Transaction ID", t["id"]),
        ("Vehicle Number", t["vehicle_number"]),
        ("Driver", t.get("driver_name") or "—"),
        ("Material", t["material"]),
        ("Entry Time", db.fmt_dt(t["entry_time"], s)),
        ("Exit Time", db.fmt_dt(t.get("exit_time"), s)),
        ("Gross Weight", f"{db.fmt_num(t['gross_weight'])} KG"),
        ("Tare Weight", f"{db.fmt_num(t['tare_weight'])} KG"),
        ("Net Weight", f"{db.fmt_num(t['net_weight'])} KG"),
        ("Status", t["status"].title()),
        ("Operator", t.get("operator") or "—"),
        ("Remarks", t.get("remarks") or "—"),
    ]
    st.dataframe(
        pd.DataFrame(rows, columns=["Field", "Value"]),
        hide_index=True,
        use_container_width=True,
    )


@st.dialog("Print slip")
def print_dialog(txn_id: str) -> None:
    t = next((x for x in db.get_transactions() if x["id"] == txn_id), None)
    if not t:
        st.warning("Transaction not found.")
        return
    show_html(db.slip_html(t), f"slip-{t['id']}", 640)


@st.dialog("Edit transaction")
def edit_dialog(txn_id: str) -> None:
    t = next((x for x in db.get_transactions() if x["id"] == txn_id), None)
    if not t:
        st.warning("Transaction not found.")
        return
    st.caption(t["id"])
    a, b = st.columns(2)
    tare = a.number_input(
        "First Weight (Tare) KG", min_value=0.0, step=10.0, format="%.0f",
        value=float(t["tare_weight"]), key=f"e_tare_{txn_id}",
    )
    gross = b.number_input(
        "Last Weight (Gross) KG", min_value=0.0, step=10.0, format="%.0f",
        value=float(t["gross_weight"]), key=f"e_gross_{txn_id}",
    )
    st.info(f"Net Weight: {db.fmt_num(max(0.0, gross - tare))} KG")
    a, b = st.columns(2)
    vehicle = a.text_input("Vehicle Number", value=t["vehicle_number"], key=f"e_veh_{txn_id}")
    driver = b.text_input("Driver Name", value=t.get("driver_name", ""), key=f"e_drv_{txn_id}")
    materials = db.get_materials()
    if t["material"] not in materials:
        materials = [*materials, t["material"]]
    material = st.selectbox(
        "Material", materials, index=materials.index(t["material"]), key=f"e_mat_{txn_id}"
    )
    remarks = st.text_input("Remarks", value=t.get("remarks") or "", key=f"e_rem_{txn_id}")

    if st.button("Save", type="primary", key=f"e_save_{txn_id}"):
        if gross > 0 and gross < tare:
            st.error("Last Weight (Gross) must be ≥ First Weight (Tare).")
            return
        db.update_transaction(
            txn_id,
            {
                "gross_weight": gross,
                "tare_weight": tare,
                "net_weight": max(0.0, gross - tare),
                "driver_name": driver.strip(),
                "vehicle_number": vehicle.strip().upper(),
                "material": material,
                "status": "completed" if gross > 0 else "pending",
                "exit_time": (t.get("exit_time") or db.now_iso()) if gross > 0 else None,
                "remarks": remarks.strip() or None,
            },
        )
        st.session_state.tx_msg = ("success", "Transaction updated.")
        st.rerun()


@st.dialog("Delete transaction")
def delete_dialog(txn_id: str) -> None:
    st.write(f"Delete transaction **{txn_id}**? This cannot be undone.")
    a, b = st.columns(2)
    if a.button("Delete", type="primary", key=f"d_yes_{txn_id}"):
        db.delete_transaction(txn_id)
        st.session_state.tx_msg = ("success", "Transaction deleted.")
        st.rerun()
    if b.button("Cancel", key=f"d_no_{txn_id}"):
        st.rerun()


@st.dialog("Clear all data")
def clear_dialog() -> None:
    st.write("This permanently deletes **all** transaction records.")
    if st.button("Yes, delete everything", type="primary", key="clear_yes"):
        db.clear_transactions()
        st.session_state.tx_msg = ("success", "All transactions cleared.")
        st.rerun()
    if st.button("Cancel", key="clear_no"):
        st.rerun()


def _reset_page() -> None:
    st.session_state.tx_page = 1


def page_transactions() -> None:
    ss = st.session_state
    s = db.get_settings()
    txns = db.get_transactions()

    head, act1, act2 = st.columns([4, 1, 1], vertical_alignment="bottom")

    with st.container(border=True):
        c1, c2, c3, c4 = st.columns([3, 1.4, 1.4, 1.4])
        search = c1.text_input(
            "Search", placeholder="Vehicle, driver, material, ID…",
            key="tx_search", on_change=_reset_page,
        )
        status = c2.selectbox(
            "Status", ["All", "Completed", "Pending"], key="tx_status", on_change=_reset_page
        )
        d_from = c3.date_input("From", value=None, key="tx_from", on_change=_reset_page)
        d_to = c4.date_input("To", value=None, key="tx_to", on_change=_reset_page)

    q = (search or "").strip().lower()
    rows = []
    for t in txns:
        if q and not any(
            q in str(t.get(f, "")).lower()
            for f in ("vehicle_number", "driver_name", "material", "id")
        ):
            continue
        if status != "All" and t["status"] != status.lower():
            continue
        day = db.parse_dt(t["entry_time"], s).date()
        if d_from and day < d_from:
            continue
        if d_to and day > d_to:
            continue
        rows.append(t)

    with head:
        st.title("Transactions")
        st.caption(f"{len(rows)} records found")
    act1.download_button(
        "Export CSV",
        db.transactions_csv(rows, s),
        file_name="weighbridge-transactions.csv",
        mime="text/csv",
        icon=":material/download:",
        disabled=not rows,
    )
    if act2.button("Clear All Data", icon=":material/delete:", disabled=not txns):
        clear_dialog()

    flash_msg = ss.pop("tx_msg", None)
    if flash_msg:
        st.success(flash_msg[1])

    pages = max(1, -(-len(rows) // PAGE_SIZE))
    ss.setdefault("tx_page", 1)
    ss.tx_page = min(max(1, ss.tx_page), pages)
    start = (ss.tx_page - 1) * PAGE_SIZE
    page_rows = rows[start : start + PAGE_SIZE]

    if not page_rows:
        st.info("No transactions match your filters.")
        return

    table = pd.DataFrame(
        {
            "Txn ID": [t["id"] for t in page_rows],
            "Date/Time": [db.fmt_dt(t["entry_time"], s, short=True) for t in page_rows],
            "Vehicle": [t["vehicle_number"] for t in page_rows],
            "Driver": [t.get("driver_name", "") for t in page_rows],
            "Material": [t["material"] for t in page_rows],
            "Gross (KG)": [t["gross_weight"] or None for t in page_rows],
            "Tare (KG)": [t["tare_weight"] for t in page_rows],
            "Net (KG)": [t["net_weight"] or None for t in page_rows],
            "Status": [_status_label(t["status"]) for t in page_rows],
        }
    )
    sig = hash((q, status, str(d_from), str(d_to), ss.tx_page, len(rows)))
    event = st.dataframe(
        table,
        hide_index=True,
        use_container_width=True,
        on_select="rerun",
        selection_mode="single-row",
        key=f"tx_table_{sig}",
        column_config={
            "Gross (KG)": st.column_config.NumberColumn(format="%,.0f"),
            "Tare (KG)": st.column_config.NumberColumn(format="%,.0f"),
            "Net (KG)": st.column_config.NumberColumn(format="%,.0f"),
        },
    )

    f1, f2 = st.columns([5, 1], vertical_alignment="center")
    f1.caption(f"Page {ss.tx_page} of {pages} ({len(rows)} records)")
    f2.number_input("Page", 1, pages, key="tx_page", label_visibility="collapsed")

    picked = event.selection.rows
    if not picked:
        st.caption("Select a row to view, print, edit or delete it.")
        return
    t = page_rows[picked[0]]
    st.markdown(f"**Selected:** `{t['id']}` · {t['vehicle_number']}")
    b1, b2, b3, b4, _ = st.columns([1, 1, 1, 1, 4])
    if b1.button("View", icon=":material/visibility:", use_container_width=True):
        view_dialog(t["id"])
    if b2.button("Print", icon=":material/print:", use_container_width=True):
        print_dialog(t["id"])
    if b3.button("Edit", icon=":material/edit:", use_container_width=True):
        edit_dialog(t["id"])
    if b4.button("Delete", icon=":material/delete:", use_container_width=True):
        delete_dialog(t["id"])


# ----------------------------------------------------------------- reports


def page_reports() -> None:
    s = db.get_settings()
    txns = db.get_transactions()
    st.title("Reports")
    st.caption("Summary analytics and weight statistics.")

    names = {"daily": "Last 14 Days", "weekly": "Last 12 Weeks", "monthly": "Last 12 Months"}
    tabs = st.tabs(["Daily", "Weekly", "Monthly"])
    for tab, period in zip(tabs, names):
        with tab:
            data = db.build_period_data(txns, period, s)
            total = {
                k: sum(d[k] for d in data)
                for k in ("transactions", "gross", "tare", "net")
            }
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("Total Transactions", total["transactions"], names[period], delta_color="off")
            for col, label, key in (
                (m2, "Total Gross Weight", "gross"),
                (m3, "Total Tare Weight", "tare"),
                (m4, "Total Net Weight", "net"),
            ):
                col.metric(label, f"{total[key] / 1000:.1f} MT", f"{db.fmt_num(total[key])} KG", delta_color="off")

            with st.container(border=True):
                st.caption("NET WEIGHT OVER TIME (KG)")
                recent = pd.DataFrame(data[-7:]).set_index("label")
                st.bar_chart(
                    recent[["net", "gross"]].rename(
                        columns={"net": "Net Weight", "gross": "Gross Weight"}
                    ),
                    color=["#22E66A", "#1F7A44"],
                    stack=False,
                )

            active = [d for d in data if d["transactions"] > 0]
            if active:
                st.dataframe(
                    pd.DataFrame(active).rename(
                        columns={
                            "label": "Period",
                            "transactions": "Transactions",
                            "gross": "Gross Weight (KG)",
                            "tare": "Tare Weight (KG)",
                            "net": "Net Weight (KG)",
                        }
                    ),
                    hide_index=True,
                    use_container_width=True,
                )
            else:
                st.info("No data for this period.")
            st.download_button(
                "Export CSV",
                db.report_csv(data),
                file_name=f"weighbridge-report-{period}.csv",
                mime="text/csv",
                icon=":material/download:",
                key=f"rep_dl_{period}",
            )


# ---------------------------------------------------------------- settings


def page_settings() -> None:
    st.title("Settings")
    st.caption("Configure company and weighbridge details.")
    s = db.get_settings()

    with st.form("settings_form"):
        st.caption("COMPANY INFORMATION")
        company = st.text_input("Company Name", s["company_name"])
        address = st.text_input("Address", s["address"])
        a, b = st.columns(2)
        city = a.text_input("City / State", s["city"])
        phone = b.text_input("Phone Number", s["phone"])
        st.caption("WEIGHBRIDGE DETAILS")
        a, b = st.columns(2)
        wb_name = a.text_input("Weighbridge Name", s["weighbridge_name"])
        wb_loc = b.text_input("Location / Gate", s["weighbridge_location"])
        lic = a.text_input("License Number", s["license_number"])
        unit = b.selectbox(
            "Weight Unit (shown on slips)",
            db.UNITS,
            index=db.UNITS.index(s["unit"]) if s["unit"] in db.UNITS else 0,
            format_func=lambda u: {"KG": "KG — Kilograms", "MT": "MT — Metric Tonnes", "LB": "LB — Pounds"}[u],
        )
        tz = st.text_input("Time zone (IANA name)", s["timezone"], help="e.g. Asia/Kolkata")
        if st.form_submit_button("Save Settings", type="primary", icon=":material/save:"):
            try:
                db.ZoneInfo(tz.strip())
            except Exception:
                st.error("Unknown time zone. Use a name like Asia/Kolkata.")
            else:
                db.save_settings(
                    {
                        "company_name": company,
                        "address": address,
                        "city": city,
                        "phone": phone,
                        "weighbridge_name": wb_name,
                        "weighbridge_location": wb_loc,
                        "license_number": lic,
                        "unit": unit,
                        "timezone": tz.strip(),
                    }
                )
                st.success("Settings saved successfully.")

    with section("Material types"):
        with st.form("material_form", clear_on_submit=True):
            c1, c2 = st.columns([4, 1], vertical_alignment="bottom")
            new = c1.text_input("New material", placeholder="Enter new material name")
            if c2.form_submit_button("Add", icon=":material/add:", use_container_width=True):
                if not new.strip():
                    st.warning("Enter a name.")
                elif not db.add_material(new):
                    st.error("Material already exists.")
                else:
                    st.rerun()
        for m in db.get_materials():
            c1, c2 = st.columns([8, 1], vertical_alignment="center")
            c1.write(m)
            if c2.button("", icon=":material/delete:", key=f"mat_del_{m}", help=f"Delete {m}"):
                db.delete_material(m)
                st.rerun()

    with section("Vehicle tare registry"):
        registry = db.get_registry()
        df = pd.DataFrame(
            {"Vehicle Number": list(registry), "Tare (kg)": [float(v) for v in registry.values()]}
        )
        edited = st.data_editor(
            df,
            num_rows="dynamic",
            hide_index=True,
            use_container_width=True,
            key="reg_editor",
            column_config={
                "Tare (kg)": st.column_config.NumberColumn(min_value=0.0, format="%.0f"),
            },
        )
        c1, c2 = st.columns([1, 1])
        if c1.button("Save registry", type="primary", icon=":material/save:"):
            new_reg, bad = {}, 0
            for _, r in edited.iterrows():
                vn = str(r["Vehicle Number"] or "").strip().upper()
                tare = r["Tare (kg)"]
                if not vn or vn == "NAN" or pd.isna(tare) or float(tare) <= 0:
                    bad += 1
                    continue
                new_reg[vn] = float(tare)
            db.set_registry(new_reg)
            st.success(f"Saved {len(new_reg)} vehicles" + (f" ({bad} invalid rows skipped)." if bad else "."))
            st.rerun()
        c2.download_button(
            "Export CSV",
            db.registry_csv(registry),
            file_name="vehicle_tare_registry.csv",
            mime="text/csv",
            icon=":material/download:",
        )
        up = st.file_uploader("Import CSV (vehicle_number,tare_weight)", type="csv", key="reg_up")
        if up and st.button("Import file", icon=":material/upload:"):
            imported, bad = db.parse_registry_csv(up.getvalue().decode("utf-8-sig", "replace"))
            if not imported:
                st.error("No valid rows found in CSV.")
            else:
                db.set_registry({**registry, **imported})
                st.success(
                    f"Imported {len(imported)} vehicle(s)" + (f" ({bad} rows skipped)." if bad else ".")
                )
                st.rerun()

    with section("Backup & restore"):
        st.warning(
            "Streamlit Community Cloud storage is temporary. The app's data file is "
            "wiped on reboot or redeploy. Download a backup regularly.",
            icon="⚠️",
        )
        st.download_button(
            "Download full backup (JSON)",
            db.export_db_json(),
            file_name="weighmaster-backup.json",
            mime="application/json",
            icon=":material/download:",
        )
        bk = st.file_uploader("Restore from backup", type="json", key="bk_up")
        if bk and st.button("Restore (replaces all data)", icon=":material/restore:"):
            err = db.restore_db_json(bk.getvalue())
            if err:
                st.error(err)
            else:
                st.success("Backup restored.")
                st.rerun()

    with section("System information"):
        for k, v in (
            ("Application", "WeighMaster Pro v2.0 (Streamlit)"),
            ("Storage", f"JSON file ({db.DATA_FILE.name})"),
            ("Platform", "Streamlit Community Cloud"),
        ):
            c1, c2 = st.columns([1, 2])
            c1.caption(k)
            c2.write(v)


# ------------------------------------------------------------------- shell

pages = [
    st.Page(page_gate_pass, title="Gate Pass", icon=":material/print:", url_path="gate-pass", default=True),
    st.Page(page_new_transaction, title="New Transaction", icon=":material/add_circle:", url_path="new-transaction"),
    st.Page(page_transactions, title="Transactions", icon=":material/list:", url_path="transactions"),
    st.Page(page_reports, title="Reports", icon=":material/bar_chart:", url_path="reports"),
    st.Page(page_settings, title="Settings", icon=":material/settings:", url_path="settings"),
]
current = st.navigation(pages)

with st.sidebar:
    cfg = db.get_settings()
    st.divider()
    st.markdown(f"**WeighMaster** · v2.0 Pro  \n{cfg['company_name']}  \n{cfg['weighbridge_name']}")

current.run()
