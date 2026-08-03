from datetime import datetime

from flask import Blueprint, abort, jsonify, redirect, request, send_file

from scanner_diagnostics import frame_path, queue_sound_test, read_status, write_status
from translation import translate
from utils.auth import admin_required
from utils.db import get_db
from utils.render import HTML_START, get_language, render_page


scanner_diagnostics_bp = Blueprint("scanner_diagnostics", __name__)


def _t(key):
    return translate(key, get_language())


@scanner_diagnostics_bp.get("/einstellungen/scanner-diagnose")
@admin_required
def scanner_diagnostics_page():
    return render_page(
        HTML_START + """
        <div class="page-hero"><div><div class="eyebrow">{{ t("scanner_diagnostics") }}</div>
        <h1>{{ t("scanner_reliability") }}</h1><p>{{ t("scanner_diagnostics_desc") }}</p></div>
        <a class="button filter" href="/einstellungen">{{ t("back_to_settings") }}</a></div>
        <div class="stats" id="scanner-stats"></div>
        <div class="card"><h2>{{ t("last_camera_image") }}</h2>
          <img id="scanner-frame" src="/einstellungen/scanner-diagnose/frame.jpg" alt="" style="width:100%;max-height:520px;object-fit:contain;border-radius:12px;">
        </div>
        <div class="card"><h2>{{ t("web_test_scan") }}</h2><p>{{ t("web_test_scan_desc") }}</p>
          <form method="post" action="/einstellungen/scanner-diagnose/testscan" style="display:flex;gap:10px;flex-wrap:wrap;">
            <input name="ean" required placeholder="EAN / UPC"><button class="filter">{{ t("run_test_scan") }}</button>
          </form></div>
        <div class="card"><h2>{{ t("sound_test") }}</h2>
          <form method="post" action="/einstellungen/scanner-diagnose/ton" style="display:flex;gap:10px;align-items:center;flex-wrap:wrap;">
            <select name="pattern"><option value="success">{{ t("sound_success") }}</option><option value="warning">{{ t("sound_warning") }}</option><option value="error">{{ t("sound_error") }}</option></select>
            <label>{{ t("volume") }} <input name="volume" type="range" min="10" max="100" value="60"></label>
            <button class="filter">{{ t("test_sound") }}</button>
          </form></div>
        <script>
        const labels={{ labels|tojson }};
        async function refreshScanner(){const response=await fetch('/api/scanner-diagnostics');if(!response.ok)return;const s=await response.json();
          const values=[[labels.fps,s.fps||0],[labels.decode,s.last_decode_ms==null?'—':s.last_decode_ms+' ms'],[labels.barcodes,(s.detected_barcodes||[]).join(', ')||'—'],[labels.success,s.last_success_at_text||'—'],[labels.error,s.last_error||'—']];
          document.getElementById('scanner-stats').innerHTML=values.map(v=>`<div class="stat"><strong>${v[0]}</strong><div class="stat-zahl" style="font-size:1.15rem">${v[1]}</div></div>`).join('');}
        refreshScanner();setInterval(refreshScanner,2000);setInterval(()=>{document.getElementById('scanner-frame').src='/einstellungen/scanner-diagnose/frame.jpg?t='+Date.now()},3000);
        </script></body></html>
        """,
        labels={"fps": _t("camera_fps"), "decode": _t("scan_time"), "barcodes": _t("detected_barcodes"), "success": _t("last_successful_scan"), "error": _t("last_scanner_error")},
    )


@scanner_diagnostics_bp.get("/api/scanner-diagnostics")
@admin_required
def scanner_diagnostics_api():
    state = read_status()
    for field in ("last_success_at", "last_error_at", "last_scan_at", "updated_at"):
        value = state.get(field)
        state[f"{field}_text"] = datetime.fromtimestamp(value).strftime("%Y-%m-%d %H:%M:%S") if value else None
    state["frame_available"] = frame_path().is_file()
    return jsonify(state)


@scanner_diagnostics_bp.get("/einstellungen/scanner-diagnose/frame.jpg")
@admin_required
def scanner_frame():
    path = frame_path()
    if not path.is_file():
        abort(404)
    response = send_file(path, mimetype="image/jpeg", max_age=0)
    response.headers["Cache-Control"] = "no-store"
    return response


@scanner_diagnostics_bp.post("/einstellungen/scanner-diagnose/testscan")
@admin_required
def scanner_test_scan():
    ean = request.form.get("ean", "").strip()
    conn = get_db()
    row = conn.execute(
        "SELECT p.name, pb.menge, pb.aktion FROM produkt_barcodes pb JOIN produkte p ON p.id=pb.produkt_id WHERE pb.ean=?",
        (ean,),
    ).fetchone()
    conn.close()
    write_status(test_scan_ean=ean, test_scan_result=dict(row) if row else None, test_scan_at=int(datetime.now().timestamp()))
    return jsonify(ok=bool(row), ean=ean, product=dict(row) if row else None)


@scanner_diagnostics_bp.post("/einstellungen/scanner-diagnose/ton")
@admin_required
def scanner_sound_test():
    try:
        queue_sound_test(request.form.get("pattern", "warning"), request.form.get("volume", "60"))
    except ValueError:
        abort(400)
    return redirect("/einstellungen/scanner-diagnose")
