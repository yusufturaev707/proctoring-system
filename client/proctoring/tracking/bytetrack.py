"""
ByteTrack — obyektlarni kadrlar orasida kuzatish.

NIMA UCHUN KUZATUV UMUMAN KERAK. Detektor har kadrda mustaqil
ishlaydi va u "bu o'sha telefonmi yoki yangisimi?" degan savolga
javob bermaydi. Kuzatuvsiz 100 kadrda ko'ringan telefon 100 ta
alohida aniqlanish bo'lardi va texnik topshiriqning 9-holati
("100 kadr -> 1 hodisa") bajarilmasdi. `track_id` esa aynan shu
bog'lanishni beradi: hodisa OCHILADI, obyekt kadrda turgan sayin
ochiq qoladi va yo'qolgach YOPILADI.

NIMA UCHUN O'ZIMIZ YOZILDI. `supervision`, `boxmot`, rasmiy
`ByteTrack` — hammasi `scipy`, `lap` yoki `torch` ni tortadi.
PyInstaller bundle'iga bu yuzlab megabayt qo'shadi, holbuki
kerakli algoritm ~200 qator numpy. Loyihada allaqachon shu qaror
qabul qilingan: `face_engine.py` da torch AYNAN shu sababdan
olib tashlangan.

BYTETRACK'NING ASOSIY G'OYASI - ikki bosqichli moslashtirish:

  1-bosqich: YUQORI ishonchli aniqlanishlar mavjud izlar bilan
             moslashtiriladi;
  2-bosqich: moslanmagan izlar PAST ishonchli aniqlanishlar bilan
             moslashtiriladi.

Ikkinchisi butun algoritmning ma'nosi: obyekt qisman berkilganda
(qo'l telefonni yarim yopganda) ishonch tushadi va oddiy tracker
izni yo'qotadi — keyin uni YANGI obyekt sifatida qayta ochadi.
Proktorlikda bu bitta telefonni o'nta hodisaga aylantirardi.

SODDALASHTIRISH: Kalman filtri YO'Q. Rasmiy ByteTrack harakatni
Kalman bilan bashorat qiladi; bu yerda esa obyektlar deyarli
qimirlamaydi (stol ustidagi telefon, o'tirgan odam) va oxirgi
ramka o'rnining o'zi yetarli bashorat. Kalman `scipy` ni tortardi
va yutuq bu sahnada o'lchanmas darajada kichik.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np

log = logging.getLogger(__name__)


@dataclass
class Track:
    """Bitta kuzatilayotgan obyekt."""

    track_id: int
    cls: str
    bbox: np.ndarray                  # [x1, y1, x2, y2]
    score: float
    #: COCO klass KODI (`-1` - noma'lum). `cls` - serverdagi NOM
    #: ("Odam") va u sozlamada o'zgarishi mumkin; qaror esa kodga
    #: tayanadi (`behavior_analyzer._PERSON_CODE`).
    code: int = -1
    #: Iz birinchi marta TASDIQLANGAN kadr (`_min_hits` dan keyin).
    first_frame: int = 0
    last_frame: int = 0
    #: Ketma-ket nechta kadrda ko'rindi (tasdiqlashdan oldin).
    hits: int = 0
    #: Ketma-ket nechta kadrda YO'Q (o'chirishdan oldin).
    misses: int = 0
    confirmed: bool = False
    #: Ishonchlar tarixi — hodisa `confidence` si shundan olinadi.
    scores: list = field(default_factory=list)

    @property
    def age_frames(self) -> int:
        return self.last_frame - self.first_frame + 1

    @property
    def mean_score(self) -> float:
        return float(np.mean(self.scores)) if self.scores else 0.0

    @property
    def max_score(self) -> float:
        return float(max(self.scores)) if self.scores else 0.0

    def as_dict(self) -> dict:
        return {
            "track_id": self.track_id,
            "cls": self.cls,
            "bbox": [int(value) for value in self.bbox],
            "score": round(float(self.score), 3),
            "mean_score": round(self.mean_score, 3),
            "age_frames": self.age_frames,
        }


def iou_matrix(boxes_a: np.ndarray, boxes_b: np.ndarray) -> np.ndarray:
    """
    Har bir juftlik uchun IoU (kesishma / birlashma).

    Vektorlashtirilgan: 20 iz x 20 aniqlanish uchun ham bitta
    numpy amali. Ichma-ich sikl sekin mashinada har kadrda
    seziladigan bo'lardi.
    """
    if len(boxes_a) == 0 or len(boxes_b) == 0:
        return np.zeros((len(boxes_a), len(boxes_b)), dtype=np.float32)

    a = np.asarray(boxes_a, dtype=np.float32)[:, None, :]   # (N, 1, 4)
    b = np.asarray(boxes_b, dtype=np.float32)[None, :, :]   # (1, M, 4)

    left = np.maximum(a[..., 0], b[..., 0])
    top = np.maximum(a[..., 1], b[..., 1])
    right = np.minimum(a[..., 2], b[..., 2])
    bottom = np.minimum(a[..., 3], b[..., 3])

    inter = np.clip(right - left, 0, None) * np.clip(bottom - top, 0, None)
    area_a = np.clip(a[..., 2] - a[..., 0], 0, None) * np.clip(a[..., 3] - a[..., 1], 0, None)
    area_b = np.clip(b[..., 2] - b[..., 0], 0, None) * np.clip(b[..., 3] - b[..., 1], 0, None)

    union = area_a + area_b - inter
    # Nol maydonli ramka (buzuq aniqlanish) nolga bo'lishni
    # keltirib chiqarmasligi kerak.
    return np.where(union > 0, inter / np.maximum(union, 1e-6), 0.0).astype(np.float32)


def greedy_match(cost: np.ndarray, threshold: float) -> tuple:
    """
    Ochko'z moslashtirish: eng katta IoU dan boshlab juftlaydi.

    MACARON (Hungarian) ALGORITMI EMAS va bu ongli: u `scipy` ni
    talab qiladi (`linear_sum_assignment`), yutuq esa bu sahnada
    yo'q. Optimal moslashtirish ko'p va ZICH joylashgan bir xil
    obyektlar bo'lganda ahamiyatga ega; imtihon stolida esa 2-5 ta
    obyekt bor va ular bir-birining ustida turmaydi.

    Qaytadi: `(juftliklar, moslanmagan_qatorlar, moslanmagan_ustunlar)`.
    """
    rows, cols = cost.shape
    matches: list = []
    used_rows: set = set()
    used_cols: set = set()

    if rows and cols:
        # Barcha juftliklarni IoU bo'yicha kamayish tartibida.
        order = np.dstack(np.unravel_index(np.argsort(-cost, axis=None), cost.shape))[0]
        for row, col in order:
            if cost[row, col] < threshold:
                # Qolganlari yanada kichik — davom etishning ma'nosi yo'q.
                break
            if row in used_rows or col in used_cols:
                continue
            used_rows.add(int(row))
            used_cols.add(int(col))
            matches.append((int(row), int(col)))

    unmatched_rows = [index for index in range(rows) if index not in used_rows]
    unmatched_cols = [index for index in range(cols) if index not in used_cols]
    return matches, unmatched_rows, unmatched_cols


class ByteTrack:
    """
    Ikki bosqichli kuzatuvchi.

    Har kadrda `update(detections)` chaqiriladi va u TASDIQLANGAN
    izlar ro'yxatini qaytaradi.

    `detections` — `{"cls": str, "bbox": [x1,y1,x2,y2], "score": float}`
    lug'atlari ro'yxati.
    """

    def __init__(
        self,
        *,
        high_threshold: float = 0.5,
        low_threshold: float = 0.2,
        match_threshold: float = 0.3,
        max_misses: int = 15,
        min_hits: int = 3,
    ) -> None:
        """
        `min_hits` — iz TASDIQLANGUNCHA kerak bo'ladigan kadr soni.

        Bitta kadrdagi aniqlanish tasodifiy bo'lishi mumkin (shovqin,
        blur, yorug'lik chaqnashi). Uni darhol iz qilib ochish hodisa
        oqimini soxta obyektlar bilan to'ldirardi — bu proktorlikdagi
        eng qimmat xato turi.

        `max_misses` — iz o'chirilgunga qadar necha kadr yo'qolib
        turishi mumkin. Obyekt qo'l bilan vaqtincha yopilganda iz
        saqlanib qolishi kerak, aks holda u yangi `track_id` bilan
        qayta ochilardi.
        """
        self.high_threshold = float(high_threshold)
        self.low_threshold = float(low_threshold)
        self.match_threshold = float(match_threshold)
        self.max_misses = int(max_misses)
        self.min_hits = int(min_hits)

        self._tracks: list[Track] = []
        self._next_id = 1
        self._frame = 0

    # ------------------------------------------------------------------
    @property
    def tracks(self) -> list:
        """Tasdiqlangan va hozir ko'rinayotgan izlar."""
        return [item for item in self._tracks if item.confirmed and item.misses == 0]

    @property
    def all_tracks(self) -> list:
        return list(self._tracks)

    def reset(self) -> None:
        """Yangi sessiya — izlar va ID hisoblagichi noldan."""
        self._tracks = []
        self._next_id = 1
        self._frame = 0

    # ------------------------------------------------------------------
    def update(self, detections: list) -> list:
        """Kadrni qayta ishlaydi va tasdiqlangan izlarni qaytaradi."""
        self._frame += 1

        high = [item for item in detections if item.get("score", 0) >= self.high_threshold]
        low = [
            item
            for item in detections
            if self.low_threshold <= item.get("score", 0) < self.high_threshold
        ]

        # --- 1-bosqich: yuqori ishonchli aniqlanishlar ---
        remaining = self._associate(self._tracks, high)

        # --- 2-bosqich: qolgan izlar + PAST ishonchli aniqlanishlar ---
        #
        # ByteTrack'ning butun ma'nosi shu yerda: qisman berkilgan
        # obyektning ishonchi tushadi va oddiy tracker uni yo'qotadi.
        # Bu bosqich izni saqlab qoladi.
        self._associate(remaining, low, second_stage=True)

        self._age_and_prune()
        return self.tracks

    # ------------------------------------------------------------------
    def _associate(self, tracks: list, detections: list, *, second_stage: bool = False) -> list:
        """
        Izlarni aniqlanishlar bilan juftlaydi.

        Qaytadi: MOSLANMAGAN izlar (keyingi bosqich uchun).

        Moslashtirish HAR BIR KLASS ICHIDA alohida: telefonning izi
        kitobning aniqlanishiga ulanib qolmasligi kerak, hatto ular
        ramka bo'yicha ustma-ust tushsa ham.
        """
        if not detections:
            return list(tracks)

        unmatched_tracks: list = []
        classes = {item["cls"] for item in detections} | {item.cls for item in tracks}

        for cls in classes:
            class_tracks = [item for item in tracks if item.cls == cls]
            class_detections = [item for item in detections if item["cls"] == cls]

            if not class_tracks:
                if not second_stage:
                    # Yangi iz FAQAT birinchi bosqichda ochiladi:
                    # past ishonchli aniqlanish yangi obyekt uchun
                    # asos bo'la olmaydi (aynan shu shovqin manbai).
                    for detection in class_detections:
                        self._create(detection)
                continue

            if not class_detections:
                unmatched_tracks.extend(class_tracks)
                continue

            cost = iou_matrix(
                np.array([item.bbox for item in class_tracks], dtype=np.float32),
                np.array([item["bbox"] for item in class_detections], dtype=np.float32),
            )
            matches, lost, extra = greedy_match(cost, self.match_threshold)

            for track_index, detection_index in matches:
                self._hit(class_tracks[track_index], class_detections[detection_index])

            unmatched_tracks.extend(class_tracks[index] for index in lost)

            if not second_stage:
                for index in extra:
                    self._create(class_detections[index])

        return unmatched_tracks

    def _create(self, detection: dict) -> Track:
        track = Track(
            track_id=self._next_id,
            cls=detection["cls"],
            bbox=np.asarray(detection["bbox"], dtype=np.float32),
            score=float(detection.get("score", 0.0)),
            code=int(detection.get("code", -1)),
            first_frame=self._frame,
            last_frame=self._frame,
            hits=1,
            scores=[float(detection.get("score", 0.0))],
            confirmed=self.min_hits <= 1,
        )
        self._next_id += 1
        self._tracks.append(track)
        return track

    def _hit(self, track: Track, detection: dict) -> None:
        track.bbox = np.asarray(detection["bbox"], dtype=np.float32)
        track.score = float(detection.get("score", 0.0))
        track.scores.append(track.score)
        track.last_frame = self._frame
        track.hits += 1
        track.misses = 0
        if not track.confirmed and track.hits >= self.min_hits:
            track.confirmed = True
            # Tasdiqlangan kadr - hodisaning BOSHLANISH vaqti.
            # Birinchi ko'rinish emas: u tasodifiy bo'lishi mumkin
            # edi va hodisa vaqtini oldinga surib yuborardi.
            track.first_frame = self._frame - track.hits + 1

    def _age_and_prune(self) -> None:
        """Ko'rinmagan izlarga yosh qo'shadi va eskilarini o'chiradi."""
        alive: list[Track] = []
        for track in self._tracks:
            if track.last_frame != self._frame:
                track.misses += 1
            if track.misses > self.max_misses:
                log.debug(
                    "Iz yopildi: #%s %s (%s kadr)",
                    track.track_id, track.cls, track.age_frames,
                )
                continue
            # Tasdiqlanmagan iz BIRINCHI yo'qolishda o'chadi:
            # u hali obyekt ekani isbotlanmagan va uni 15 kadr
            # ushlab turish shovqinni uzaytirardi.
            if not track.confirmed and track.misses > 0:
                continue
            alive.append(track)
        self._tracks = alive
