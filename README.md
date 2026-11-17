# Tuya R32 Heat Pump Manager (NECLA_EV_ISITMA) / Tuya R32 Isı Pompası Yöneticisi

Yerel ağ (LAN) üzerinden Axen KS-100W / R32 Isı Pompası izleme ve kontrol paneli.  
Tailscale ile uzaktan erişim, SQLite geçmiş veritabanı, Chart.js grafikler, glassmorphism UI.

---

## 🎯 Özellikler / Features

| Türkçe / Turkish | English |
|------------------|---------|
| **Tam yerel iletişim** — `tinytuya` protokol 3.5, Cloud'a bağımlı değil | **Fully local communication** — `tinytuya` protocol 3.5, no Cloud dependency |
| **Canlı durum** — 19 DP okuma (sıcaklıklar, modlar, fanlar, kompresör, EEV, su debisi, voltaj/akım) | **Live status** — 19 DP readings (temperatures, modes, fans, compressor, EEV, flow, voltage/current) |
| **Kontrol** — Ana güç, ısıtma/su/auto hedefleri (35-60°C), çalışma modu (heat/auto/hot_water/heat_hot_water), sessiz/tatil modu | **Control** — Main power, heating/water/auto targets (35-60°C), operation mode, silent/away modes |
| **Geçmiş grafik** — 8 sıcaklık serisi, 4 zaman aralığı (1h/6h/24h/7d), 10 dk otomatik yenileme | **History charts** — 8 temperature series, 4 time ranges (1h/6h/24h/7d), 10 min auto-refresh |
| **Seri gizle/göster** — Checkbox legend + "Hepsi Seç / Tümünü Kaldır" butonları | **Series toggle** — Checkbox legend + "Select All / Deselect All" buttons |
| **Sistem servisi** — `systemd` ile açılışta otomatik başlatma, `Restart=always` | **System service** — `systemd` auto-start on boot, `Restart=always` |
| **Tailscale erişim** — `http://100.125.108.13:8902/` (herhangi bir yerden) | **Tailscale access** — `http://100.125.108.13:8902/` (from anywhere) |

---

## 📦 Kurulum / Installation

### 1. Bağımlılıklar / Dependencies

```bash
sudo apt update && sudo apt install python3-venv sqlite3
cd /home/tekinaltun/projects/Tuya_Head_Pomp_manager
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Tuya Cloud Credentials (bir kez / one-time)

- https://iot.tuya.com → Cloud → Project oluştur (Smart Home, Custom) / Create Project (Smart Home, Custom)
- **Access ID** / **Access Secret** kopyala / Copy
- Devices → Link Tuya App Account → SmartLife hesabını QR ile bağla / Link SmartLife account via QR
- Service API: IoT Core, Authorization, Device Status Notification etkinleştir / Enable

### 3. Wizard ile Local Key Alma / Get Local Key via Wizard

```bash
cd /home/tekinaltun/projects/Tuya_Head_Pomp_manager
./venv/bin/python -m tinytuya wizard
# Access ID, Access Secret, Region (eu) gir / Enter
# SmartLife App UID istenirse gir / Enter if prompted
# devices.json ve snapshot.json oluşur / Created
```

### 4. Cihaz Konfigürasyonu / Device Configuration

`app_local.py` dosyasını aç ve şunları güncelle / Edit and update:

```python
DEVICE_ID = "bfb3e7b67f3df5e451iqgh"      # Isı pompası Device ID / Heat pump Device ID
LOCAL_KEY = "}!g2>gk_Rlqrq`Mh"            # Wizard'dan alınan Local Key / Local Key from wizard
DEVICE_IP = "192.168.1.164"               # Yerel IP (aynı ağda) / Local IP (same LAN)
DEVICE_VERSION = 3.5                       # Protokol versiyonu / Protocol version
```

> **Not:** Eğer cihaz farklı bir IP'de ise `tinytuya scan` ile bulabilirsiniz. / If different IP, use `tinytuya scan` to discover.

### 5. Systemd Servisi / Systemd Service

```bash
sudo cp tuya-heatpump.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tuya-heatpump.service
sudo systemctl status tuya-heatpump.service
```

Servis logları / Service logs:
```bash
journalctl -u tuya-heatpump.service -f
```

---

## 🌐 Erişim / Access

| Ortam / Environment | URL |
|---------------------|-----|
| Yerel ağ / Local LAN | `http://<makine-ip>:8902/` |
| Tailscale | `http://100.125.108.13:8902/` |

---

## 📊 DP Şeması / DP Schema (Kaynak: github.com/make-all/tuya-local)

| DP | Açıklama / Description | Tip / Type | Ölçek / Scale | Yazılabilir / Writable |
|----|------------------------|------------|---------------|------------------------|
| 1 | Ana Güç / Main Power | Bool | - | ✅ |
| 6 | Hata Kodu / Error Code | Enum | - | ❌ |
| 101 | Sessiz Mod / Silent Mode | Bool | - | ✅ |
| 103 | Isıtma/Auto Hedef / Heat/Auto Target | Temp | ÷10 °C | ✅ (35-60) |
| 104 | Sıcak Su (CWU) Hedef / DHW Target | Temp | ÷10 °C | ✅ (20-60) |
| 105 | Auto Modu Hedef / Auto Mode Target | Temp | ÷10 °C | ✅ (5-25) |
| 106 | Giriş Suyu / Inlet Water | Temp | ÷10 °C | ❌ |
| 107 | Çıkış Suyu / Outlet Water | Temp | ÷10 °C | ❌ |
| 108 | Tank Sıcaklığı / Tank Temp | Temp | ÷10 °C | ❌ |
| 109 | Çalışma Modu / Operation Mode | Enum | heat/auto/hot_water/heat_hot_water | ✅ |
| 118 | Dış Hava / Outdoor Temp | Temp | ÷10 °C | ❌ |
| 119 | Egzoz/Deşarj / Exhaust Temp | Temp | ÷10 °C | ❌ |
| 120 | Dönüş (Emme) / Suction Temp | Temp | ÷10 °C | ❌ |
| 121 | Kompresör Frekansı / Compressor Freq | Int | Hz | ❌ |
| 122 | Ana EEV Açıklığı / Main EEV Opening | Int | step | ❌ |
| 123 | Yardımcı EEV / Sub EEV | Int | step | ❌ |
| 124 | AC Fan Durumu / AC Fan Status | Enum | close/low/high | ❌ |
| 125 | DC Fan 1 Hızı / DC Fan 1 Speed | Int | RPM | ❌ |
| 126 | DC Fan 2 Hızı / DC Fan 2 Speed | Int | RPM | ❌ |
| 127 | Su Debisi / Water Flow | Float | m³/h | ❌ |
| 128 | Voltaj / Voltage | Float | V | ❌ |
| 129 | Akım / Current | Float | A | ❌ |
| 165 | Tatil Modu / Away Mode | Bool | - | ✅ |

**Önemli / Important:** DP103 (Isıtma hedefi) cihaz donanımında **35°C alt sınırı** vardır. 35 altı gönderilirse cihaz sessizce reddeder.  
**Important:** DP103 (Heating target) has a **hardware minimum of 35°C**. Values below 35 are silently rejected by the device.

---

## 🗄️ Geçmiş Veritabanı / History Database

- **Dosya / File:** `history.db` (SQLite)
- **Tablo / Table:** `readings(ts INTEGER, dp TEXT, value REAL, PRIMARY KEY(ts, dp))`
- **Toplayıcı / Collector:** APScheduler, her 10 dk bir çalışır (DP: 103,104,105,106,107,108,118,119,120)
- **API:** `GET /history?hours=24&dps=103,104,106...`

---

## 🔧 Sorun Giderme / Troubleshooting

| Sorun / Issue | Çözüm / Solution |
|---------------|------------------|
| "Connection refused" | Cihaz IP/Local Key yanlış; `tinytuya scan` ile doğrula / Wrong IP/Key; verify with `tinytuya scan` |
| Grafik boş / Empty chart | `/history?hours=24` endpoint'ini test et; `history.db` dolu mu? / Test endpoint; check DB |
| Chart.js yüklenmiyor / Not loading | `static/chart.umd.min.js` ve `chartjs-adapter-date-fns.bundle.min.js` var mı? / Files exist? |
| Yazma geri alınıyor / Write reverted | 450 ms debounce + 6 sn optimistic reload zaten var; min=35 kontrolü yap / Debounce+reload exist; check min=35 |
| Servis başlamıyor / Service won't start | `journalctl -u tuya-heatpump.service -n 50` |

---

## 📁 Dosya Yapısı / File Structure

```
Tuya_Head_Pomp_manager/
├── app_local.py              # Ana Flask uygulaması (port 8902) / Main Flask app (port 8902)
├── requirements.txt          # Python bağımlılıkları / Python dependencies
├── tuya-heatpump.service     # systemd servis dosyası / systemd service file
├── byd.env                   # (opsiyonel) BYD credentials şablonu / BYD creds template
├── static/
│   ├── chart.umd.min.js              # Chart.js v4 UMD (lokal) / Chart.js v4 UMD (local)
│   └── chartjs-adapter-date-fns.bundle.min.js  # Date adapter
├── history.db                # SQLite geçmiş veritabanı (otomatik oluşur) / Auto-created
└── README.md                 # Bu dosya / This file
```

---

## 🔗 İlgili Projeler / Related Projects

- **EV Şarj Paneli / EV Charging Panel:** `app_ev.py` (port 8903) — Cloud API + Bluetooth proxy planlı / planned
- **BYD Araç Paneli / BYD Vehicle Panel:** `app_byd.py` (port 8904) — `pybyd` Cloud API, TR endpoint
- **ESP32-S3 Gateway:** BLE proxy + Zigbee coordinator + Matter border router + LVGL dashboard

---

## 📝 Lisans / License

MIT — Kişisel kullanım için özgür / Free for personal use.