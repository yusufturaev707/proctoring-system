"""
Imtihon sozlamasi va ish o'rni holatining MOSLIGINI tekshirish.

Sof funksiya: UI ni ham, tarmoqni ham bilmaydi. Kirish - siyosat
(serverdan kelgan `config.proctoring`) va aniqlangan kamera
taqsimoti; chiqish - muammolar ro'yxati.

IKKI DARAJA VA ULAR ARALASHTIRILMAYDI:

    TO'SIQ (blocking)   - siyosat ochiq TALAB qilgan narsa yo'q.
                          Davom etib bo'lmaydi. Bu qaror
                          administratorniki: u `primary_required`
                          ni qo'ygan va uni operator chetlab
                          o'tolmasligi kerak.
    OGOHLANTIRISH       - holat ideal emas, lekin siyosat uni
                          talab qilmagan. Operator ko'radi va
                          o'zi qaror qiladi.

Farq muhim: hamma narsani to'siqqa aylantirish sozlanmagan tizimda
butun imtihonni bloklab qo'yardi; hammasini ogohlantirishga
aylantirish esa administrator qo'ygan talabni ma'nosiz qilardi.

BU TEKSHIRUV YAGONA HIMOYA EMAS. U operatorga NOSOZLIKNI ERTA
ko'rsatish uchun - talabgor kelgunga qadar. Haqiqiy majburlash
serverda: sessiya ochilishida va `proctoring/start/` da (M2). Client
tomondagi tekshiruvni chetlab o'tish mumkin, serverdagini yo'q.
"""

from __future__ import annotations

from dataclasses import dataclass

from proctoring.camera.roles import CameraLayout


@dataclass
class PolicyIssue:
    """Bitta muammo: nima, nega va qanchalik jiddiy."""

    blocking: bool
    title: str
    detail: str = ""

    @property
    def kind(self) -> str:
        return "error" if self.blocking else "warning"


def check_readiness(
    *,
    config: dict,
    layout: CameraLayout,
    face_ready: bool = True,
    config_loaded: bool = True,
    check_result: dict | None = None,
    threats=None,
    threats_block: bool = True,
) -> list[PolicyIssue]:
    """
    Imtihonni boshlashga tayyormi.

    `config` - serverdan kelgan to'liq client konfiguratsiyasi
    (`exam/config/` javobidagi `config`).
    `config_loaded=False` - sozlamani olib bo'lmadi (tarmoq xatosi).
    `check_result` - `camera/check/` javobi (server baholagan).
    `threats` - ishga tushishdagi tozalash hisoboti
    (`services.threat_scanner.ThreatReport`) yoki `None`.

    IKKI MANBA, ANIQ USTUVORLIK. Server tekshiruvi mavjud bo'lsa,
    kamera bo'yicha xulosa AYNAN UNDAN olinadi va mahalliy evristika
    ishlatilmaydi. Sabab: server haqiqiy o'lchovlarni (FPS,
    rezolyutsiya, yorug'lik) ko'rgan, mahalliy tekshiruv esa faqat
    "kamera ro'yxatda bormi" degan savolga javob beradi. Ikkalasini
    birga ko'rsatish bir nosozlik uchun ikkita xabar berardi.

    Server tekshiruvi YO'Q bo'lsa - mahalliy evristika ishlaydi va
    qo'shimcha ogohlantirish chiqadi: `proctoring/start/` uni
    baribir talab qilishi mumkin va bu haqda operator IMTIHON
    BOSHLANISHIDAN oldin bilishi kerak.
    """
    issues: list[PolicyIssue] = []

    # TAHDIDLAR BIRINCHI va ular `config_loaded` dan OLDIN tekshiriladi.
    #
    # Sabab: masofaviy boshqaruv dasturi imtihon profili olinganmi
    # yoki yo'qmi degan savoldan mustaqil ravishda to'sadi. Uni
    # sozlama olinmagan holatda o'tkazib yuborish tarmoqni uzib
    # qo'yish orqali butun tekshiruvni chetlab o'tish yo'lini
    # ochardi.
    issues.extend(_check_threats(threats, threats_block))

    if not config_loaded:
        # OGOHLANTIRISH, to'siq EMAS.
        #
        # Sozlamani olib bo'lmagani vaqtinchalik tarmoq nosozligi
        # bo'lishi mumkin. Muhim qismlarni server baribir o'zi
        # majburlaydi (davriy FaceID chegarasi client yuborgan ballga
        # `verify_periodic_face` da qo'llanadi va u imtihon
        # profilidan olinadi), ya'ni oqim ishlaydi - faqat
        # client tomondagi qiymatlar (skrinshot oralig'i, tezkor
        # tugmalar) global profilniki bo'lib qoladi.
        #
        # Butun imtihonni o'tkinchi xato tufayli to'xtatish bundan
        # battar bo'lardi.
        issues.append(
            PolicyIssue(
                blocking=False,
                title="Imtihon sozlamasi olinmadi",
                detail=(
                    "Umumiy sozlama bilan davom etiladi. Tezkor tugmalar va "
                    "skrinshot oralig'i bu imtihonnikiga mos kelmasligi mumkin."
                ),
            )
        )
        return issues

    policy = (config or {}).get("proctoring") or {}
    camera = policy.get("camera") or {}

    if check_result:
        issues.extend(_from_server_check(check_result))
    else:
        issues.extend(_check_cameras(policy, camera, layout))
        # Server tekshiruvni MAJBURLASA (`check_required`) - TO'SIQ.
        # Ilgari bu doim ogohlantirish edi: operator uni tasdiqlab o'tar,
        # server esa `proctoring/start/` da `camera_check_required` bilan
        # rad etardi - talabgor JSHSHIR, FaceID va shaxs tasdig'idan o'tib
        # bo'lgach. Shart serverdagi bilan bir xil: kamera siyosatda
        # talab qilinmasa tekshiruvsiz boshlash qonuniy. Bayroq kelmasa
        # (eski server) - avvalgidek ogohlantirish.
        needs_camera = bool(
            camera.get("primary_required", True) or camera.get("secondary_required", False)
        )
        required = bool(camera.get("check_required")) and needs_camera
        issues.append(
            PolicyIssue(
                blocking=required,
                title="Kamera tekshiruvi o'tkazilmagan",
                detail=(
                    "«Tekshirish» tugmasini bosing — tekshiruvsiz imtihon "
                    "boshlanmaydi."
                    if required
                    else "«Tekshirish» tugmasini bosing. Tekshiruvsiz imtihon "
                    "boshlanishida rad etilishi mumkin."
                ),
            )
        )

    issues.extend(_check_modules(policy, layout, face_ready))
    return issues


def _from_server_check(result: dict) -> list:
    """
    Server tekshiruvidan MUAMMOLARNI ajratib oladi.

    Faqat `failed` va `warning` qatorlar olinadi: muvaffaqiyatli
    tekshiruvlar panelda allaqachon ko'rinib turibdi va ularni
    modalga takrorlash uni o'qib bo'lmas holga keltirardi.

    Matn SERVERNIKI - client uni qayta yozmaydi. Chegara ham, sabab
    ham bitta joyda yashashi kerak.
    """
    issues: list[PolicyIssue] = []
    for check in result.get("checks") or []:
        status = check.get("status")
        if status not in ("failed", "warning"):
            continue
        issues.append(
            PolicyIssue(
                blocking=bool(check.get("blocking")) and status == "failed",
                title=check.get("title") or check.get("code", ""),
                detail=check.get("detail") or "",
            )
        )
    return issues


# --------------------------------------------------------------------------
def _check_cameras(policy: dict, camera: dict, layout: CameraLayout) -> list:
    issues: list[PolicyIssue] = []

    primary = layout.get("primary")
    secondary = layout.get("secondary")
    required_primary = bool(camera.get("primary_required", True))
    required_secondary = bool(camera.get("secondary_required", False))

    if not _usable(primary):
        issues.append(
            PolicyIssue(
                blocking=required_primary,
                title="Yuz tekshiruvi kamerasi ishlamayapti",
                detail=(
                    _why(primary)
                    or "Kamera topilmadi. Veb-kamerani ulang yoki administratordan "
                    "IP kamera biriktirishni so'rang."
                ),
            )
        )

    if not _usable(secondary):
        # Ikkilamchi kamera YO'QLIGI - odatiy hol. U faqat siyosat
        # talab qilganda to'siq bo'ladi.
        if required_secondary:
            issues.append(
                PolicyIssue(
                    blocking=True,
                    title="Obyekt aniqlash kamerasi ishlamayapti",
                    detail=(
                        _why(secondary)
                        or "Bu imtihon uchun ikkinchi kamera majburiy."
                    ),
                )
            )
        elif int(camera.get("count") or 1) > 1:
            issues.append(
                PolicyIssue(
                    blocking=False,
                    title="Ikkinchi kamera yo'q",
                    detail=(
                        "Sozlamada ikkita kamera ko'zda tutilgan. Obyekt aniqlash "
                        "va stol nazorati ishlamaydi."
                    ),
                )
            )

    # Virtual kamera - oldindan yozilgan videoni jonli oqim sifatida
    # ko'rsatishning eng oson yo'li.
    # `in_use` - faqat imtihonda ISHLATILADIGAN kameralar: zaxiradagi
    # qurilma hech narsa yozmaydi va hech narsani tasdiqlamaydi.
    if not camera.get("allow_virtual", False):
        for item in layout.in_use:
            if item.is_virtual:
                issues.append(
                    PolicyIssue(
                        blocking=True,
                        title="Virtual kamera aniqlandi",
                        detail=(
                            "«{}» virtual qurilma va bu imtihonda taqiqlangan. "
                            "Uni o'chirib, haqiqiy kamerani ulang.".format(item.label)
                        ),
                    )
                )

    # Rezolyutsiya - FAQAT o'lchangan bo'lsa. Kamera hali
    # ochilmagan bo'lsa (`width == 0`), tekshirib bo'lmaydi va bu
    # "muvaffaqiyatsiz" degani EMAS.
    min_width = int(camera.get("min_width") or 0)
    min_height = int(camera.get("min_height") or 0)
    for item in layout.in_use:
        if not item.width or not item.height:
            continue
        if item.width < min_width or item.height < min_height:
            issues.append(
                PolicyIssue(
                    blocking=False,
                    title="Kamera sifati past: {}".format(item.label),
                    detail="{} — talab qilinadigan eng kichik o'lcham {}x{}.".format(
                        item.resolution, min_width, min_height
                    ),
                )
            )
    return issues


def _check_threats(report, blocks: bool) -> list:
    """
    Ishga tushishdagi tozalash hisobotidan muammolarni ajratadi.

    UCH XIL YAKUN, UCH XIL XULOSA:

      yo'q qilingan  -> hech narsa. Dastur yopilgan, imtihon toza
                        mashinada boshlanadi. Yozuv hodisa oqimida
                        qoladi, operatorni esa bekorga to'xtatmaymiz.
      qolgan (to'siq)-> TO'SIQ. Administrator huquqi yetmagan yoki
                        xizmat qayta ko'tarilgan - ya'ni masofaviy
                        boshqaruv HOZIR ham ishlayapti.
      ogohlantirish  -> yopib bo'lmagan ikkinchi darajali vosita
                        (Hyper-V yoqilgan, virtual kamera).

    `blocks=False` (imtihon profilida `rdp.block_exam=false`, zaxira -
    `.env` `THREAT_BLOCK_EXAM`) barcha to'siqlarni
    ogohlantirishga tushiradi: hodisa baribir yoziladi va proktor
    panelda ko'radi, qarorni esa operator qabul qiladi.
    """
    if report is None:
        return []

    issues: list[PolicyIssue] = []
    for finding in report.survivors:
        issues.append(
            PolicyIssue(
                blocking=blocks,
                title="Yopib bo'lmadi: {}".format(finding.label),
                # Sabab ham, yo'l ham bitta matnda: operator nima
                # bo'lganini va nima qilishini birdan ko'rishi kerak.
                detail="{} ({}). {}".format(
                    finding.evidence or finding.describe(),
                    finding.reason or "sabab noma'lum",
                    finding.hint,
                ).strip(),
            )
        )

    for finding in report.warnings:
        issues.append(
            PolicyIssue(
                blocking=False,
                title="Aniqlandi: {}".format(finding.label),
                detail="{} {}".format(finding.evidence, finding.hint).strip(),
            )
        )
    return issues


def _check_modules(policy: dict, layout: CameraLayout, face_ready: bool) -> list:
    issues: list[PolicyIssue] = []
    modules = policy.get("modules") or {}

    if modules.get("identity") and not face_ready:
        issues.append(
            PolicyIssue(
                blocking=False,
                title="Yuz tekshiruvi modeli yuklanmagan",
                detail=(
                    "Model hali yuklanmoqda yoki yuklanmadi. FaceID sahifasi "
                    "ochilguncha kutib turing."
                ),
            )
        )

    if modules.get("objects") and layout.get("secondary") is None:
        # Obyekt aniqlash BIRLAMCHI kamerada ham ishlaydi, lekin u
        # yuzga qaragan - stol va qo'llar kadrga tushmaydi. Bu
        # to'siq emas, lekin natijaning cheklanganini aytish kerak.
        issues.append(
            PolicyIssue(
                blocking=False,
                title="Obyekt aniqlash cheklangan rejimda",
                detail=(
                    "Ikkinchi kamera yo'q — obyektlar faqat yuz kamerasida "
                    "qidiriladi, stol va qo'llar kadrga tushmaydi."
                ),
            )
        )
    return issues


def _usable(camera) -> bool:
    return camera is not None and camera.available


def _why(camera) -> str:
    """Kamera nega ishlamayotgani (rol aniqlangan bo'lsa)."""
    if camera is None:
        return ""
    return camera.reason or ""


def blocking(issues: list) -> list:
    return [item for item in issues if item.blocking]


def warnings(issues: list) -> list:
    return [item for item in issues if not item.blocking]
