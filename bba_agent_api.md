# BBA Console API — Proctoring server integratsiyasi uchun qo'llanma

> **Bu fayl kimga:** Proctoring serverida ishlayotgan Claude (yoki dasturchi) uchun. Vazifa: BBA Console
> API'sidan hududlar (region), xonalar (room), kompyuterlar (device) va ularning inventory'sini (shu
> jumladan MAC va UUID) olib, Proctoring serverida "bu kompyuter BBA Console'da ro'yxatdan o'tganmi?"
> degan tekshiruvni qilish.
>
> Hamma ma'lumot 2026-10-06 holatiga, Console'ning haqiqiy javoblari bilan tekshirilgan (agent 0.1.96).

---

## 0. Senga (Claude'ga) vazifa

Sen Proctoring serverida BBA Console bilan integratsiya yozasan. Maqsad:

1. BBA Console'dan **hudud → xona → kompyuter** daraxtini va har bir kompyuterning **hardware ID'larini**
   (system UUID, MAC'lar, ona plata seriyasi, TPM, ...) muntazam olib, Proctoring serverining o'z bazasida
   saqlash (sinxronizatsiya).
2. Test boshlanganda Proctoring dasturi yuborgan kompyuter ma'lumotlarini (MAC, UUID) shu baza bilan
   solishtirish. **Console'da yo'q yoki ID'lari mos kelmagan kompyuterga test sayti ochilmasligi kerak.**
3. Kerak bo'lsa monitoring (online/offline, cheat-hodisalar) va audit ma'lumotlarini ham olish.

Qoidalar:
- Console bilan **faqat o'qish** rejimida ishla. `POST /login` va `POST /logout`dan boshqa hech qanday
  `POST/PATCH/PUT/DELETE` so'rov yuborma. Job yuborish, kompyuterni boshqarish sening vazifang emas
  (hisobda bunga huquq ham yo'q).
- Login/parolni kodga yozma. Ular muhit o'zgaruvchilaridan (`BBA_USERNAME`, `BBA_PASSWORD`) olinsin.
- Console'ni ortiqcha yuklama: limitlar 7-bo'limda.

---

## 1. Ulanish

| | Qiymat |
|---|---|
| **Base URL (tavsiya)** | `https://172.16.222.2:8443` |
| Muqobil (faqat test uchun) | `http://console.local/api` — shifrlanmagan HTTP, token tarmoqda ochiq ketadi. Production'da ishlatma. |
| TLS | Console sertifikati BBA'ning **ichki CA**'si bilan imzolangan. Tizimning CA ro'yxatida yo'q. |

**CA sertifikatini bir marta yuklab ol** va har bir so'rovda shu bilan tekshir (`verify=False` yoki `-k`
**ishlatma**):

```sh
curl -sk https://172.16.222.2:8443/ca -o bba-ca.pem      # bir marta; keyin faylni saqlab qo'y
curl --cacert bba-ca.pem https://172.16.222.2:8443/regions   # endi to'liq TLS tekshiruvi bilan
```

Sertifikatda `172.16.222.2` va `console.local` bor, shuning uchun shu ikkala nom bilan tekshiruv o'tadi.
Proctoring server Console'ga **172.16.222.2:8443** porti orqali chiqa olishi kerak (MikroTik/firewall).

---

## 2. Autentifikatsiya

Console'da maxsus foydalanuvchi bor: **`proctoring`** (rol: `user`). Paroli administratorda.

### Login

```http
POST /login
Content-Type: application/json

{"username": "proctoring", "password": "..."}
```

Javob (200):

```json
{
  "token": "…",
  "role": "user",
  "username": "proctoring",
  "full_name": "Proctoring",
  "expires_at": "2026-10-07T14:05:08+05:00",
  "must_change_password": false
}
```

Keyingi har bir so'rovda:

```http
Authorization: Bearer <token>
```

Muhim:
- **Token 24 soat yashaydi** (`expires_at`). Muddati tugaganda yoki istalgan so'rov **401** qaytarsa, qayta
  `POST /login` qil va so'rovni bir marta qaytar.
- Har so'rovda login qilma. Tokenni xotirada saqla va qayta ishlat.
- **Login himoyasi:** 15 daqiqa ichida 5 marta noto'g'ri parol kiritilsa, login 15 daqiqaga bloklanadi
  (**429**). Noto'g'ri parol bilan login'ni siklda qaytarma. 401 kelsa, to'xta va xabar ber.
- `must_change_password: true` bo'lsa, hamma so'rov **403** "password change required" qaytaradi. Bunda
  administrator parolni qayta o'rnatishi kerak, integratsiya o'zi hal qilolmaydi.
- Ish tugaganda (masalan servis to'xtaganda) `POST /logout` tokenni bekor qiladi. Bu ixtiyoriy.

### Qaysi huquqlar borligini tekshirish: `GET /me`

```json
{
  "user": {...},
  "grants": [
    {"scope_type": "room", "scope_name": "Class-110", "region_name": "Toshkent Shahar",
     "room_id": "b7fb90b8-…", "region_id": "ee6858af-…", "permissions": ["view"]}
  ],
  "anywhere": [...],
  "global": [...]
}
```

---

## 3. Huquqlar modeli (nimani ko'ra olasan)

Console'da huquqlar **doiraga** (scope) beriladi: global, hudud (region), xona (room) yoki bitta kompyuter.
Hudud grant'i undagi barcha xona va kompyuterlarni, xona grant'i undagi kompyuterlarni qamraydi.

| Huquq | Nima beradi |
|---|---|
| `view` (UI'da "Monitoring") | Hudud/xona daraxti, kompyuterlar, inventory, online/offline tarixi, cheat-hodisalar, statistika. |
| `audit` | Shu doiradagi audit log (`GET /audit-log`). `audit` avtomatik `view`ni ham beradi. |

- **Hozir (2026-10-06):** `proctoring`da faqat **Toshkent Shahar → Class-110** xonasiga `view` huquqi bor.
  Keyinchalik administrator boshqa hududlarni ham qo'shadi. **Kod hech narsani qattiq yozib qo'ymasin**:
  hudud va xonalar ro'yxatini har safar API'dan ol.
- Ro'yxatlar **server tomonida avtomatik filtrlanadi**: sen faqat ruxsat berilgan narsani ko'rasan, boshqasi
  ro'yxatda umuman chiqmaydi. Doiradan tashqaridagi kompyuterga to'g'ridan-to'g'ri so'rov **403** qaytaradi.
- `audit` huquqi berilmagan bo'lsa, `GET /audit-log` **403** qaytaradi. Bu xato emas, shunchaki huquq yo'q.

---

## 4. Endpoint'lar

Umumiy qoidalar:
- Hammasi JSON. Vaqtlar ISO-8601, Toshkent vaqt mintaqasi bilan (`+05:00`).
- **Maydon nomlari:** asosiy obyektlar PascalCase (`ID`, `RegionID`, `Status`, `Hardware`), hisoblangan
  maydonlar va `Hardware`/`NetworkConfig` ichi esa snake_case (`device_count`, `system_uuid`, `mac`). Nomlarni
  aynan shu ko'rinishda ishlat.
- Ro'yxatlar `limit`/`offset` oladi va `{<kalit>: [...], "total": N}` qaytaradi. Faqat `/regions` va `/rooms`
  oddiy massiv qaytaradi.

### 4.1 Hududlar — `GET /regions`

Oddiy massiv qaytaradi, sahifalash yo'q (hududlar o'nlab xolos):

```json
[
  {"ID": "ee6858af-01bb-4287-9b1e-dc913cb5befd", "Name": "Toshkent Shahar", "Subnet": "172.16.0.0/16",
   "Code": "R-01", "GeneralRoomID": "…", "room_count": 3, "device_count": 14, "user_count": 2}
]
```

`device_count` faqat senga ko'rinadigan kompyuterlar soni.

### 4.2 Xonalar — `GET /rooms`

Oddiy massiv qaytaradi. Filtr parametri yo'q: hammasini ol va `RegionID` bo'yicha o'zing guruhla.

```json
[
  {"ID": "b7fb90b8-1913-4fe6-bdf9-a080f754167a", "RegionID": "ee6858af-01bb-4287-9b1e-dc913cb5befd",
   "Name": "Class-110", "Code": "RM-0003", "device_count": 10}
]
```

Har bir hududda avtomatik "General" xonasi bor (`GeneralRoomID`).

### 4.3 Kompyuterlar — `GET /devices`

| Parametr | Ma'nosi |
|---|---|
| `room_id` | Faqat shu xonadagilar |
| `region_id` | Faqat shu hududdagilar |
| `status` | `online` \| `offline_graceful` \| `offline_unexpected` \| `unknown` |
| `search` | Nomi bo'yicha qidiruv |
| `limit` | **1..500**. ⚠️ 500 dan katta qiymat xato bermaydi, jim **50 ga tushadi**. Doim `limit=500` ber. |
| `offset` | Sahifalash uchun: `total`ga yetguncha `offset += limit` |

```json
{
  "devices": [
    {
      "ID": "5de8ef40-ef17-464d-ba5a-f3c55915a790",
      "Status": "online",
      "RoomID": "b7fb90b8-1913-4fe6-bdf9-a080f754167a",
      "EnrolledAt": "2026-09-04T18:45:16+05:00",
      "LastSeenAt": "2026-10-06T13:01:23+05:00",
      "AgentVersion": "0.1.96",
      "RevokedAt": null,
      "HostnameCode": "BBA-110-3",
      "Hostname": "BBA-110-3",
      "TestModeEnabled": false,
      "TestModePolicy": {...}
    }
  ],
  "total": 10
}
```

- `ID` — kompyuterning **doimiy Console ID'si** (UUID). IP yoki MAC emas, o'zgarmaydi. Asosiy kalit sifatida
  shuni ishlat.
- `HostnameCode` — Console'dagi nomi (masalan `BBA-110-3`). `Hostname` — Windows'dagi nomi.
- `RevokedAt` `null` bo'lmasa, kompyuter Console'dan chiqarilgan: **unga test ruxsat berilmasin.**
- `RoomID` `null` bo'lsa, kompyuter hali xonaga biriktirilmagan.
- `Status`: `online` — hozir ulangan. `offline_graceful` — normal o'chirilgan. `offline_unexpected` — aloqa
  kutilmaganda uzilgan.

### 4.4 Inventory — `GET /devices/{id}/inventory`

Kompyuterning eng oxirgi inventory'si:

```json
{
  "snapshot": {
    "ID": "…",
    "DeviceID": "5de8ef40-…",
    "CapturedAt": "2026-10-06T14:01:40+05:00",
    "Hostname": "BBA-110-3",
    "OS": "windows", "Arch": "amd64",
    "OSVersion": "Windows 10 Pro 21H1 (Build 19043.928)",
    "LastBootAt": "2026-10-06T13:01:16+05:00",
    "InstalledSoftware": [{"name": "RustDesk", "version": "1.4.9…"}],
    "NetworkConfig": [
      {"name": "Ethernet 3", "mac": "30-C5-99-18-53-A1", "enabled": true, "dhcp": true,
       "addrs": ["192.168.0.57/24", "fe80::…/64"], "gateway": "192.168.0.254",
       "dns": ["192.168.200.200", "192.168.0.254"]}
    ],
    "Hardware": {
      "cpu": "13th Gen Intel(R) Core(TM) i5-13400F",
      "motherboard": "ASUSTeK COMPUTER INC. PRIME B760M-K",
      "storage": [{"model": "Lexar SSD NM620 512GB", "serial": "0000_0006_2505_2155_CAF2_5B03_6000_04A6.", "...": "..."}],
      "ram_modules": [{"manufacturer": "Apacer Technology", "serial_number": "00225245", "part_number": "D12.3528WT.001", "...": "..."}],
      "ids": {
        "system_uuid": "124023EC-FFF9-9177-3E7D-30C5991853A1",
        "system_vendor": "ASUS",
        "system_model": "System Product Name",
        "system_serial": "System Serial Number",
        "bios_serial": "System Serial Number",
        "baseboard_serial": "250861367400312",
        "cpu_id": "BFEBFBFF000B0671",
        "machine_guid": "a865c9f2-56ae-43c5-a9c4-d2d423d2ce34",
        "tpm_ek_hash": "8fcbaf1facb3b35bf26dd683f70f451e91e0205b89049b1cd4641d8d2e7bad2f",
        "network_adapters": [
          {"name": "Realtek PCIe GbE Family Controller #3", "mac": "C4-62-37-01-DE-1A"},
          {"name": "Realtek Gaming 2.5GbE Family Controller", "mac": "30-C5-99-18-53-A1"}
        ],
        "monitors": [{"name": "JRY HDMI", "serial": "000000000000"}]
      },
      "...": "gpus, monitors, keyboards, mice, audio_devices, ... (identifikatsiya uchun kerak emas)"
    },
    "StartupApps": [...]
  },
  "changes": null
}
```

- Inventory hech qachon yig'ilmagan bo'lsa `"snapshot": null` keladi. Buni "ma'lumot yo'q" deb qabul qil, xato
  deb emas.
- Agent inventory'ni **o'zi yuboradi**: har 15 daqiqada tekshiradi, o'zgarish bo'lsa darhol yuboradi, o'zgarish
  bo'lmasa ham kamida **6 soatda bir marta** yuboradi. `CapturedAt` — ma'lumot qachon olingani.
- `changes` — oldingi snapshot'dan nima o'zgargani haqida qisqa matn ro'yxati (yoki `null`).
- ⚠️ Har bir inventory so'rovi Console audit log'iga `view_device` yozuvi qo'shadi (bitta kompyuter uchun 10
  daqiqada ko'pi bilan bir marta). Shuning uchun inventory'ni bot kabi tez-tez so'rama, 6-bo'limdagi jadval
  bo'yicha ol.

### 4.5 Monitoring

| Endpoint | Nima beradi |
|---|---|
| `GET /stats` | Umumiy va hududlar bo'yicha holat: `{"overall": {"total","online","offline_graceful","offline_unexpected","unknown"}, "by_region": [{"region_id","region_name",...}]}` |
| `GET /devices/{id}/connectivity-events?limit=N` (N ≤ 200) | Online/offline tarixi: `{"events": [{"Kind": "connected" \| "disconnected_graceful" \| "disconnected_unexpected", "Detail", "OccurredAt", "ReportedAt"}]}` |
| `GET /cheat-events?device_id=&region_id=&exam_session_id=&limit=&offset=` | Agent aniqlagan shubhali holatlar: `{"events": [{"DeviceID","ExamSessionID","Kind","Detail":{...},"OccurredAt"}], "total"}`. `limit` ≤ 500. |

### 4.6 Audit (faqat `audit` huquqi berilsa)

`GET /audit-log?device_id=&action=&actor=&limit=&offset=` (`limit` ≤ 1000):

```json
{
  "entries": [
    {"ID": "…", "ActorUserID": "…", "ActorName": "admin", "Action": "create_job",
     "Target": {"device_id": "5de8ef40-…"}, "Detail": {"type": "list_local_users", "status": "sent"},
     "DeviceID": "5de8ef40-…", "OccurredAt": "2026-10-06T14:10:08+05:00"}
  ],
  "total": 2252
}
```

`audit` huquqi bo'lmasa **403** qaytadi, buni jim o'tkazib yubor.

---

## 5. MAC va UUID'ni to'g'ri olish va solishtirish

### Qaysi maydonlardan

| ID | Qayerdan | Ishonchliligi |
|---|---|---|
| **System UUID** | `Hardware.ids.system_uuid` | Asosiy kompyuter ID'si (SMBIOS). Placeholder bo'lishi mumkin (pastga qara). |
| **MAC'lar** | `Hardware.ids.network_adapters[].mac` (faqat **jismoniy** adapterlar) | Ishonchli, lekin Windows sozlamasidan oson o'zgartiriladi. |
| MAC (zaxira) | `NetworkConfig[].mac` | Virtual adapterlar ham kirishi mumkin. Faqat `ids` yo'q bo'lsa ishlat. |
| Ona plata seriyasi | `Hardware.ids.baseboard_serial` | Yaxshi qo'shimcha belgi. |
| TPM | `Hardware.ids.tpm_ek_hash` | Chipga xos, eng qiyin soxtalashtiriladi. TPM bo'lmasa bo'sh. |
| Windows MachineGuid | `Hardware.ids.machine_guid` | Windows qayta o'rnatilsa o'zgaradi. |
| Disk seriyasi | `Hardware.storage[].serial` | Disk almashtirilsa o'zgaradi. |
| CPU ID | `Hardware.ids.cpu_id` | ❌ **Yagona emas** (bir xil modeldagi barcha CPU'larda bir xil). Identifikatsiya uchun ishlatma. |

### Normalizatsiya (solishtirishdan oldin majburiy)

- **MAC:** Console `C4-62-37-01-DE-1A` formatida beradi. Proctoring dasturi `c4:62:37:01:de:1a` yoki
  `C46237…` yuborishi mumkin. Ikkala tomonni ham shunday keltir: ajratuvchilarni olib tashla, katta harfga o'tkaz
  → `C4623701DE1A`.
- **UUID:** katta harfga o'tkaz, chetdagi `{}` va bo'shliqlarni olib tashla.
- Boshqa seriyalar: chetdagi bo'shliqlarni olib tashla, katta harfga o'tkaz.

### Placeholder (soxta) qiymatlar — **ID sifatida ishlatma**

Ko'p ona platalar haqiqiy seriya o'rniga bir xil "to'ldiruvchi" yozadi va u minglab kompyuterda bir xil bo'ladi.
Masalan BBA-110-3'da `system_serial` va `bios_serial` = `"System Serial Number"`. Quyidagilarni "qiymat yo'q"
deb hisobla (katta-kichik harf farqsiz):

```
to be filled by o.e.m. | default string | system serial number | system product name | system manufacturer
base board serial number | chassis serial number | not specified | not applicable | none | o.e.m. | oem
invalid | 123456789 | 00000000-0000-0000-0000-000000000000 | ffffffff-ffff-ffff-ffff-ffffffffffff
03000200-0400-0500-0006-000700080009
```

Bundan tashqari **faqat `0` yoki faqat `F`dan iborat** har qanday qiymat ham placeholder (ajratuvchilar `- _ .`
va bo'shliq hisobga olinmaydi). Masalan monitor seriyasi `000000000000`.

### Eski agentlar

`Hardware.ids` faqat **agent 0.1.96 va undan yangi** versiyalarda bor. Eski agentda `ids` bo'lmaydi: bunda
faqat `NetworkConfig[].mac` mavjud, UUID yo'q. Kompyuterning versiyasi `GET /devices` → `AgentVersion`da.
Console agentlarni avtomatik yangilaydi.

### Tavsiya etilgan tekshiruv qoidasi

Proctoring dasturi test boshlanganda kompyuterdan `system_uuid` va jismoniy MAC'larni (iloji bo'lsa
`baseboard_serial` va `tpm_ek_hash`ni ham) olib serverga yuboradi. Server:

1. Normalizatsiya qiladi va placeholder'larni tashlaydi.
2. Mahalliy bazadan (6-bo'lim) qidiradi: `system_uuid` bo'yicha **va** MAC'lar bo'yicha.
3. **Ruxsat** faqat quyidagilarning hammasi bajarilsa beriladi:
   - topilgan kompyuter **bitta**;
   - `system_uuid` mos keladi (agar u placeholder bo'lmasa);
   - kamida **bitta jismoniy MAC** mos keladi;
   - `RevokedAt == null`.
   Qo'shimcha: `baseboard_serial` yoki `tpm_ek_hash` ikkala tomonda ham bor bo'lsa, ular ham mos kelishi
   kerak.
4. Aks holda **rad et** va sababini log'ga yoz (qaysi ID mos kelmadi). Shunda administrator tushuna oladi.

⚠️ **Halol cheklov:** MAC'ni Windows'da bir daqiqada o'zgartirish mumkin, UUID'ni esa virtual mashinada. Faqat
shu ikkisiga tayangan tekshiruvni bilgan odam aylanib o'tadi. Bundan tashqari, ba'zi ona platalar UUID'ni MAC'dan
yasaydi. Masalan BBA-110-3'da UUID `124023EC-FFF9-9177-3E7D-`**`30C5991853A1`** oxiri NIC 2'ning MAC'i bilan bir
xil. Ya'ni bunday platalarda UUID va MAC bir-biridan mustaqil ikkita belgi emas. Ona plata seriyasi va TPM
qo'shilsa, soxtalashtirish ancha qiyinlashadi. Kelajakdagi kuchliroq variant BBA jamoasi bilan kelishiladi: Proctoring dasturi
kompyuterdagi BBA Agent'dan uning sertifikat bilan tasdiqlangan Console ID'sini so'raydi.

---

## 6. Sinxronizatsiya algoritmi

```
har 15–30 daqiqada (yengil):
  token yo'q yoki 401 → POST /login
  regions = GET /regions
  rooms   = GET /rooms
  devices = GET /devices?limit=500&offset=0,500,1000,...  (total'gacha)
  → bazada region/room/device jadvallarini yangila (yangi qo'shilganlar, o'chirilganlar,
    RevokedAt, RoomID o'zgarishi, Status)

har 6 soatda (og'ir) + yangi paydo bo'lgan kompyuter uchun darhol:
  har bir device uchun GET /devices/{ID}/inventory
  snapshot != null bo'lsa → Hardware.ids, Hardware.storage[].serial, NetworkConfig[].mac'ni saqla
                            (CapturedAt bilan)
  so'rovlar orasida ~0.25 s pauza (7-bo'lim)
```

Bazadan kompyuterni o'chirma, chunki u vaqtincha ko'rinmay qolgan bo'lishi mumkin (masalan huquq olib qo'yilgan).
"Oxirgi ko'rilgan" vaqtini saqla va ro'yxatda yo'q kompyuterni **ruxsat berilmagan** deb hisobla.

Test boshlanganda Console'ga so'rov yuborish **shart emas**: tekshiruv mahalliy baza bo'yicha tez ishlaydi va
Console vaqtincha ishlamay qolsa ham to'xtamaydi.

---

## 7. Limitlar va xatolar

| Narsa | Qiymat |
|---|---|
| Umumiy so'rov limiti | **300 so'rov / daqiqa** bitta IP'dan. Oshsa **429** keladi: kut va qayta urin. 10 000 kompyuter inventory'si ~35 daqiqada olinadi, shunga moslab rejalashtir. |
| Login | 15 daqiqada 5 noto'g'ri urinish → 15 daqiqa blok (**429**) |
| `limit` maksimumi | devices / cheat-events: 500; audit-log: 1000; connectivity-events: 200. Oshsa jim standart qiymatga tushadi. |

| Kod | Ma'nosi | Nima qilish kerak |
|---|---|---|
| 200 | OK | |
| 401 | Token yo'q yoki eskirgan | Bir marta qayta login qil; yana 401 bo'lsa to'xta, parolni tekshir |
| 403 | Huquq yo'q (doiradan tashqari, `audit` yo'q yoki parol almashtirish talab qilinadi) | Shu resursni o'tkazib yubor, log'ga yoz |
| 404 | Topilmadi | O'tkazib yubor |
| 429 | Limit oshdi | 30–60 s kut, keyin davom et |
| 5xx | Console xatosi | Eksponensial kutish bilan qayta urin. Mahalliy bazadagi ma'lumot bilan ishlashda davom et. |

---

## 8. Namuna mijoz (Python, faqat standart kutubxona)

```python
import json, os, ssl, time, urllib.error, urllib.request

BASE = os.environ.get("BBA_URL", "https://172.16.222.2:8443")
CA = os.environ.get("BBA_CA", "bba-ca.pem")   # GET /ca dan bir marta yuklab olingan
USER, PASSWORD = os.environ["BBA_USERNAME"], os.environ["BBA_PASSWORD"]

_ctx = ssl.create_default_context(cafile=CA)
_token = None

def _call(method, path, body=None, auth=True):
    req = urllib.request.Request(BASE + path, method=method,
                                 data=json.dumps(body).encode() if body is not None else None)
    req.add_header("Content-Type", "application/json")
    if auth:
        req.add_header("Authorization", "Bearer " + _token)
    with urllib.request.urlopen(req, context=_ctx, timeout=30) as r:
        return json.loads(r.read() or b"null")

def login():
    global _token
    _token = _call("POST", "/login", {"username": USER, "password": PASSWORD}, auth=False)["token"]

def get(path):
    if _token is None:
        login()
    for attempt in range(5):
        try:
            return _call("GET", path)
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                login(); continue
            if e.code == 429 or e.code >= 500:
                time.sleep(min(60, 5 * 2 ** attempt)); continue
            raise
    raise RuntimeError("BBA Console unavailable: " + path)

def all_devices(**filters):
    out, offset = [], 0
    while True:
        q = "&".join(f"{k}={v}" for k, v in filters.items())
        page = get(f"/devices?limit=500&offset={offset}&{q}")
        out += page["devices"]
        offset += 500
        if offset >= page["total"]:
            return out

PLACEHOLDERS = {"to be filled by o.e.m.", "default string", "system serial number", "system product name",
                "system manufacturer", "base board serial number", "chassis serial number", "not specified",
                "not applicable", "none", "o.e.m.", "oem", "invalid", "123456789",
                "00000000-0000-0000-0000-000000000000", "ffffffff-ffff-ffff-ffff-ffffffffffff",
                "03000200-0400-0500-0006-000700080009"}

def clean_id(v):
    """Normalized ID, or None for an empty or placeholder value."""
    s = (v or "").strip().strip("{}").strip()
    core = "".join(c for c in s.lower() if c not in "-_. ")
    if not s or s.lower() in PLACEHOLDERS or not core or set(core) <= {"0"} or set(core) <= {"f"}:
        return None
    return s.upper()

def norm_mac(v):
    m = "".join(c for c in (v or "") if c.isalnum()).upper()
    return m if len(m) == 12 and clean_id(m) else None

def device_ids(inv):
    """Hardware IDs from one GET /devices/{id}/inventory response."""
    snap = inv.get("snapshot")
    if not snap:
        return None
    hw = snap.get("Hardware") or {}
    ids = hw.get("ids") or {}
    macs = [n.get("mac") for n in ids.get("network_adapters") or []] \
        or [n.get("mac") for n in snap.get("NetworkConfig") or []]      # agent < 0.1.96
    return {
        "captured_at": snap.get("CapturedAt"),
        "system_uuid": clean_id(ids.get("system_uuid")),
        "baseboard_serial": clean_id(ids.get("baseboard_serial")),
        "tpm_ek_hash": clean_id(ids.get("tpm_ek_hash")),
        "machine_guid": clean_id(ids.get("machine_guid")),
        "macs": sorted({m for m in map(norm_mac, macs) if m}),
        "disk_serials": [s for s in (clean_id(d.get("serial")) for d in hw.get("storage") or []) if s],
    }

if __name__ == "__main__":
    regions = {r["ID"]: r for r in get("/regions")}
    rooms = {r["ID"]: r for r in get("/rooms")}
    for d in all_devices():
        room = rooms.get(d["RoomID"] or "", {})
        region = regions.get(room.get("RegionID", ""), {})
        ids = device_ids(get(f"/devices/{d['ID']}/inventory"))
        print(region.get("Name"), "/", room.get("Name"), "/", d["HostnameCode"], d["Status"],
              "revoked" if d["RevokedAt"] else "", json.dumps(ids))
        time.sleep(0.25)
```

Ishga tushirish:

```sh
curl -sk https://172.16.222.2:8443/ca -o bba-ca.pem
BBA_USERNAME=proctoring BBA_PASSWORD='…' python3 bba_sync.py
```

---

## 9. Qisqa xulosa (eslab qol)

- `POST /login` → Bearer token (24 soat), 401 bo'lsa qayta login.
- `GET /regions`, `GET /rooms` → daraxt. `GET /devices?limit=500&offset=…` → kompyuterlar.
- `GET /devices/{ID}/inventory` → `snapshot.Hardware.ids` (UUID, MAC, seriyalar). 6 soatda bir marta yetarli.
- MAC'ni `C4623701DE1A` ko'rinishiga keltir, placeholder'larni tashla, CPU ID'ni ishlatma.
- `RevokedAt != null` yoki ro'yxatda yo'q → test ruxsat etilmaydi.
- Faqat o'qish. 300 so'rov/daqiqa. CA sertifikati bilan HTTPS.
- Huquqlar keyin kengayadi (hamma hududlar, `audit`): kod hech narsani qattiq yozib qo'ymasin.
