# Tuya R32 Heat Pump Manager (NECLA_EV_ISITMA)

Yerel ağ (LAN) üzerinden Axen KS-100W / R32 Isı Pompası izleme ve kontrol paneli.  
Tailscale ile uzaktan erişim, SQLite geçmiş veritabanı, Chart.js grafikler, glassmorphism UI.

---

## 🎯 Özellikler

- **Tam yerel iletişim** — `tinytuya` protokol 3.5, Cloud'a bağımlı değil
- **Canlı durum** — 19 DP okuma (sıcaklıklar, modlar, fanlar, kompresör, EEV, su debisi, voltaj/akım)
- **Kontrol** — Ana güç, ısıtma/su/auto hedefleri (35-60°C), çalışma modu (heat/auto/hot_water/heat_hot_water), sessiz/tatil modu
- **Geçmiş grafik** — 8 sıcaklık serisi, 4 zaman aralığı (1h/6h/24h/7d), 10 dk otomatik yenileme
- **Seri gizle/göster** — Checkbox legend + "Hepsi Seç / Tümünü Kaldır" butonları
- **Sistem servisi** — `systemd` ile açılışta otomatik başlatma, `Restart=always`
- **Tailscale erişim** — `http://100.125.108.13:8902/` (herhangi bir yerden)

---

## 📦 Kurulum

### 1. Bağımlılıklar

```bash
sudo apt update && sudo apt install python3-venv sqlite3
cd /home/tekinaltun/projects/Tuya_Head_Pomp_manager
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. Tuya Cloud Credentials (bir kez)

- https://iot.tuya.com → Cloud → Project oluştur (Smart Home, Custom)
- **Access ID** / **Access Secret** kopyala
- Devices → Link Tuya App Account → SmartLife hesabını QR ile bağla
- Service API: IoT Core, Authorization, Device Status Notification etkinleştir

### 3. Wizard ile Local Key Alma

```bash
cd /home/tekinaltun/projects/Tuya_Head_Pomp_manager
./venv/bin/python -m tinytuya wizard
# Access ID, Access Secret, Region (eu) gir
# SmartLife App UID istenirse gir
# devices.json ve snapshot.json oluşur
```

### 4. Cihaz Konfigürasyonu

`app_local.py` dosyasını aç ve şunları güncelle:

```python
DEVICE_ID = "bfb3e7b67f3df5e451iqgh"      # Isı pompası Device ID
LOCAL_KEY = "}!g2>gk_Rlqrq`Mh"            # Wizard'dan alınan Local Key
DEVICE_IP = "192.168.1.164"               # Yerel IP (aynı ağda)
DEVICE_VERSION = 3.5                       # Protokol versiyonu
```

> **Not:** Eğer cihaz farklı bir IP'de ise `tinytuya scan` ile bulabilirsiniz.

### 5. Systemd Servisi

```bash
sudo cp tuya-heatpump.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now tuya-heatpump.service
sudo systemctl status tuya-heatpump.service
```

Servis logları:
```bash
journalctl -u tuya-heatpump.service -f
```

---

## 🌐 Erişim

| Ortam | URL |
|-------|-----|
| Yerel ağ | `http://<makine-ip>:8902/` |
| Tailscale | `http://100.125.108.13:8902/` |

---

## 📊 DP Şeması (Kaynak: github.com/make-all/tuya-local)

| DP | Açıklama | Tip | Ölçek | Yazılabilir |
|----|----------|-----|-------|-------------|
| 1 | Ana Güç | Bool | - | ✅ |
| 6 | Hata Kodu | Enum | - | ❌ |
| 101 | Sessiz Mod | Bool | - | ✅ |
| 103 | Isıtma/Auto Hedef | Temp | ÷10 °C | ✅ (35-60) |
| 104 | Sıcak Su (CWU) Hedef | Temp | ÷10 °C | ✅ (20-60) |
| 105 | Auto Modu Hedef | Temp | ÷10 °C | ✅ (5-25) |
| 106 | Giriş Suyu | Temp | ÷10 °C | ❌ |
| 107 | Çıkış Suyu | Temp | ÷10 °C | ❌ |
| 108 | Tank Sıcaklığı | Temp | ÷10 °C | ❌ |
| 109 | Çalışma Modu | Enum | heat/auto/hot_water/heat_hot_water | ✅ |
| 118 | Dış Hava | Temp | ÷10 °C | ❌ |
| 119 | Egzoz/Deşarj | Temp | ÷10 °C | ❌ |
| 120 | Dönüş (Emme) | Temp | ÷10 °C | ❌ |
| 121 | Kompresör Frekansı | Int | Hz | ❌ |
| 122 | Ana EEV Açıklığı | Int | step | ❌ |
| 123 | Yardımcı EEV | Int | step | ❌ |
| 124 | AC Fan Durumu | Enum | close/low/high | ❌ |
| 125 | DC Fan 1 Hızı | Int | RPM | ❌ |
| 126 | DC Fan 2 Hızı | Int | RPM | ❌ |
| 127 | Su Debisi | Float | m³/h | ❌ |
| 128 | Voltaj | Float | V | ❌ |
| 129 | Akım | Float | A | ❌ |
| 165 | Tatil Modu | Bool | - | ✅ |

**Önemli:** DP103 (Isıtma hedefi) cihaz donanımında **35°C alt sınırı** vardır. 35 altı gönderilirse cihaz sessizce reddeder.

---

## 🗄️ Geçmiş Veritabanı

- **Dosya:** `history.db` (SQLite)
- **Tablo:** `readings(ts INTEGER, dp TEXT, value REAL, PRIMARY KEY(ts, dp))`
- **Toplayıcı:** APScheduler, her 10 dk bir çalışır (DP: 103,104,105,106,107,108,118,119,120)
- **API:** `GET /history?hours=24&dps=103,104,106...`

---

## 🔧 Sorun Giderme

| Sorun | Çözüm |
|-------|-------|
| "Connection refused" | Cihaz IP/Local Key yanlış; `tinytuya scan` ile doğrula |
| Grafik boş | `/history?hours=24` endpoint'ini test et; `history.db` dolu mu? |
| Chart.js yüklenmiyor | `static/chart.umd.min.js` ve `chartjs-adapter-date-fns.bundle.min.js` var mı? |
| Yazma geri alınıyor | 450 ms debounce + 6 sn optimistic reload zaten var; min=35 kontrolü yap |
| Servis başlamıyor | `journalctl -u tuya-heatpump.service -n 50` |

---

## 📁 Dosya Yapısı

```
Tuya_Head_Pomp_manager/
├── app_local.py              # Ana Flask uygulaması (port 8902)
├── requirements.txt          # Python bağımlılıkları
├── tuya-heatpump.service     # systemd servis dosyası
├── byd.env                   # (opsiyonel) BYD credentials şablonu
├── static/
│   ├── chart.umd.min.js              # Chart.js v4 UMD (lokal)
│   └── chartjs-adapter-date-fns.bundle.min.js  # Date adapter
├── history.db                # SQLite geçmiş veritabanı (otomatik oluşur)
└── README.md                 # Bu dosya
```

---

## 🔗 İlgili Projeler

- **EV Şarj Paneli:** `app_ev.py` (port 8903) — Cloud API + Bluetooth proxy planlı
- **BYD Araç Paneli:** `app_byd.py` (port 8904) — `pybyd` Cloud API, TR endpoint
- **ESP32-S3 Gateway:** BLE proxy + Zigbee coordinator + Matter border router + LVGL dashboard

---

## 📝 Lisans

MIT — Kişisel kullanım için özgür.