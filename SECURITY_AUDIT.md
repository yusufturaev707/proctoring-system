# Xavfsizlik auditi — Proctoring System

**Sana:** 2026-09-26
**Qamrov:** Backend (Django/DRF), Frontend (React SPA), Desktop client (PyQt6)
**Metodika:** Statik kod tahlili (manual code review), arxitektura/trust-boundary tahlili. Ishlaydigan exploit yozilmagan — faqat muammo va tuzatish yo'nalishi ko'rsatilgan.
**Muallif:** Claude (Sonnet 5), loyiha egasi bilan bosqichma-bosqich ishlab chiqilgan.

> **Muhim eslatma qamrov haqida.** Bu audit to'liq penetration test emas — kod statik o'qilgan, ishga tushirilmagan, fuzzing/dynamic scanning qilinmagan. Backendda quyidagilar **chuqur ko'rilmagan**: `controls/services.py`ning to'liq qolgan qismi, `proctoring/services/{evidence,screenshots,risk,tasks}.py` ichki mantig'ining har bir qatori, `exams/api/v1/views.py`, `devices/api/v1/views.py`, barcha Django `admin.py` fayllari, `users/management/commands/seed_base_data.py`, Celery `tasks.py`ning to'liq matni. Bu yerlarda topilmagan zaiflik yo'q degani emas — "tekshirilmagan maydon" sifatida ochiq qayd etaman.

---

## 1. Xulosa jadvali

| ID | Component | Muammo | Severity | Ta'siri | Tuzatish (qisqacha) |
|---|---|---|---|---|---|
| AUDIT-01 | Backend / proctoring | Machine UUID mos kelmasligi faqat handshake'da tekshiriladi va faqat ogohlantirish beradi; bron o'chirilgan bo'lsa imtihon oqimining qolgan qismida MAJBURLANMAYDI | **HIGH** | Klonlangan/ko'chirilgan mashina obrazi standart konfiguratsiyada aniqlanmasdan ishlayveradi — funksiyaning asosiy maqsadi bekor bo'ladi | `ProctoringStartView`/`ExamAccessView`da `verify_machine()` ni qayta chaqirish va rad etish |
| AUDIT-02 | Backend / proctoring | `screenshots/commit/` (S3 yo'li) client aytgan `object_key`ni egalik/mavjudlik tekshirmasdan qabul qiladi | MEDIUM | Sessiya o'z metadatasini boshqa (bilingan) kalitga bog'lay oladi — dalil yaxlitligi buziladi | Kalit prefiksini `session.public_id` bilan solishtirish + ixtiyoriy `head_object` |
| AUDIT-03 | Arxitektura | FaceID balli va AI xulq-atvor hodisalarining `severity`si to'liq clientda hisoblanadi, serverda mustaqil tasdiqlanmaydi | MEDIUM (ataylab, lekin auditda alohida qayd etilishi shart) | Patch qilingan client real vaqtda "hammasi joyida" signalini yoki past `severity` ni soxtalashtirishi mumkin | Tasodifiy namunada server-tomon audit (`FACE_RANDOM_AUDIT_RATE` mavjud, ishlatilmaydi) |
| AUDIT-04 | Frontend | JWT access + refresh tokenlar `localStorage`da saqlanadi | MEDIUM | Kelajakdagi XSS ikkala tokenni ham o'g'irlashga imkon beradi | CSP qo'shish (AUDIT-05) yoki `httpOnly` cookie'ga o'tish |
| AUDIT-05 | Frontend/Infra | Content-Security-Policy header umuman yo'q (nginx ham, `index.html` ham) | MEDIUM | XSS paydo bo'lsa uning ta'sirini cheklovchi eng arzon himoya yo'q | `nginx.conf.example`ga qat'iy CSP qo'shish |
| AUDIT-06 | Backend / integrations | `Exam.site_url`ga SSRF cheklovi yo'q (loopback/RFC1918/link-local) | LOW | Administrator hisobi buzilsa, backend serveri ichki tarmoq/metadata xizmatlariga so'rov yubortirilishi mumkin | Host validatsiyasi + `allow_redirects=False` |
| AUDIT-07 | Backend / config | `JWT_SIGNING_KEY` alohida majburlanmaydi (standart — `SECRET_KEY`) | LOW/INFO | Kalitlar ajratilmaganda bitta kalit sizib chiqishi ikkala tizimga ta'sir qiladi | `production.py`dagi majburiy-sir tekshiruviga qo'shish |
| AUDIT-08 | Backend / devices | Kamera RTSP kredensiali bekor qilinmaydi — faqat operatsion nazoratga (parol almashtirish) tayanadi | LOW/INFO | Buzilgan client uzoq muddat kamera oqimini ko'rishda davom etishi mumkin | Deploy runbook'da faqat-o'qish, davriy almashtiriladigan hisob talabini qattiqlashtirish |
| AUDIT-09 | Desktop client | O'rnatuvchi/`.exe` Authenticode imzosiz, nashr checksum'i yo'q | LOW | Ichki tarqatish kanalida almashtirilgan `.exe`ni aniqlash imkoni yo'q | Kod-imzo sertifikati + SHA-256 manifest e'lon qilish |
| AUDIT-10 | Desktop client | Lokal HTTP xizmat (`:8050`) `Origin`siz so'rovlarni domen tekshiruvidan o'tkazadi | INFO | Faqat mashina allaqachon buzilgan holatda ahamiyatli (kod bajarish talab qiladi) | Kelajakda yangi endpoint qo'shilganda ehtiyot bo'lish; hozircha o'zgartirish shart emas |
| AUDIT-11 | Desktop client | TLS sertifikat pinning yo'q, faqat OS CA do'koni | INFO | Mashina administrator darajasida buzilgan holatda MITM imkoniyati | Yuqori xavfsizlik talab qilinsa pinning qo'shish |

**Umumiy xulosa:** CRITICAL darajali va tashqi, autentifikatsiyalanmagan hujumchi tomonidan bevosita ekspluatatsiya qilinadigan HIGH zaiflik topilmadi. Kod bazasi o'ziga xos yuqori darajada mudofaalangan (constant-time compare, atomik race-condition himoyasi, path traversal + symlink himoyasi, mass-assignment/privilege-escalation validatorlari, IP-spoofing testlari). Topilgan yagona HIGH (AUDIT-01) ham tashqi tarmoqdan emas, balki **ichki, allaqachon autentifikatsiyalangan** actor (operator yoki klonlangan mashina) tomonidan ekspluatatsiya qilinadi.

---

## 2. Critical va High topilmalar (batafsil)

### AUDIT-01 — Machine UUID tekshiruvi imtihon oqimida majburlanmaydi

**Component:** `backend/src/apps/proctoring/api/v1/client_views.py` (`HandshakeView`, `ExamAccessView`, `ProctoringStartView`) + `backend/src/apps/devices/services.py:verify_machine`

**Tavsif.** `verify_machine()` — client aytgan SMBIOS Machine UUID/MAC ni `Computer.machine_uuid`/`mac_address` bilan solishtiruvchi funksiya — kod bo'ylab **faqat bir marta** chaqiriladi: `HandshakeView.post()` ichida (`client_views.py:429`). Natija (`machine["allowed"]`) HTTP javobida qaytadi, lekin bu — **faqat rasmiy clientga ko'rsatma**: "Davom etish"ni bloklash yoki bloklamaslik qarori to'liq client kodida.

Keyingi hech bir endpoint (`CandidateLookupView`, `FaceVerifyView`, `IdentityConfirmView`, `ExamAccessView`, `ProctoringStartView`, `SessionFinishView`) bu tekshiruvni qayta chaqirmaydi va sessiyaga bog'lab saqlamaydi.

Yagona server-tomonidagi qat'iy to'siq — `apps/exams/bookings.py:resolve_candidate_seat()` — lekin u faqat `bookings_enforced(schedule)` `True` bo'lganda (ya'ni `REQUIRE_COMPUTER_BOOKING=true` YOKI o'sha test sessiyasida kamida bitta bron mavjud bo'lganda) ishlaydi. Bu — **standart bo'lmagan** holat (`REQUIRE_COMPUTER_BOOKING` standart qiymati `False`, `settings/base.py:466`).

**Root cause.** Mashina tekshiruvi bitta, dastlabki nuqtada (login) joylashtirilgan va uning natijasi sessiya hayot sikliga "yopishtirilmagan" — keyingi har bir muhim qadam (ayniqsa `proctoring/start/`, WebView ochilishidan oldingi so'nggi darvoza) buni mustaqil tekshirmaydi.

**Ta'sir.** CLAUDE.md o'zi bu funksiyaning maqsadini shunday izohlaydi: *"mashina obrazi ko'chirilganda (imtihon markazlarida odatiy amaliyot) ... o'nlab mashina bitta `device_id` bilan ishlab, barcha sessiyalar bitta kompyuterga yozilardi"* — aynan shu holatni oldini olish uchun yaratilgan. Amalda, bron tizimi ishlatilmasa (odatiy holat):

1. Bir nechta jismoniy mashinada (bir xil obrazdan klonlangan, ya'ni bitta `device_id.json`ga ega) parallel ishga tushirilgan clientlar hech qanday server-tomon to'siqsiz sessiyalarni ochib, imtihonlarni to'liq o'tkazib yuborishi mumkin — server buni "bir xil kompyuterda" deb hisoblaydi, aslida turli fizik mashinalarda bo'lsa ham.
2. Operator (yoki texnik jihatdan tayyorlangan xodim) `machine.allowed == false` ogohlantirishini ko'rib ham, patch qilinmagan/qayta yozilgan client bilan davom ettirishi mumkin — chunki server keyingi qadamlarda buni tekshirmaydi.

**Ekspluatatsiya sharti (Confirmed emasligi uchun izoh):** bu — allaqachon autentifikatsiyalangan, ro'yxatdan o'tgan qurilma va xodim JWT'siga ega bo'lgan actor. Tashqi, anonim hujumchi bunga kira olmaydi. Shuning uchun CVSS-mantiqidagi **Privileges Required: High**, lekin **Impact: High** (funksiyaning butun maqsadini bekor qiladi) — natijada umumiy **HIGH** deb baholanadi.

**Holat: CONFIRMED** (kodda to'g'ridan-to'g'ri ko'rinadi — `verify_machine` chaqiruvlari faqat bitta joyda).

**Xavfsiz variant:**

```python
# apps/proctoring/api/v1/client_serializers.py
class ProctoringStartSerializer(serializers.Serializer):
    ai_profile = serializers.CharField(max_length=8, required=False, allow_blank=True, default="")
    machine_uuid = MachineUuidField()
    mac_address = serializers.CharField(max_length=17, required=False, allow_blank=True,
                                         validators=[mac_address_validator])

# apps/proctoring/api/v1/client_views.py
class ProctoringStartView(SessionRequiredView):
    def post(self, request):
        serializer = ProctoringStartSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        session = self.session
        device = self.device
        machine = device_services.verify_machine(
            device,
            machine_uuid=serializer.validated_data.get("machine_uuid", ""),
            mac_address=serializer.validated_data.get("mac_address", ""),
        )
        if settings.PROCTORING["REQUIRE_MACHINE_MATCH"] and machine["status"] not in (
            device_services.MACHINE_OK, device_services.MACHINE_UNKNOWN,
        ):
            raise DomainError(
                "Mashina identifikatori login paytidan farq qiladi — administratorga murojaat qiling",
                code="machine_mismatch",
            )
        ...
```

Shu bilan bir qatorda, `HandshakeView`da bog'langan `machine_uuid`/holatni sessiyaga (`ExamSession.meta.machine_check`) yozib qo'yish va uni keyingi qadamlarda solishtirish ham muqobil yechim — ikkinchi HTTP so'rovi shart emas, lekin handshake va start orasida qurilma almashtirilishini tutmaydi (kam ehtimolli, lekin mumkin bo'lgan holat).

---

## 3. Medium/Low topilmalar (batafsil)

### AUDIT-02 — Skrinshot commit: `object_key` egaligi tasdiqlanmaydi

**Component:** `apps/proctoring/api/v1/client_views.py:1513-1541` (`ScreenshotCommitView`) → `apps/proctoring/services/ingest.py:181-220` (`push_screenshot_meta`)

S3 yo'lida `screenshots/presign/` server tomonidan sessiyaga bog'langan kalit yaratadi (`build_object_key(session.public_id, kind)`), lekin `screenshots/commit/` bosqichida client yuborgan `object_key` (erkin satr, 500 belgigacha) **hech qanday tekshiruvsiz** qabul qilinadi: kalit sessiyaning o'z prefiksiga tegishli ekani solishtirilmaydi, obyekt S3'da mavjudligi/hajmi tasdiqlanmaydi.

**Ta'sir.** Amaldagi sessiya (haqiqiy token bilan) `object_key`ga o'zboshimchalik bilan qiymat yuborib, boshqa (bilingan) sessiyaning haqiqiy faylini yoki mavjud bo'lmagan kalitni o'ziga bog'lay oladi — proktor panelida noto'g'ri/soxta "dalil" ko'rinishi mumkin. Ekspluatatsiya kalitni bilishni talab qiladi (ikki UUID, 128-bit) — tasodifiy hujum ehtimoli past, lekin ikkinchi qatlam yo'qligi o'zi kamchilik.

**Severity: MEDIUM.** **Holat: CONFIRMED.**

**Tuzatish:**
```python
def push_screenshot_meta(*, session, object_key: str, ...):
    if f"/{session.public_id}/" not in object_key:
        raise ScreenshotRejected("object_key bu sessiyaga tegishli emas")
    ...
```

### AUDIT-03 — FaceID balli va AI hodisa `severity`si to'liq client hisoblaydi

**Component:** `apps/proctoring/services/session.py:verify_initial_face`, `apps/proctoring/services/ingest.py:push_event/push_events_batch` (`severity` maydoni, `IMMEDIATE_SEVERITY` va `MONITOR_MIN_SEVERITY` bilan taqqoslash)

Ikki alohida, lekin bog'liq fakt:
1. Yuz o'xshashlik balli (0-100) to'liq clientda hisoblanadi (cosine similarity), server faqat chegara bilan solishtiradi — **"server ballni qayta hisoblay olmaydi"** (kod docstring'i, ochiq e'tirof).
2. Har bir xulq-atvor hodisasining `severity`si (0-4) **client tomonidan** belgilanadi va bu qiymat: (a) hodisa write-behind buferini chetlab, darhol yozilishini, (b) proktorning jonli ekraniga real-vaqtli chiqishini (`MONITOR_MIN_SEVERITY` filtri), (c) qanchalik "kritik" ko'rsatilishini — TO'G'RIDAN-TO'G'RI hal qiladi. `EventRiskWeight` modelida jiddiylik ustuni ATAYLAB olib tashlangan (`controls.0011` migratsiyasi) — bu ongli arxitektura qarori.

**Ta'sir.** Patch qilingan/o'zgartirilgan client: (a) FaceID balini har doim chegaradan yuqori qilib yuborishi, (b) haqiqatan kritik hodisani `severity=0` bilan yuborib, uni proktorning jonli e'tiboridan berkitib qo'yishi mumkin. Bu — mahsulotning **markaziy** ishonch chegarasi.

**Kompensatsiya:** operator hujjat bo'yicha shaxsni jonli tasdiqlaydi (FaceID balliga bog'liq emas); skrinshot va dalil kadrlari (rasm/video) baribir saqlanadi va inson tomonidan keyinchalik ko'rib chiqilishi mumkin — ya'ni **avtomatik real-vaqtli signal** soxtalashtirilsa ham, **postfactum tekshiruv uchun dalil** saqlanib qoladi (agar dalil yig'ish o'zi ham `severity`/`confidence` chegarasiga bog'liq bo'lmasa — bu nuqta chuqurroq tekshirilmagan, yuqoridagi qamrov eslatmasiga qarang).

**Severity: MEDIUM** (arxitektura darajasida ongli qabul qilingan xavf, lekin auditda buni "yo'q" deb ko'rsatish noto'g'ri bo'lardi — shuning uchun alohida qayd etiladi). **Holat: CONFIRMED — dizayn bo'yicha.**

**Tavsiya:** `Setting.faceid_audit_rate` maydoni mavjud, lekin CLAUDE.md o'zi tasdiqlaydi — "ishlatilmaydi". Agar resurs ruxsat bersa, past chastotali (masalan 5%) server-tomon qayta tekshiruv (namunaviy kadrlarni saqlab, keyinroq offline ML orqali solishtirish) qo'shish — bu to'liq real-vaqtli yechim emas, lekin fitna/spoofing ehtimolini statistik pasaytiradi va apellyatsiya vaqtida qo'shimcha dalil beradi.

### AUDIT-04 va AUDIT-05 — Frontend: `localStorage` tokenlar + CSP yo'qligi

**Component:** `frontend/src/api/client.js:5-19`, `frontend/index.html`, `backend/deploy/nginx.conf.example:38-40`

JWT access (`proctoring.access`) va refresh (`proctoring.refresh`) tokenlar `localStorage`da saqlanadi — `httpOnly` cookie emas. Buning yonida CSP header mutlaqo yo'q (na `<meta>` tegi, na nginx `add_header`). Ikkalasi birga o'qilganda: kelajakda paydo bo'lishi mumkin bo'lgan har qanday XSS (dependency zaifligi, kod xatosi) to'g'ridan-to'g'ri va to'liq sessiya o'g'irlanishiga olib keladi, va bunga qarshi hech qanday brauzer-darajasidagi himoya yo'q.

**Severity: MEDIUM** (har ikkisi alohida past-o'rta, birga past-yuqori). **Holat: CONFIRMED.**

**Tavsiya:**
```nginx
add_header Content-Security-Policy "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data: blob:; connect-src 'self' wss: https:; object-src 'none'; frame-ancestors 'none'; base-uri 'self'" always;
```
Uzoq muddatda: token saqlashni `httpOnly` + `SameSite=Strict` cookie'ga ko'chirish (bu `CORS_ALLOW_CREDENTIALS`/CSRF strategiyasini qayta ko'rib chiqishni talab qiladi — kattaroq o'zgarish, alohida rejalashtirish kerak).

### AUDIT-06 — SSRF potentsiali: `Exam.site_url`

**Component:** `apps/integrations/exam_site.py:194-244` (`_request`, `check_candidate`)

Backend administrator sozlagan `site_url`ga (+ shifrlangan sarlavha bilan) `GET` so'rovi yuboradi; host validatsiyasi (loopback/RFC1918/link-local blokировкаsi) yo'q, `allow_redirects` aniq `False` qilinmagan.

**Ekspluatatsiya sharti:** faqat `exams.manage` (respublika darajasi) ruxsatiga ega administrator hisobi buzilgan taqdirda dolzarb (confused deputy). **Severity: LOW.** **Holat: POTENTIAL** (nazariy — amaliy PoC yozilmagan, lekin kodda tasdiqlangan cheklov yo'qligi).

### AUDIT-07 — `JWT_SIGNING_KEY` alohida majburlanmaydi

`config/settings/base.py:367`: standart holatda `SECRET_KEY`dan foydalanadi. `production.py` faqat `SECRET_KEY`/`TOKEN_HASH_KEY`/`FIELD_ENCRYPTION_KEY`ni tekshiradi. **Severity: LOW/INFO** (hardening, aktiv zaiflik emas). **Holat: CONFIRMED.**

### AUDIT-08 — Kamera RTSP kredensiali bekor qilinmaydi

`apps/devices/services.py:issue_camera_stream`. Kodda va CLAUDE.md'da to'liq va ochiq tan olingan: `CAMERA_STREAM_GRANT_TTL` faqat audit yozuvi chastotasini cheklaydi, kredensialning o'zi (RTSP parol) serverdan bekor qilinmaydi — himoya operatsion (kameralarda alohida, faqat-o'qish, davriy almashtiriladigan hisob). **Severity: LOW/INFO.** **Holat: CONFIRMED — dizayn, hujjatlashtirilgan.**

### AUDIT-09 — Kod imzosi va checksum yo'q

`client/installer/README.md`, `build.ps1`. Authenticode imzosi yoki nashr checksum'i haqida hech narsa yo'q. Ichki tarqatish kanalida (fayl serveri, USB) almashtirilgan `.exe`ni aniqlash imkoni yo'q. **Severity: LOW.** **Holat: CONFIRMED.**

### AUDIT-10, AUDIT-11 — INFO darajasidagi arxitektura eslatmalari

- **AUDIT-10:** `client/services/local_service.py:origin_allowed` — `Origin` sarlavhasisiz so'rov domen tekshiruvidan o'tadi (ataylab, brauzer bo'lmagan mijozlar uchun). Faqat mashina allaqachon buzilgan holatda ahamiyatli.
- **AUDIT-11:** Desktop clientda TLS sertifikat pinning yo'q, faqat OS CA do'koniga tayanadi (`API_SSL_VERIFY`). Standart amaliyot, lekin yuqori xavfsizlik talab qilinsa qo'shimcha qatlam bo'lardi.

---

## 4. Arxitektura zaifliklari (hozircha zaiflik emas, lekin xavfli joylar)

Bu bo'lim — kodda **ongli ravishda** qabul qilingan, lekin auditda alohida nomlanishi shart bo'lgan qarorlar:

1. **AI/FaceID xulq-atvor tahlili to'liq clientda** (AUDIT-03). Markazlashgan ML klasteri iqtisodiy jihatdan asossiz (~$500k, hujjatda aytilgan) — lekin bu shuni anglatadi: real-vaqtli avtomatik nazoratning yakuniy ishonch darajasi operator hisobi va client dasturi yaxlitligiga bog'liq, mustaqil kriptografik kafolat yo'q.
2. **Qurilma imzosi yo'q** (`authentication.py` docstring'i ochiq izohlaydi: "imzo faqat qo'shimcha murakkablik edi"). Bu qaror to'g'ri — imzo "kim" savolini yechmaydi — lekin buning natijasi: **payload yaxlitligi** (severity, score, machine_uuid) faqat TLS transport darajasida himoyalangan, legitim-lekin-o'zgartirilgan client uni istagancha to'ldiradi.
3. **Kiosk/tezkor-tugma bloklash/threat-scanner — "best-effort", mutlaq chegara emas.** Kod bu haqda o'zi ochiq: userland darajasida o'ldirib bo'lmaydigan tahdid IMTIHONNI TO'SADI, lekin kernel darajasida majburlanmaydi. Fizik kirish huquqiga ega, texnik bilimli talabgor/operator uchun bu — mutlaq to'siq emas, faqat balandlik.
4. **RTSP kredensiali muddatsiz** (AUDIT-08) — himoya kodda emas, operatsion amaliyotda.
5. **Machine UUID — inventarizatsiya intizomi, kredensial emas** (AUDIT-01 bilan bog'liq). Bu atamaning o'zi to'g'ri tanlangan, lekin amaliyotda intizom bo'shashishi mumkin bo'lgan yagona nuqtaga (handshake) qurilgan.

---

## 5. Xavfsizroq arxitektura bo'yicha tavsiya

**Qisqa muddatli (kod o'zgarishi kam, ta'siri katta):**
- AUDIT-01: mashina tekshiruvini `proctoring/start/`da qayta majburlash.
- AUDIT-02: `object_key` prefiks tekshiruvi.
- AUDIT-05: CSP header qo'shish (bitta qator nginx konfiguratsiyasida).
- AUDIT-07: `JWT_SIGNING_KEY`ni `production.py`dagi majburiy-sir ro'yxatiga qo'shish.
- AUDIT-06: `exam_site.py`ga host-validatsiya + `allow_redirects=False`.

**O'rta muddatli:**
- AUDIT-03: `FACE_RANDOM_AUDIT_RATE`ni amalga oshirish — tasodifiy namunada server-tomon offline audit.
- AUDIT-04: token saqlashni `httpOnly` cookie'ga ko'chirishni baholash (CSRF strategiyasi bilan birga).
- AUDIT-09: kod-imzo sertifikati sotib olish va build jarayoniga integratsiya qilish.

**Uzoq muddatli / infratuzilma:**
- AUDIT-08: kameralar uchun alohida, faqat-o'qish, avtomatik almashtiriladigan (masalan har 90 kunda) hisob — deploy runbook talabini kodda (masalan ishga tushishda ogohlantirish) mustahkamlash.
- AUDIT-11: yuqori xavfsizlik talab qilinadigan joylashtirishlar uchun sertifikat pinning ko'rib chiqish.

**Umumiy tamoyil (saqlanishi kerak):** "client ishonchsiz muhit" prinsipi to'g'ri va izchil qo'llanilgan — uni buzmasdan, faqat **amalga oshirishdagi bo'shliqlarni** (AUDIT-01, AUDIT-02) yopish kerak, arxitekturani qayta qurish shart emas.

---

## 6. Tuzatish rejasi

### P0 — Darhol (bu auditda yo'q)
Tashqi, autentifikatsiyalanmagan hujumchi tomonidan bevosita ekspluatatsiya qilinadigan CRITICAL topilma yo'q. P0 talab qiladigan narsa aniqlanmadi.

### P1 — Qisqa muddat (keyingi sprint)
- **AUDIT-01** — Machine UUID qayta tekshiruvi `proctoring/start/`da.
- **AUDIT-02** — Skrinshot `object_key` egalik tekshiruvi.
- **AUDIT-05** — CSP header (bitta nginx qator, deploy paytida sinash bilan).

### P2 — Rejalashtirib (keyingi 1-2 chorak)
- **AUDIT-03** — FaceID tasodifiy server-audit namunasi.
- **AUDIT-04** — Token saqlash strategiyasini qayta baholash (`httpOnly` cookie migratsiyasi imkoniyati).
- **AUDIT-06** — SSRF himoyasi `exam_site.py`da.
- **AUDIT-07** — `JWT_SIGNING_KEY` mustaqilligini majburlash.
- **AUDIT-09** — Kod-imzo sertifikati va build integratsiyasi.

### P3 — Hardening (imkoniyat bo'lganda)
- **AUDIT-08** — Kamera hisobi rotatsiyasi runbook'ini kuchaytirish (deploy hujjatida).
- **AUDIT-10** — Lokal xizmatga yangi endpoint qo'shilganda Origin qoidasini qayta ko'rib chiqish (hozircha o'zgartirish shart emas).
- **AUDIT-11** — TLS sertifikat pinning (yuqori xavfsizlik talab qilinadigan joylashtirishlar uchun).

---

## Ilova: Ijobiy topilmalar (auditda alohida ta'kidlanishi lozim)

Xolislik uchun — bu audit davomida kod bazasida quyidagi amaliyotlar **to'g'ri va izchil** qo'llanilgani kuzatildi:

- Barcha parol/token solishtirishlarida `hmac.compare_digest`/Django `check_password` (constant-time).
- Challenge/pending-session iste'moli atomik (Redis GET+DEL bitta MULTI'da) — race condition yo'q.
- Fayl tizimi storage'ida path traversal + symlink himoyasi (`resolve()`dan keyin tekshiruv).
- `select_for_update(skip_locked=True)` — bron tizimida parallel so'rovlar uchun to'g'ri qulflash.
- Mass-assignment va privilege-escalation'ga qarshi serializer validatorlari (`UserWriteSerializer.validate`) — rol/viloyat bo'yicha ruxsat oshirishning oldini oladi.
- IP-spoofing'ga qarshi `TRUSTED_PROXY_COUNT` mexanizmi va unga mos testlar.
- Production sozlamalarida majburiy-sir tekshiruvi ishga tushishda (`ImproperlyConfigured`).
- Xato konvertida stack trace clientga hech qachon chiqmaydi (faqat log'ga).
- RTSP/kamera parollari admin panelga hech qachon qaytarilmaydi, Django admin formalaridan `exclude` qilingan.
- Frontend: `dangerouslySetInnerHTML`/`eval` umuman ishlatilmagan, sourcemap production build'da o'chirilgan, tashqi CDN skriptlari yo'q.
