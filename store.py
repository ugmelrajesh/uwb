"""WeighMaster storage, slips, reports and CSV helpers.

Pure Python: no Streamlit import, so it can be tested on its own.
Data lives in one JSON file (see DATA_FILE).
"""

from __future__ import annotations

import csv
import html
import io
import json
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

DATA_FILE = Path(
    os.environ.get(
        "WEIGHMASTER_DATA", Path(__file__).resolve().parent / "data" / "store.json"
    )
)

DEFAULT_MATERIALS = [
    "Coal",
    "Sand",
    "Gravel",
    "Iron Ore",
    "Wheat",
    "Rice",
    "Cotton",
    "Cement",
    "Limestone",
    "Fertilizer",
    "Other",
]

DEFAULT_SETTINGS = {
    "company_name": "ABC Logistics Pvt. Ltd.",
    "address": "12 Industrial Estate, Sector 5",
    "city": "Mumbai, Maharashtra 400001",
    "phone": "+91 22 4567 8900",
    "weighbridge_name": "Weighbridge Unit #1",
    "weighbridge_location": "Gate No. 1 - Main Entry",
    "unit": "KG",
    "license_number": "WB-MH-2024-001",
    "timezone": "Asia/Kolkata",
}

UNITS = ["KG", "MT", "LB"]


# ---------------------------------------------------------------- storage


def load_db() -> dict:
    try:
        raw = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raw = {}
    except Exception:
        raw = {}
    materials = raw.get("materials")
    if not isinstance(materials, list) or not materials:
        materials = list(DEFAULT_MATERIALS)
    txns = raw.get("transactions")
    registry = raw.get("vehicle_tare")
    return {
        "settings": {**DEFAULT_SETTINGS, **(raw.get("settings") or {})},
        "materials": materials,
        "transactions": txns if isinstance(txns, list) else [],
        "vehicle_tare": registry if isinstance(registry, dict) else {},
    }


def save_db(db: dict) -> None:
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=DATA_FILE.parent, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(db, f, indent=2)
    os.replace(tmp, DATA_FILE)


def export_db_json() -> bytes:
    return json.dumps(load_db(), indent=2).encode("utf-8")


def restore_db_json(data: bytes) -> str | None:
    """Replace all data from a backup. Returns an error text or None."""
    try:
        raw = json.loads(data.decode("utf-8"))
    except Exception:
        return "File is not valid JSON."
    if not isinstance(raw, dict) or not {"transactions", "settings"} & set(raw):
        return "File is not a WeighMaster backup."
    txns = raw.get("transactions", [])
    if not isinstance(txns, list):
        return "Backup has a bad transactions list."
    need = {"id", "vehicle_number", "material", "entry_time", "status"}
    for t in txns:
        if not isinstance(t, dict) or not need <= set(t):
            return "Backup has a transaction with missing fields."
    save_db(
        {
            "settings": {**DEFAULT_SETTINGS, **(raw.get("settings") or {})},
            "materials": raw.get("materials") or list(DEFAULT_MATERIALS),
            "transactions": txns,
            "vehicle_tare": raw.get("vehicle_tare") or {},
        }
    )
    return None


# --------------------------------------------------------------- settings


def get_settings() -> dict:
    return load_db()["settings"]


def save_settings(s: dict) -> None:
    db = load_db()
    db["settings"] = {**DEFAULT_SETTINGS, **s}
    save_db(db)


def get_tz(s: dict | None = None) -> ZoneInfo:
    s = s or get_settings()
    try:
        return ZoneInfo(s.get("timezone") or "Asia/Kolkata")
    except Exception:
        return ZoneInfo("UTC")


def now_iso(s: dict | None = None) -> str:
    return datetime.now(get_tz(s)).isoformat(timespec="seconds")


def parse_dt(iso: str, s: dict | None = None) -> datetime:
    dt = datetime.fromisoformat(iso)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(get_tz(s))


def fmt_dt(iso: str | None, s: dict | None = None, short: bool = False) -> str:
    if not iso:
        return "—"
    pattern = "%d/%m/%y %H:%M" if short else "%d/%m/%Y %H:%M:%S"
    return parse_dt(iso, s).strftime(pattern)


def fmt_num(n) -> str:
    n = float(n or 0)
    return f"{int(n):,}" if n == int(n) else f"{n:,.2f}"


# -------------------------------------------------------------- materials


def get_materials() -> list[str]:
    return load_db()["materials"]


def add_material(name: str) -> bool:
    name = name.strip()
    db = load_db()
    if not name or name.lower() in (m.lower() for m in db["materials"]):
        return False
    db["materials"].append(name)
    save_db(db)
    return True


def delete_material(name: str) -> None:
    db = load_db()
    db["materials"] = [m for m in db["materials"] if m != name]
    save_db(db)


# ------------------------------------------------------------ transactions


def get_transactions() -> list[dict]:
    return load_db()["transactions"]


def generate_id(txns: list[dict] | None = None) -> str:
    txns = get_transactions() if txns is None else txns
    biggest = 0
    for t in txns:
        try:
            biggest = max(biggest, int(str(t["id"]).replace("WB-", "")))
        except ValueError:
            pass
    return f"WB-{biggest + 1:06d}"


def add_transaction(txn: dict) -> None:
    db = load_db()
    if txn["tare_weight"] > 0:
        db["vehicle_tare"][txn["vehicle_number"].strip().upper()] = txn["tare_weight"]
    db["transactions"].insert(0, txn)
    save_db(db)


def update_transaction(txn_id: str, updates: dict) -> None:
    db = load_db()
    for i, t in enumerate(db["transactions"]):
        if t["id"] == txn_id:
            t = {**t, **updates}
            db["transactions"][i] = t
            if updates.get("tare_weight", 0) > 0:
                db["vehicle_tare"][t["vehicle_number"].strip().upper()] = updates[
                    "tare_weight"
                ]
            break
    save_db(db)


def delete_transaction(txn_id: str) -> None:
    db = load_db()
    db["transactions"] = [t for t in db["transactions"] if t["id"] != txn_id]
    save_db(db)


def clear_transactions() -> None:
    db = load_db()
    db["transactions"] = []
    save_db(db)


# ------------------------------------------------------ vehicle tare registry


def get_registry() -> dict[str, float]:
    return load_db()["vehicle_tare"]


def set_registry(registry: dict[str, float]) -> None:
    db = load_db()
    db["vehicle_tare"] = registry
    save_db(db)


def save_vehicle_tare(vehicle: str, tare: float) -> None:
    db = load_db()
    db["vehicle_tare"][vehicle.strip().upper()] = tare
    save_db(db)


def get_vehicle_tare(vehicle: str) -> float | None:
    key = (vehicle or "").strip().upper()
    if not key:
        return None
    db = load_db()
    if key in db["vehicle_tare"]:
        return db["vehicle_tare"][key]
    for t in db["transactions"]:
        if t["vehicle_number"].upper() == key and t.get("tare_weight", 0) > 0:
            return t["tare_weight"]
    return None


def vehicle_options() -> list[str]:
    db = load_db()
    names = set(db["vehicle_tare"]) | {
        t["vehicle_number"].upper() for t in db["transactions"]
    }
    return sorted(names)


def parse_registry_csv(text: str) -> tuple[dict[str, float], int]:
    """Parse 'vehicle_number,tare_weight' rows. Returns (rows, skipped)."""
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if lines and lines[0].lower().startswith("vehicle"):
        lines = lines[1:]
    out: dict[str, float] = {}
    bad = 0
    for line in lines:
        parts = line.split(",")
        vn = parts[0].strip().upper() if parts else ""
        try:
            tare = float(parts[1].strip())
        except (IndexError, ValueError):
            tare = 0.0
        if not vn or tare <= 0:
            bad += 1
            continue
        out[vn] = tare
    return out, bad


def registry_csv(registry: dict[str, float]) -> bytes:
    lines = ["vehicle_number,tare_weight"]
    lines += [f"{vn},{fmt_num(t).replace(',', '')}" for vn, t in registry.items()]
    return "\n".join(lines).encode("utf-8")


# -------------------------------------------------------------------- CSV


def _csv_bytes(headers: list[str], rows: list[list]) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, quoting=csv.QUOTE_ALL)
    w.writerow(headers)
    w.writerows(rows)
    return buf.getvalue().encode("utf-8-sig")


def transactions_csv(txns: list[dict], s: dict | None = None) -> bytes:
    headers = [
        "Transaction ID",
        "Entry Date/Time",
        "Exit Date/Time",
        "Vehicle Number",
        "Driver Name",
        "Material",
        "Gross Weight (KG)",
        "Tare Weight (KG)",
        "Net Weight (KG)",
        "Status",
        "Operator",
        "Remarks",
    ]
    rows = [
        [
            t["id"],
            fmt_dt(t["entry_time"], s),
            fmt_dt(t.get("exit_time"), s) if t.get("exit_time") else "",
            t["vehicle_number"],
            t.get("driver_name", ""),
            t["material"],
            t.get("gross_weight", 0),
            t.get("tare_weight", 0),
            t.get("net_weight", 0),
            t["status"],
            t.get("operator", ""),
            t.get("remarks") or "",
        ]
        for t in txns
    ]
    return _csv_bytes(headers, rows)


def report_csv(data: list[dict]) -> bytes:
    headers = [
        "Period",
        "Transactions",
        "Gross Weight (KG)",
        "Tare Weight (KG)",
        "Net Weight (KG)",
    ]
    rows = [
        [d["label"], d["transactions"], d["gross"], d["tare"], d["net"]] for d in data
    ]
    return _csv_bytes(headers, rows)


# ---------------------------------------------------------------- reports


def _month_start(d: date, back: int) -> date:
    idx = d.year * 12 + (d.month - 1) - back
    return date(idx // 12, idx % 12 + 1, 1)


def build_period_data(txns: list[dict], period: str, s: dict | None = None) -> list[dict]:
    """period: daily (14 days), weekly (12 weeks, Mon start), monthly (12 months)."""
    s = s or get_settings()
    today = datetime.now(get_tz(s)).date()
    dated = [(parse_dt(t["entry_time"], s).date(), t) for t in txns]

    if period == "daily":
        buckets = [(today - timedelta(days=i)) for i in range(13, -1, -1)]
        key = lambda d: d  # noqa: E731
        label = lambda b: b.strftime("%d/%m")  # noqa: E731
    elif period == "weekly":
        this_week = today - timedelta(days=today.weekday())
        buckets = [this_week - timedelta(weeks=i) for i in range(11, -1, -1)]
        key = lambda d: d - timedelta(days=d.weekday())  # noqa: E731
        label = lambda b: f"W{b.isocalendar()[1]:02d}"  # noqa: E731
    else:
        buckets = [_month_start(today, i) for i in range(11, -1, -1)]
        key = lambda d: d.replace(day=1)  # noqa: E731
        label = lambda b: b.strftime("%b %y")  # noqa: E731

    out = {b: {"transactions": 0, "gross": 0.0, "tare": 0.0, "net": 0.0} for b in buckets}
    for d, t in dated:
        b = key(d)
        if b in out:
            out[b]["transactions"] += 1
            out[b]["gross"] += t.get("gross_weight", 0)
            out[b]["tare"] += t.get("tare_weight", 0)
            out[b]["net"] += t.get("net_weight", 0)
    return [{"label": label(b), **v} for b, v in out.items()]


# ------------------------------------------------------------------ slips

_PRINT_BAR = (
    '<div class="noprint" style="text-align:center;margin:10px 0">'
    '<button onclick="window.print()" style="padding:6px 18px;font-size:13px;'
    'cursor:pointer">Print</button></div>'
)


def esc(x) -> str:
    return html.escape("" if x is None else str(x))


def slip_html(t: dict, s: dict | None = None) -> str:
    """80 mm thermal weight slip."""
    s = s or get_settings()
    unit = s.get("unit") or "KG"
    completed = t["status"] == "completed"
    tone = "#000" if completed else "#666"

    def row(label, value):
        return (
            f'<div class="row"><span class="label">{esc(label)}:</span>'
            f'<span class="value">{esc(value)}</span></div>'
        )

    def sub(text):
        return f'<div class="company-sub">{esc(text)}</div>' if text else ""

    addr = s.get("address", "")
    if addr and s.get("city"):
        addr = f"{addr}, {s['city']}"
    gross = f"{fmt_num(t['gross_weight'])} {unit}" if t.get("gross_weight", 0) > 0 else "PENDING"
    net = fmt_num(t["net_weight"]) if t.get("net_weight", 0) > 0 else "---"

    parts = [
        f'<div class="company-name">{esc(s.get("company_name") or "WEIGHBRIDGE")}</div>',
        sub(addr),
        sub(f"Tel: {s['phone']}" if s.get("phone") else ""),
        sub(s.get("weighbridge_name")),
        sub(s.get("weighbridge_location")),
        sub(f"Lic No: {s['license_number']}" if s.get("license_number") else ""),
        '<div class="divider-solid"></div>',
        '<div class="center bold" style="font-size:12px;letter-spacing:1px">WEIGHT SLIP</div>',
        '<div class="divider"></div>',
        row("Slip No", t["id"]),
        row("Entry", fmt_dt(t["entry_time"], s)),
        row("Exit", fmt_dt(t["exit_time"], s)) if t.get("exit_time") else "",
        '<div class="divider"></div>',
        row("Vehicle No", t["vehicle_number"]),
        row("Driver", t.get("driver_name", "")),
        row("Material", t["material"]),
        row("Operator", t.get("operator", "")),
        '<div class="divider"></div>',
        row("Gross Wt", gross),
        row("Tare Wt", f"{fmt_num(t['tare_weight'])} {unit}"),
        '<div class="weight-box"><div class="net-label">Net Weight</div>'
        f'<div class="net-value">{net}</div><div class="net-unit">{esc(unit)}</div></div>',
        (row("Remarks", t["remarks"]) + '<div class="divider"></div>') if t.get("remarks") else "",
        f'<div class="stamp"><span class="stamp-text" style="border-color:{tone};color:{tone}">'
        f'{"COMPLETED" if completed else "PENDING"}</span></div>',
        '<div class="sig-line"></div><div class="sig-label">Authorised Signature</div>',
        f'<div class="footer">Printed: {datetime.now(get_tz(s)).strftime("%d/%m/%Y %H:%M:%S")}</div>',
    ]
    return _wrap(f"Weight Slip — {t['id']}", "".join(parts))


def gate_pass_html(t: dict, s: dict | None = None) -> str:
    s = s or get_settings()
    unit = s.get("unit") or "KG"
    body = (
        f'<div class="company-name">{esc((s.get("company_name") or "").upper())}</div>'
        '<div class="center bold" style="font-size:13px;letter-spacing:2px">GATE PASS</div>'
        f'<div class="center" style="font-size:10px;margin-bottom:6px">Issued: {fmt_dt(t["entry_time"], s)}</div>'
        '<div class="divider"></div>'
        f'<div class="row"><span class="label">Vehicle Number</span><span class="value">{esc(t["vehicle_number"])}</span></div>'
        f'<div class="row"><span class="label">Material</span><span class="value">{esc(t["material"])}</span></div>'
        f'<div class="row"><span class="label">Empty Wt (Tare)</span><span class="value">{fmt_num(t["tare_weight"])} {esc(unit)}</span></div>'
        '<div class="divider"></div>'
        '<div style="margin-top:16px;font-size:11px">Authorized Signature:<br>'
        '<div style="margin-top:14px">___________________________</div></div>'
        '<div class="footer">Computer generated document</div>'
    )
    return _wrap(f"Gate Pass — {t['id']}", body)


def _wrap(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html><head><meta charset="UTF-8"><title>{esc(title)}</title>
<style>
* {{ margin:0; padding:0; box-sizing:border-box; }}
body {{ font-family:'Courier New',Courier,monospace; font-size:11px; background:#fff; color:#000;
        width:80mm; max-width:80mm; padding:6mm 4mm; margin:0 auto; }}
.center {{ text-align:center; }} .bold {{ font-weight:bold; }}
.company-name {{ font-size:14px; font-weight:bold; text-align:center; text-transform:uppercase;
                 letter-spacing:1px; margin-bottom:2px; }}
.company-sub {{ font-size:10px; text-align:center; margin-bottom:1px; }}
.divider {{ border-top:1px dashed #000; margin:4px 0; }}
.divider-solid {{ border-top:2px solid #000; margin:4px 0; }}
.row {{ display:flex; justify-content:space-between; margin:2px 0; gap:8px; }}
.label {{ color:#555; }} .value {{ font-weight:bold; text-align:right; }}
.weight-box {{ border:2px solid #000; padding:4px 6px; margin:6px 0; text-align:center; }}
.net-label {{ font-size:10px; text-transform:uppercase; letter-spacing:1px; }}
.net-value {{ font-size:20px; font-weight:bold; margin:2px 0; }}
.net-unit {{ font-size:11px; }}
.stamp {{ text-align:center; margin-top:6px; }}
.stamp-text {{ display:inline-block; border:2px solid #000; font-size:14px; font-weight:bold;
               padding:2px 10px; letter-spacing:3px; }}
.sig-line {{ border-top:1px solid #000; margin:20px auto 0; width:60%; }}
.sig-label {{ text-align:center; font-size:9px; margin-top:2px; }}
.footer {{ font-size:9px; text-align:center; margin-top:6px; color:#666; }}
@media print {{ @page {{ margin:0; size:80mm auto; }} .noprint {{ display:none; }} }}
</style></head><body>{body}{_PRINT_BAR}</body></html>"""
