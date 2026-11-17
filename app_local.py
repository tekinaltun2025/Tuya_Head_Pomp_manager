"""
Isi pompasi (R32 heat pump) - TAM DP verisi + kontrol + geçmiş grafik, yerel ag (Wi-Fi) uzerinden.
Bu sunucu ev agindaki makinede calisir, tum DP'leri yerel protokolle okur/yazar,
disaridan (internetten, Tailscale ile) erisim icin HTTP ile sunar.

Calistir: ./venv/bin/python app_local.py
Erisim (yerel ag): http://<bu-makine-ip>:8902/
"""
import time
import json
import sqlite3
import threading
from datetime import datetime, timedelta
from flask import Flask, jsonify, Response, request
import tinytuya

DEVICE_ID = "bfb3e7b67f3df5e451iqgh"
LOCAL_KEY = "}!g2>gk_Rlqrq`Mh"
DEVICE_IP = "192.168.1.164"
DEVICE_VERSION = 3.5
DEVICE_NAME = "R32 heat pump (NECLA_EV_ISITMA)"

# Kaynak: github.com/make-all/tuya-local, axen_ks100w_heatpump.yaml (product id l01fseshej0xmz8x)
# Bu cihaz Axen KS-100W/EN8BP (OEM) - R32 heat pump olarak satılan combo ısı pompası ile aynı şema.
DP_LABELS = {
    "1": "Ana Güç",
    "6": "Hata/Arıza Kodu",
    "101": "Sessiz Mod",
    "102": "Soğutma Hedef Sıcaklık (÷10 °C)",
    "103": "Isıtma/Auto Hedef Sıcaklık (÷10 °C)",
    "104": "Sıcak Su (CWU) Hedef Sıcaklık (÷10 °C)",
    "105": "Auto Modu Hedef Sıcaklık (÷10 °C)",
    "106": "Giriş Suyu Sıcaklığı (÷10 °C)",
    "107": "Çıkış Suyu Sıcaklığı (÷10 °C)",
    "108": "Sıcak Su Tankı Sıcaklığı (÷10 °C)",
    "109": "Çalışma Modu",
    "110": "Su Kapalı (water_off)",
    "114": "Antifriz Durumu",
    "115": "Defrost (Buz Çözme)",
    "116": "Su Pompası",
    "117": "Isıtma/Soğutma Aktif mi",
    "118": "Ortam (Dış Hava) Sıcaklığı (÷10 °C)",
    "119": "Egzoz/Deşarj Sıcaklığı (÷10 °C)",
    "120": "Dönüş (Emme) Sıcaklığı (÷10 °C)",
    "121": "Kompresör Frekansı (Hz)",
    "122": "Ana Genleşme Valfi (EEV) Açıklığı (step)",
    "123": "Yardımcı EEV Açıklığı (step)",
    "124": "AC Fan Durumu (close/low_spd/high_spd)",
    "125": "DC Fan 1 Hızı (RPM)",
    "126": "DC Fan 2 Hızı (RPM)",
    "127": "Su Debisi (m³/h)",
    "128": "Voltaj (V)",
    "129": "Akım (A)",
    "130": "Arıza Bayrağı",
    "165": "Tatil Modu (Away)",
    "180": "Sistem Durumu",
}

# ÷10 ölçeklendirme gereken sıcaklık/değer DP'leri (okuma VE yazma için)
SCALE10_DPS = {"102", "103", "104", "105", "106", "107", "108", "118", "119", "120"}

# Yazmaya izin verilen (kontrol edilebilir) DP'ler - sensör/salt-okunur olanlar hariç
WRITABLE_DPS = {
    "1":   {"type": "bool",   "label": "Ana Güç"},
    # Cihazda doğrulandı: 35°C altındaki komutlar cihaz tarafından sessizce
    # reddediliyor (donanım/firmware sınırı). min=35 gerçek alt sınırı yansıtır.
    "103": {"type": "temp",   "label": "Isıtma/Auto Hedef Sıcaklık (°C)", "min": 35, "max": 60},
    "104": {"type": "temp",   "label": "Sıcak Su (CWU) Hedef Sıcaklık (°C)", "min": 20, "max": 60},
    "105": {"type": "temp",   "label": "Auto Modu Hedef Sıcaklık (°C)", "min": 5, "max": 25},
    "109": {"type": "enum",   "label": "Çalışma Modu",
            "options": ["heat", "auto", "hot_water", "heat_hot_water"]},
    "101": {"type": "bool",   "label": "Sessiz Mod"},
    "165": {"type": "bool",   "label": "Tatil Modu (Away)"},
}

app = Flask(__name__, static_folder='static')
_cache = {"ts": 0, "data": None}
CACHE_SECONDS = 2

# ===== Geçmiş veritabanı =====
DB_PATH = "/home/tekinaltun/projects/tuya-local/history.db"
DB_LOCK = threading.Lock()

def init_db():
    with DB_LOCK:
        con = sqlite3.connect(DB_PATH)
        con.execute("""
            CREATE TABLE IF NOT EXISTS readings (
                ts INTEGER NOT NULL,
                dp TEXT NOT NULL,
                value REAL NOT NULL,
                PRIMARY KEY (ts, dp)
            )
        """)
        con.execute("CREATE INDEX IF NOT EXISTS idx_readings_ts ON readings(ts)")
        con.commit()
        con.close()

def save_readings(dps_dict):
    """dps_dict: {dp_code: value} - value ham (÷10 öncesi)"""
    now_ts = int(time.time())
    with DB_LOCK:
        con = sqlite3.connect(DB_PATH)
        for dp, val in dps_dict.items():
            if isinstance(val, (int, float)):
                con.execute("INSERT OR REPLACE INTO readings (ts, dp, value) VALUES (?, ?, ?)",
                           (now_ts, str(dp), float(val)))
        con.commit()
        con.close()

def query_history(dp_codes, hours=24):
    """Son 'hours' saat içindeki veriyi getir. Dönüş: {dp: [(ts, value), ...]}"""
    since = int(time.time()) - hours * 3600
    placeholders = ",".join("?" for _ in dp_codes)
    with DB_LOCK:
        con = sqlite3.connect(DB_PATH)
        rows = con.execute(f"""
            SELECT dp, ts, value FROM readings
            WHERE dp IN ({placeholders}) AND ts >= ?
            ORDER BY ts ASC
        """, (*dp_codes, since)).fetchall()
        con.close()
    result = {dp: [] for dp in dp_codes}
    for dp, ts, val in rows:
        result[dp].append([ts * 1000, val])  # JS için ms cinsinden
    return result

def prune_old(days=30):
    """Eski verileri temizle"""
    cutoff = int(time.time()) - days * 86400
    with DB_LOCK:
        con = sqlite3.connect(DB_PATH)
        con.execute("DELETE FROM readings WHERE ts < ?", (cutoff,))
        con.commit()
        con.close()

# Arka plan toplayıcı (her 10 dakikada bir)
COLLECTOR_INTERVAL = 600  # saniye
COLLECTOR_DPS = ["103", "104", "105", "106", "107", "108", "118", "119", "120", "121", "128", "129"]
_collector_stop = threading.Event()

def collector_loop():
    while not _collector_stop.wait(COLLECTOR_INTERVAL):
        try:
            d = get_device()
            status = d.status()
            dps = status.get("dps", {}) if isinstance(status, dict) else {}
            filtered = {k: v for k, v in dps.items() if k in COLLECTOR_DPS}
            if filtered:
                save_readings(filtered)
                print(f"[collector] {datetime.now().strftime('%H:%M:%S')} kaydedildi: {list(filtered.keys())}")
        except Exception as e:
            print(f"[collector] hata: {e}")

def start_collector():
    init_db()
    t = threading.Thread(target=collector_loop, daemon=True)
    t.start()
    print("[collector] başlatıldı (10 dk aralık)")

def stop_collector():
    _collector_stop.set()


def get_device():
    d = tinytuya.Device(DEVICE_ID, DEVICE_IP, LOCAL_KEY)
    d.set_version(DEVICE_VERSION)
    d.set_socketTimeout(5)
    return d


def fetch_status(force=False):
    now = time.time()
    if not force and _cache["data"] and now - _cache["ts"] < CACHE_SECONDS:
        return _cache["data"]
    d = get_device()
    status = d.status()
    _cache["data"] = status
    _cache["ts"] = now
    # Geçmişe kaydet (sıcaklık DP'leri)
    try:
        dps = status.get("dps", {}) if isinstance(status, dict) else {}
        filtered = {k: v for k, v in dps.items() if k in COLLECTOR_DPS}
        if filtered:
            save_readings(filtered)
    except Exception:
        pass
    return status


@app.route("/status")
def status():
    data = fetch_status()
    return jsonify(data)


@app.route("/set", methods=["POST"])
def set_value():
    """JSON body: {"dp": "103", "value": 35}  (sıcaklık °C olarak, bool/enum ham değer)"""
    body = request.get_json(force=True, silent=True) or {}
    dp = str(body.get("dp", ""))
    value = body.get("value")

    if dp not in WRITABLE_DPS:
        return jsonify({"ok": False, "error": f"DP {dp} yazılabilir listede değil"}), 400

    spec = WRITABLE_DPS[dp]
    try:
        if spec["type"] == "bool":
            payload_value = bool(value) if not isinstance(value, str) else value.lower() in ("1", "true", "on", "açık")
        elif spec["type"] == "temp":
            temp_c = float(value)
            if not (spec["min"] <= temp_c <= spec["max"]):
                return jsonify({"ok": False, "error": f"Sıcaklık {spec['min']}-{spec['max']}°C aralığında olmalı"}), 400
            payload_value = int(round(temp_c * 10))
        elif spec["type"] == "enum":
            if value not in spec["options"]:
                return jsonify({"ok": False, "error": f"Geçersiz seçenek, olası: {spec['options']}"}), 400
            payload_value = value
        else:
            return jsonify({"ok": False, "error": "bilinmeyen tip"}), 400

        d = get_device()
        result = d.set_value(int(dp), payload_value, nowait=False)
        _cache["data"] = None  # cache'i boz, sonraki okuma taze gelsin
        return jsonify({"ok": True, "sent": {"dp": dp, "value": payload_value}, "device_response": result})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.route("/history")
def history():
    """Geçmiş veri endpoint'i. Query params: hours=24, dps=103,104,106,118"""
    hours = int(request.args.get("hours", "24"))
    hours = max(1, min(hours, 24 * 30))  # 1 saat - 30 gün arası
    dps_param = request.args.get("dps", "103,104,106,107,108,118,119,120")
    dp_codes = [d.strip() for d in dps_param.split(",") if d.strip()]
    data = query_history(dp_codes, hours)
    return jsonify({"hours": hours, "dps": data, "labels": {dp: DP_LABELS.get(dp, dp) for dp in dp_codes}})


ICONS = {
    "1": "⏻", "6": "⚠", "101": "🔇", "102": "❄", "103": "🔥", "104": "🚿",
    "105": "🌡", "106": "💧", "107": "💧", "108": "🛁", "109": "⚙",
    "110": "🚰", "114": "🧊", "115": "🧊", "116": "🌀", "117": "⚡",
    "118": "🌤", "119": "🔺", "120": "🔻", "121": "🌀", "122": "🎛",
    "123": "🎛", "124": "🪭", "125": "🪭", "126": "🪭", "127": "💧",
    "128": "🔌", "129": "🔌", "130": "⚠", "165": "🏖", "180": "📶",
}

SENSOR_DPS = [
    "106", "107", "108", "118", "119", "120", "121", "128", "129", "127",
    "125", "126", "122", "123", "6", "110", "114", "115", "116", "117", "130", "180",
]


@app.route("/")
def home():
    data = fetch_status()
    dps = data.get("dps", {}) if isinstance(data, dict) else {}

    def disp(code, value):
        if code in SCALE10_DPS and isinstance(value, (int, float)):
            return f"{value/10:.1f}"
        if isinstance(value, bool):
            return "Açık" if value else "Kapalı"
        return value

    power_on = bool(dps.get("1"))
    mode = dps.get("109", "—")
    outside_temp = disp("118", dps.get("118"))

    hero = f"""
    <div class="hero {'on' if power_on else 'off'}">
      <div class="hero-left">
        <div class="hero-status">{'● ÇALIŞIYOR' if power_on else '○ KAPALI'}</div>
        <div class="hero-mode">{mode}</div>
        <div class="hero-sub">Dış hava: {outside_temp}°C</div>
      </div>
      <button class="power-btn {'on' if power_on else ''}" onclick="setDp('1', {str(not power_on).lower()})">⏻</button>
    </div>"""

    # ===== Grafik için veri serisi (son 24h varsayılan) =====
    CHART_DPS = ["103", "104", "106", "107", "108", "118", "119", "120"]
    chart_dps_json = json.dumps(CHART_DPS)

    sensor_cards = ""
    for code in SENSOR_DPS:
        if code not in dps:
            continue
        label = DP_LABELS.get(code, code)
        val = disp(code, dps[code])
        unit = "°C" if code in SCALE10_DPS else ("Hz" if code == "121" else ("V" if code == "128" else ("A" if code == "129" else "")))
        sensor_cards += f"""
        <div class="sensor-card">
          <div class="sensor-icon">{ICONS.get(code, '📟')}</div>
          <div class="sensor-val">{val}{unit}</div>
          <div class="sensor-label">{label}</div>
        </div>"""

    control_cards = ""
    for dp, spec in WRITABLE_DPS.items():
        if dp == "1":
            continue
        cur = dps.get(dp)
        icon = ICONS.get(dp, "⚙")
        if spec["type"] == "bool":
            control_cards += f"""
            <div class="control-card">
              <div class="control-head"><span class="c-icon">{icon}</span>{spec['label']}</div>
              <label class="switch">
                <input type="checkbox" {"checked" if cur else ""} onchange="setDp('{dp}', this.checked)">
                <span class="slider"></span>
              </label>
            </div>"""
        elif spec["type"] == "temp":
            cur_c = (cur / 10) if isinstance(cur, (int, float)) else spec["min"]
            lo, hi = spec["min"], spec["max"]
            # Aralığa göre makul aralıklarla tick/sayı üret (çok sık olmasın)
            ticks = list(range(int(lo), int(hi) + 1, 1))
            if ticks[-1] != int(hi):
                ticks.append(int(hi))
            datalist_opts = "".join(f"<option value='{t}'></option>" for t in ticks)
            tick_labels = "".join(
                f"<span style='left:{(t - lo) / (hi - lo) * 100}%'>{t}</span>" for t in ticks
            )
            control_cards += f"""
            <div class="control-card wide">
              <div class="control-head"><span class="c-icon">{icon}</span>{spec['label']}
                <span class="temp-readout" id="val{dp}">{cur_c}°C</span></div>
              <input type="range" class="temp-slider" id="dp{dp}" min="{lo}" max="{hi}"
                     step="0.5" value="{cur_c}" list="ticks{dp}"
                     oninput="document.getElementById('val{dp}').textContent=this.value+'°C'"
                     onchange="setTemp('{dp}')">
              <datalist id="ticks{dp}">{datalist_opts}</datalist>
              <div class="tick-labels">{tick_labels}</div>
            </div>"""
        elif spec["type"] == "enum":
            opts = "".join(
                f"<option value='{o}' {'selected' if o == cur else ''}>{o.replace('_',' ').title()}</option>"
                for o in spec["options"]
            )
            control_cards += f"""
            <div class="control-card wide">
              <div class="control-head"><span class="c-icon">{icon}</span>{spec['label']}</div>
              <select class="mode-select" id="dp{dp}" onchange="setEnum('{dp}')">{opts}</select>
            </div>"""

    html = f"""
    <html><head><meta charset='utf-8'>
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>{DEVICE_NAME}</title>
    <script src="/static/chart.umd.min.js"></script>
    <script src="/static/chartjs-adapter-date-fns.bundle.min.js"></script>
    <script>
      Chart.register(ChartDateFnsAdapter);
    </script>
    <style>
      :root {{
        --bg: #0b0e14; --card: #151a24; --card2: #1b2230; --accent: #22d3ee;
        --accent2: #a78bfa; --warn: #fb7185; --ok: #34d399; --text: #e5e7eb;
        --muted: #8b93a7;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0; padding: 24px 16px 60px; min-height: 100vh;
        background: radial-gradient(circle at 20% -10%, #1a2340 0%, var(--bg) 55%);
        color: var(--text); font-family: -apple-system, 'Segoe UI', Roboto, sans-serif;
      }}
      h1 {{ font-size: 1.3rem; font-weight: 600; margin: 0 0 4px; }}
      .subtitle {{ color: var(--muted); font-size: 0.85rem; margin-bottom: 20px; }}
      .wrap {{ max-width: 720px; margin: 0 auto; }}

      .hero {{
        display: flex; justify-content: space-between; align-items: center;
        background: linear-gradient(135deg, #1b2a4a, #10131f);
        border: 1px solid #2a3550; border-radius: 20px; padding: 22px 24px;
        margin-bottom: 22px; box-shadow: 0 10px 30px -10px rgba(34,211,238,0.15);
      }}
      .hero.on {{ border-color: rgba(52,211,153,0.4); }}
      .hero-status {{ font-size: 0.8rem; letter-spacing: 1px; color: var(--ok); font-weight: 600; }}
      .hero.off .hero-status {{ color: var(--muted); }}
      .hero-mode {{ font-size: 1.6rem; font-weight: 700; margin: 4px 0; text-transform: capitalize; }}
      .hero-sub {{ color: var(--muted); font-size: 0.85rem; }}
      .power-btn {{
        width: 58px; height: 58px; border-radius: 50%; border: 2px solid #334;
        background: #1a1f2b; color: #667; font-size: 1.4rem; cursor: pointer;
        transition: all 0.25s;
      }}
      .power-btn.on {{
        background: radial-gradient(circle, #34d39933, transparent); color: var(--ok);
        border-color: var(--ok); box-shadow: 0 0 18px rgba(52,211,153,0.5);
      }}

      .section-title {{
        font-size: 0.75rem; text-transform: uppercase; letter-spacing: 1.5px;
        color: var(--muted); margin: 28px 0 12px; font-weight: 600;
      }}

      .sensor-grid {{
        display: grid; grid-template-columns: repeat(auto-fill, minmax(100px, 1fr));
        gap: 10px;
      }}
      .sensor-card {{
        background: var(--card); border: 1px solid #242b3a; border-radius: 14px;
        padding: 14px 10px; text-align: center; transition: transform 0.15s;
      }}
      .sensor-card:hover {{ transform: translateY(-2px); border-color: var(--accent); }}
      .sensor-icon {{ font-size: 1.3rem; margin-bottom: 6px; }}
      .sensor-val {{ font-size: 1.05rem; font-weight: 700; color: var(--accent); }}
      .sensor-label {{ font-size: 0.65rem; color: var(--muted); margin-top: 3px; line-height: 1.2; }}

      .control-grid {{
        display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px;
      }}
      .control-card {{
        background: var(--card2); border: 1px solid #2a3344; border-radius: 16px;
        padding: 16px; display: flex; flex-direction: column; justify-content: space-between;
        min-height: 72px;
      }}
      .control-card.wide {{ grid-column: 1 / -1; }}
      .control-head {{
        display: flex; align-items: center; gap: 8px; font-size: 0.9rem; font-weight: 600;
        margin-bottom: 10px;
      }}
      .c-icon {{ font-size: 1.1rem; }}
      .temp-readout {{ margin-left: auto; color: var(--accent); font-weight: 700; }}

      .switch {{ position: relative; display: inline-block; width: 50px; height: 28px; align-self: flex-start; }}
      .switch input {{ opacity: 0; width: 0; height: 0; }}
      .slider {{
        position: absolute; cursor: pointer; inset: 0; background: #2a3344;
        border-radius: 28px; transition: 0.3s;
      }}
      .slider::before {{
        content: ""; position: absolute; height: 22px; width: 22px; left: 3px; bottom: 3px;
        background: #ccc; border-radius: 50%; transition: 0.3s;
      }}
      input:checked + .slider {{ background: var(--ok); }}
      input:checked + .slider::before {{ transform: translateX(22px); background: #fff; }}

      .temp-slider {{
        -webkit-appearance: none; width: 100%; height: 6px; border-radius: 3px;
        background: linear-gradient(90deg, var(--accent2), var(--accent)); outline: none;
      }}
      .tick-labels {{
        position: relative; height: 16px; margin-top: 2px;
      }}
      .tick-labels span {{
        position: absolute; transform: translateX(-50%);
        font-size: 9px; color: var(--muted, #9aa0a6); font-weight: 500;
      }}
      .tick-labels span:first-child {{ transform: translateX(0); }}
      .tick-labels span:last-child {{ transform: translateX(-100%); }}

      .chart-section {{
        background: var(--card); border: 1px solid #242b3a; border-radius: 16px;
        padding: 20px; margin: 22px 0;
      }}
      .chart-header {{
        display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px;
      }}
      .chart-title {{ font-size: 1rem; font-weight: 600; }}
      .chart-controls {{ display: flex; gap: 8px; flex-wrap: wrap; }}
      .chart-btn {{
        padding: 6px 12px; border-radius: 8px; border: 1px solid #2a3344;
        background: #10141d; color: var(--text); font-size: 0.8rem; cursor: pointer;
        transition: all 0.15s;
      }}
      .chart-btn:hover {{ border-color: var(--accent); }}
      .chart-btn.active {{ background: var(--accent); color: #000; border-color: var(--accent); }}
      .chart-canvas-wrap {{ position: relative; height: 320px; }}
      .chart-legend {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 8px 0 12px; padding: 8px; background: var(--card2); border-radius: 8px; border: 1px solid #242b3a; }}
      .chart-legend-actions {{ display: flex; gap: 6px; margin-bottom: 8px; }}
      .chart-legend-btn {{ padding: 4px 10px; border-radius: 6px; border: 1px solid #2a3344; background: #10141d; color: var(--text); font-size: 0.7rem; cursor: pointer; transition: all 0.15s; }}
      .chart-legend-btn:hover {{ border-color: var(--accent); }}
      .chart-legend-item {{ display: inline-flex; align-items: center; gap: 6px; cursor: pointer; font-size: 0.75rem; color: #e5e7eb; }}
      .chart-legend-item input {{ width: 14px; height: 14px; accent-color: var(--accent); cursor: pointer; }}
      .chart-legend-item.hidden {{ opacity: 0.4; }}
      .chart-legend-color {{ width: 12px; height: 12px; border-radius: 2px; flex-shrink: 0; }}

      .temp-slider::-webkit-slider-thumb {{
        -webkit-appearance: none; width: 22px; height: 22px; border-radius: 50%;
        background: #fff; border: 3px solid var(--accent); cursor: pointer;
      }}

      .mode-select {{
        width: 100%; padding: 10px; border-radius: 10px; border: 1px solid #2a3344;
        background: #10141d; color: var(--text); font-size: 0.95rem;
      }}

      #toast {{
        position: fixed; bottom: 20px; left: 50%; transform: translateX(-50%) translateY(100px);
        background: #1b2230; border: 1px solid #334; padding: 10px 18px; border-radius: 12px;
        font-size: 0.85rem; transition: transform 0.3s; box-shadow: 0 8px 24px rgba(0,0,0,0.4);
      }}
      #toast.show {{ transform: translateX(-50%) translateY(0); }}
      #toast.ok {{ border-color: var(--ok); color: var(--ok); }}
      #toast.err {{ border-color: var(--warn); color: var(--warn); }}
    </style>
    <script>
      async function send(dp, value) {{
        const res = await fetch('/set', {{
          method: 'POST', headers: {{'Content-Type':'application/json'}},
          body: JSON.stringify({{dp: dp, value: value}})
        }});
        const data = await res.json();
        const toast = document.getElementById('toast');
        toast.textContent = data.ok ? '✓ Gönderildi' : ('✗ ' + data.error);
        toast.className = 'show ' + (data.ok ? 'ok' : 'err');
        setTimeout(() => toast.classList.remove('show'), 2500);
        // Cihazın dahili olarak değeri işlemesi zaman alabilir; hemen reload
        // yaparsak eski değeri okuyup gösterebiliriz. Ekranı olduğu gibi
        // bırakıp (optimistic), gerçek durumu birkaç saniye sonra sessizce
        // senkronize ediyoruz (bool/enum anlık yansıdığı için onlar için
        // reload sorun değil, sadece sıcaklık slider'ları için erteliyoruz).
        if (data.ok && !dp.toString().match(/^(102|103|104|105)$/)) {{
          setTimeout(() => location.reload(), 1200);
        }} else if (data.ok) {{
          setTimeout(() => location.reload(), 6000);
        }}
      }}
      function setDp(dp, value) {{ send(dp, value); }}
      const _debounceTimers = {{}};
      function setTemp(dp) {{
        // Mobilde sürükleme sırasında 'change' olayı art arda ateşlenebilir.
        // Son değeri gönderene kadar bekle, aradaki istekleri iptal et.
        if (_debounceTimers[dp]) clearTimeout(_debounceTimers[dp]);
        _debounceTimers[dp] = setTimeout(() => {{
          send(dp, parseFloat(document.getElementById('dp'+dp).value));
        }}, 450);
      }}
      function setEnum(dp) {{ send(dp, document.getElementById('dp'+dp).value); }}
    </script>
    <script>
      // ===== Grafik (Chart.js) =====
      let tempChart = null;
      let currentHours = 24;
      const CHART_DPS_CODES = {chart_dps_json};
      const DP_COLORS = {{
        "103": "#22d3ee",   // Isıtma hedef - cyan
        "104": "#fb7185",   // Sıcak su hedef - rose
        "105": "#a78bfa",   // Auto hedef - violet
        "106": "#34d399",   // Giriş suyu - emerald
        "107": "#fbbf24",   // Çıkış suyu - amber
        "108": "#f87171",   // Tank sıcaklığı - red
        "118": "#60a5fa",   // Dış hava - blue
        "119": "#f472b6",   // Egzoz - pink
        "120": "#4ade80",   // Dönüş - green
      }};

      async function loadChart(hours) {{
        currentHours = hours;
        document.querySelectorAll('.chart-btn').forEach(b => {{
          b.classList.toggle('active', parseInt(b.dataset.hours) === hours);
        }});
        document.querySelector('.chart-title').textContent = 
          '📈 Sıcaklık Geçmişi (Son ' + (hours < 24 ? hours + ' Saat' : (hours/24) + ' Gün') + ')';
        try {{
          const resp = await fetch('/history?hours=' + hours + '&dps=' + CHART_DPS_CODES.join(','));
          const data = await resp.json();
          renderChart(data);
        }} catch (e) {{
          console.error('Grafik yükleme hatası:', e);
        }}
      }}

      function renderChart(data) {{
        const ctx = document.getElementById('tempChart').getContext('2d');
        const datasets = [];
        for (const dp of CHART_DPS_CODES) {{
          const points = data.dps[dp] || [];
          if (points.length === 0) continue;
          datasets.push({{
            label: data.labels[dp] || dp,
            data: points,
            borderColor: DP_COLORS[dp] || '#888',
            backgroundColor: (DP_COLORS[dp] || '#888') + '22',
            borderWidth: 2,
            fill: false,
            tension: 0.2,
            pointRadius: 0,
            pointHoverRadius: 4,
            spanGaps: true,
          }});
        }}
        if (tempChart) tempChart.destroy();
        tempChart = new Chart(ctx, {{
          type: 'line',
          data: {{ datasets }},
          options: {{
            responsive: true,
            maintainAspectRatio: false,
            interaction: {{ mode: 'index', intersect: false }},
            plugins: {{
              legend: {{ display: false }},
              tooltip: {{
                backgroundColor: '#1b2230',
                titleColor: '#e5e7eb',
                bodyColor: '#e5e7eb',
                borderColor: '#334',
                borderWidth: 1,
                padding: 10,
                callbacks: {{
                  label: function(ctx) {{
                    const dp = CHART_DPS_CODES[ctx.datasetIndex];
                    const isTemp = ['103','104','105','106','107','108','118','119','120'].includes(dp);
                    const val = isTemp ? (ctx.parsed.y / 10).toFixed(1) + '°C' : ctx.parsed.y.toFixed(1);
                    return ctx.dataset.label + ': ' + val;
                  }}
                }}
              }}
            }},
            scales: {{
              x: {{
                type: 'time',
                time: {{ tooltipFormat: 'HH:mm', unit: 'hour', displayFormats: {{ hour: 'HH:mm' }} }},
                grid: {{ color: '#242b3a' }},
                ticks: {{ color: '#8b93a7', maxTicksLimit: 12 }},
              }},
              y: {{
                grid: {{ color: '#242b3a' }},
                ticks: {{ color: '#8b93a7', callback: function(v) {{ return v/10 + '°C'; }} }},
              }}
            }},
          }}
        }});

        // Build custom legend with checkboxes
        const itemsEl = document.getElementById('chartLegendItems');
        itemsEl.innerHTML = '';
        tempChart.data.datasets.forEach((ds, i) => {{
          const item = document.createElement('label');
          item.className = 'chart-legend-item';
          item.innerHTML = '<input type="checkbox" checked> <span class="chart-legend-color" style="background:' + ds.borderColor + '"></span> ' + ds.label;
          const cb = item.querySelector('input');
          cb.addEventListener('change', () => {{
            const meta = tempChart.getDatasetMeta(i);
            meta.hidden = !cb.checked;
            item.classList.toggle('hidden', !cb.checked);
            tempChart.update();
          }});
          itemsEl.appendChild(item);
        }});

        // Select All / Deselect All buttons
        const selectAllBtn = document.getElementById('legendSelectAll');
        const deselectAllBtn = document.getElementById('legendDeselectAll');
        if (selectAllBtn) {{
          selectAllBtn.addEventListener('click', () => {{
            tempChart.data.datasets.forEach((ds, i) => {{
              const meta = tempChart.getDatasetMeta(i);
              meta.hidden = false;
              const cb = itemsEl.querySelectorAll('.chart-legend-item input')[i];
              if (cb) {{
                cb.checked = true;
                cb.parentElement.classList.remove('hidden');
              }}
            }});
            tempChart.update();
          }});
        }}
        if (deselectAllBtn) {{
          deselectAllBtn.addEventListener('click', () => {{
            tempChart.data.datasets.forEach((ds, i) => {{
              const meta = tempChart.getDatasetMeta(i);
              meta.hidden = true;
              const cb = itemsEl.querySelectorAll('.chart-legend-item input')[i];
              if (cb) {{
                cb.checked = false;
                cb.parentElement.classList.add('hidden');
              }}
            }});
            tempChart.update();
          }});
        }}
      }}

      // Otomatik yenileme (her 10 dk)
      setInterval(() => loadChart(currentHours), 10 * 60 * 1000);

      // Sayfa yüklendiğinde grafik başlat
      document.addEventListener('DOMContentLoaded', () => {{
        loadChart(24);
        document.querySelectorAll('.chart-btn').forEach(btn => {{
          btn.addEventListener('click', () => loadChart(parseInt(btn.dataset.hours)));
        }});
      }});
    </script>
    </head>
    <body>
      <div class="wrap">
        <h1>{DEVICE_NAME}</h1>
        <div class="subtitle">Tailscale üzerinden canlı izleme &amp; kontrol</div>

        {hero}

        <div class="chart-section">
          <div class="chart-header">
            <span class="chart-title">📈 Sıcaklık Geçmişi (Son 24 Saat)</span>
            <div class="chart-controls">
              <button class="chart-btn active" data-hours="1">1S</button>
              <button class="chart-btn" data-hours="6">6S</button>
              <button class="chart-btn" data-hours="24">24S</button>
              <button class="chart-btn" data-hours="168">7G</button>
            </div>
          </div>
          <div class="chart-legend" id="chartLegend">
            <div class="chart-legend-actions">
              <button class="chart-legend-btn" id="legendSelectAll">Hepsi Seç</button>
              <button class="chart-legend-btn" id="legendDeselectAll">Tümünü Kaldır</button>
            </div>
            <div class="chart-legend-items" id="chartLegendItems"></div>
          </div>
          <div class="chart-canvas-wrap">
            <canvas id="tempChart"></canvas>
          </div>
        </div>

        <div class="section-title">Kontroller</div>
        <div class="control-grid">{control_cards}</div>

        <div class="section-title">Sensörler</div>
        <div class="sensor-grid">{sensor_cards}</div>
      </div>
      <div id="toast"></div>
    </body></html>
    """
    return Response(html, mimetype="text/html")


if __name__ == "__main__":
    start_collector()
    try:
        app.run(host="0.0.0.0", port=8902)
    finally:
        stop_collector()
