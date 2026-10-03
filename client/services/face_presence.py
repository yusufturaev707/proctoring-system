"""
Yuz yo'qligi / bir nechta yuz / juda uzoq yuz — KADR emas, EPIZOD bo'yicha hodisa.

AI kuzatuv o'chiq bo'lganda (`ProctoringSupervisor` ishlamaydi) imtihon
sahifasi FaceID ishchisining natijalarini oladi: aniqlash har N-kadrda,
ya'ni sekundiga ~10 natija. Ilgari HAR "yuz yo'q" natijasi hodisa
bo'lib ketardi - talabgor bir zum egilsa panelga sekundiga o'nlab
"Yuz topilmadi" ogohlantirishi tushardi: proktor uchun shovqin, server
uchun ortiqcha yuk, xavf balli uchun noto'g'ri og'irlik.

Qoida AI qatlamidagi bilan BIR XIL (`behavior_analyzer._observe_two_stage`)
va chegaralar o'sha siyosatdan (`config.proctoring.temporal`):

  * yuz `no_face_warn_s` uzluksiz yo'q -> ogohlantirish (jiddiylik 2);
  * `no_face_suspicious_s` gacha cho'zilsa -> shubha (3), shu epizodda oxirgisi;
  * bir nechta yuz `MULTIPLE_MIN_S` davom etsa -> bitta hodisa (3);
  * yuz juda uzoq (`far`) `face.far_warn_s` -> `face_too_far` (1), u
    `face.far_unverified_s` gacha cho'zilsa -> yana bitta (2) (ikkalasi
    `Setting` profilida, panel "FaceID"): bu paytda
    davriy FaceID solishtira olmaydi ("solishtirib bo'lmadi") va
    talabgor kameradan uzoq o'tirib shaxs tekshiruvini jimgina
    chetlab o'tishi mumkin edi;
  * epizod yuz `RELEASE_S` davomida qaytgandagina yopiladi - bitta
    tasodifiy kadr (miltillash) uni ikkiga bo'lmasligi kerak.

YOPILISH HODISASI. Hodisa epizod boshida chiqadi, ya'ni 30 daqiqalik
yo'qlik panelda "5 s" bo'lib qolardi. Hodisa bergan epizod yopilganda
yana bitta yozuv ketadi: o'sha tur, jiddiylik 0, `closed: true` va
`duration_ms` - AI qatlamining `_closed_event` i bilan bir xil shakl
(server uni ballga qo'shmaydi, `ingest._is_closing`). Epizodiga bitta
qator - DB'ni to'ldirmaydi.

Sof mantiq, Qt'siz: vaqt chaqiruvchidan keladi (`now`) va testlanadi.
"""

from __future__ import annotations

#: Ikkinchi yuz shuncha uzluksiz ko'rinsa - hodisa. Orqadan o'tib
#: ketgan xodim bir-ikki kadrda ko'rinadi va bu qoidaga tushmaydi.
MULTIPLE_MIN_S = 1.0
#: Holat shuncha vaqt yo'qolsagina epizod tugaydi.
RELEASE_S = 1.0
#: Konstruktor standartlari (testlar uchun). Amalda qiymat imtihon
#: profilidan keladi (`from_config`); model standartlari bilan bir xil.
#: Suyanib o'tirish tabiiy - qisqa "uzoq" holat hodisa emas.
FAR_WARN_S = 10.0
#: Shuncha vaqt davomida shaxsni solishtirib bo'lmadi - proktor bilishi kerak.
FAR_UNVERIFIED_S = 120.0


class FaceEpisodes:
    def __init__(self, *, warn_s: float = 2.0, suspicious_s: float = 5.0,
                 multiple_min_s: float = MULTIPLE_MIN_S, release_s: float = RELEASE_S,
                 far_warn_s: float = FAR_WARN_S, far_unverified_s: float = FAR_UNVERIFIED_S) -> None:
        self.warn_s = max(0.0, float(warn_s))
        self.suspicious_s = max(self.warn_s, float(suspicious_s))
        self.multiple_min_s = max(0.0, float(multiple_min_s))
        self.release_s = max(0.0, float(release_s))
        self.far_warn_s = max(0.0, float(far_warn_s))
        self.far_unverified_s = max(self.far_warn_s, float(far_unverified_s))
        # Holat -> bosqichlar: (chegara s, tur, jiddiylik, bosqich nomi).
        self._rules = {
            "none": (
                (self.warn_s, "face_not_found", 2, "warning"),
                (self.suspicious_s, "face_not_found", 3, "suspicious"),
            ),
            "multiple": ((self.multiple_min_s, "multiple_faces", 3, "confirmed"),),
            "far": (
                (self.far_warn_s, "face_too_far", 1, "warning"),
                (self.far_unverified_s, "face_too_far", 2, "unverified"),
            ),
        }
        self.reset()

    @classmethod
    def from_config(cls, config: dict | None) -> "FaceEpisodes":
        """
        Ikki manba, ataylab: "yuz yo'q" - AI qatlami bilan UMUMIY qoida
        (`ProctoringPolicy` -> `proctoring.temporal`), "yuz uzoqda" esa
        davriy FaceID'niki (`Setting.faceid_far_*` -> `face.*`,
        `runtime_settings` orqali - `.env` faqat zaxira).
        """
        from services import runtime_settings

        far_warn_s = runtime_settings.get(config, "face.far_warn_s")
        far_unverified_s = runtime_settings.get(config, "face.far_unverified_s")
        temporal = ((config or {}).get("proctoring") or {}).get("temporal") or {}
        try:
            warn_s = float(temporal.get("no_face_warn_s", 2))
            suspicious_s = float(temporal.get("no_face_suspicious_s", 5))
        except (TypeError, ValueError):
            warn_s, suspicious_s = 2.0, 5.0
        return cls(warn_s=warn_s, suspicious_s=suspicious_s,
                   far_warn_s=far_warn_s, far_unverified_s=far_unverified_s)

    def reset(self) -> None:
        self._episodes = {kind: _Episode() for kind in self._rules}

    def observe(self, state: str, now: float, *, faces: int = 0) -> list:
        """Natija -> yuboriladigan hodisalar `[(tur, jiddiylik, payload)]` (ko'pincha bo'sh)."""
        events = []
        for kind, episode in self._episodes.items():
            if state == kind:
                if episode.started is None:
                    episode.started = now
                episode.left_at = None
                episode.faces = max(episode.faces, int(faces or 0))
                events.extend(self._escalate(kind, episode, now))
            elif episode.started is not None:
                if episode.left_at is None:
                    episode.left_at = now
                if now - episode.left_at >= self.release_s:
                    events.extend(self._close(kind, episode, episode.left_at))
        return events

    def close_all(self, now: float) -> list:
        """Sessiya to'xtaganda ochiq epizodlarning yopilish hodisalari."""
        events = []
        for kind, episode in self._episodes.items():
            if episode.started is not None:
                events.extend(self._close(kind, episode, episode.left_at or now))
        return events

    def _escalate(self, kind: str, episode: "_Episode", now: float) -> list:
        stages = self._rules[kind]
        if episode.stage >= len(stages):
            return []
        threshold, event_type, severity, stage_name = stages[episode.stage]
        duration = now - episode.started
        if duration < threshold:
            return []
        episode.stage += 1
        episode.event_type = event_type
        payload = {"duration_ms": int(duration * 1000), "stage": stage_name}
        if kind == "multiple":
            payload["faces"] = max(2, episode.faces)
        return [(event_type, severity, payload)]

    @staticmethod
    def _close(kind: str, episode: "_Episode", ended_at: float) -> list:
        events = []
        if episode.stage and episode.event_type:
            payload = {
                "closed": True,
                "duration_ms": int(max(0.0, ended_at - episode.started) * 1000),
                "stage": "ended",
            }
            if kind == "multiple":
                payload["faces"] = max(2, episode.faces)
            events.append((episode.event_type, 0, payload))
        episode.__init__()
        return events


class _Episode:
    __slots__ = ("started", "left_at", "stage", "event_type", "faces")

    def __init__(self) -> None:
        #: Holat boshlangan payt; `None` - epizod yo'q.
        self.started = None
        #: Holat "yo'qolgan" payt (yopilish kechikishi uchun).
        self.left_at = None
        #: Nechta bosqich hodisasi chiqdi.
        self.stage = 0
        self.event_type = ""
        self.faces = 0
