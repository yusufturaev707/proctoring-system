"""
Taqiqlangan obyektlarni aniqlash (YOLO).

MODEL FAYLI REPOZITORIYDA YO'Q va bu ataylab: u ~10-50 MB va
har bir muassasa o'z ro'yxati bilan o'qitilgan modelni
ishlatishi mumkin (`controls.ModelVersion` modeli aynan shuning
uchun). Fayl topilmasa modul JIMGINA o'chadi va qolgan kuzatuv
ishlayveradi - lekin sabab log'ga va hodisaga tushadi
(`proctoring_degraded`), ya'ni "obyekt aniqlanmadi" va "obyekt
aniqlash umuman ishlamadi" bayonnomada ajratiladi.

KLASS RO'YXATI SERVERDAN keladi (`config.detection.classes`) va
u `CocoObject.code` bo'yicha xaritalanadi. Model chiqishidagi
indeks COCO kodiga TENG deb qabul qilinadi - standart COCO
o'qitilgan modellar uchun bu shunday. Maxsus o'qitilgan model
uchun yonida `<model>.labels.txt` fayli bo'lishi kerak: har
qatorda bitta nom, tartib model chiqishidagi indeks bilan bir xil.

ISHONCH CHEGARASI ham serverdan (`config.detection.confidence`).
Uni koddan qadab qo'yish har bir muassasada qayta kompilyatsiya
talab qilardi.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from proctoring.detection.ops import Letterbox, nms, xywh_to_xyxy
from proctoring.inference.engine import ModelNotFound, OnnxEngine, build_engine

log = logging.getLogger(__name__)


@dataclass
class Detection:
    """Bitta aniqlanish."""

    cls: str
    code: int
    score: float
    bbox: np.ndarray                  # [x1, y1, x2, y2] asl kadr koordinatalarida

    def as_dict(self) -> dict:
        return {
            "cls": self.cls,
            "code": self.code,
            "score": round(float(self.score), 3),
            "bbox": [int(value) for value in self.bbox],
        }


class YoloDetector:
    """
    YOLOv8 obyekt detektori.

    `is_ready` — model yuklandimi. `False` bo'lsa `detect()` bo'sh
    ro'yxat qaytaradi va istisno TASHLAMAYDI: pipeline har kadrda
    uni chaqiradi va u yerda `try/except` yozish siklni
    shovqinga to'ldirardi.
    """

    def __init__(
        self,
        model_path,
        profile,
        *,
        classes: Optional[list] = None,
        confidence: float = 0.5,
        iou_threshold: float = 0.45,
    ) -> None:
        self._engine: OnnxEngine = build_engine(model_path, profile, name="yolo")
        self._path = Path(model_path)
        self._letterbox = Letterbox(size=profile.detect_size)
        self._confidence = float(confidence)
        self._iou = float(iou_threshold)
        self._names = self._load_labels()
        #: Faqat SHU kodlar hodisaga aylanadi (serverdan).
        self._allowed = self._build_allowed(classes)
        self._error = ""

    # ------------------------------------------------------------------
    @property
    def is_ready(self) -> bool:
        return self._engine.is_ready

    @property
    def error(self) -> str:
        """Modul o'chirilgan bo'lsa - sababi."""
        return self._error

    @property
    def uses_gpu(self) -> bool:
        return self._engine.uses_gpu

    @property
    def last_latency_ms(self) -> float:
        return self._engine.last_latency_ms

    def load(self) -> bool:
        """
        Modelni yuklaydi. `False` — yuklanmadi (sabab `error` da).

        BLOKLOVCHI: fon thread'ida chaqiriladi.
        """
        try:
            self._engine.load()
        except ModelNotFound as exc:
            self._error = str(exc)
            log.warning("Obyekt aniqlash o'chirildi: %s", exc)
            return False
        except Exception as exc:
            self._error = "Modelni yuklab bo'lmadi: {}".format(str(exc)[:200])
            log.exception("YOLO modelini yuklashda xato")
            return False
        return True

    def close(self) -> None:
        self._engine.close()

    # ------------------------------------------------------------------
    def detect(self, frame: np.ndarray) -> list:
        """Kadrdagi ruxsat etilmagan obyektlar."""
        if not self.is_ready or frame is None:
            return []

        try:
            tensor = self._letterbox.apply(frame)
            outputs = self._engine.run(tensor)
        except Exception:
            log.exception("YOLO inference xatosi")
            return []

        return self._decode(outputs[0])

    # ------------------------------------------------------------------
    def _decode(self, output: np.ndarray) -> list:
        """
        YOLOv8 chiqishini ochadi.

        SHAKL: `(1, 4 + nc, N)` — ya'ni kanal o'qi O'RTADA. Bu
        YOLOv5 dan (`(1, N, 5 + nc)`, obyekt ishonchi alohida)
        farq qiladi va ikkalasini bir kodda qo'llab-quvvatlash
        shoxlanishga olib kelardi. Bu yerda faqat v8: `ModelVersion`
        yozuvi modelning formatini belgilaydi va noto'g'ri format
        yuklanganda shakl tekshiruvi uni darhol ushlaydi.
        """
        array = np.asarray(output)
        if array.ndim == 3:
            array = array[0]
        if array.ndim != 2:
            log.error("YOLO chiqishining shakli kutilmagan: %s", array.shape)
            return []

        # `(4 + nc, N)` -> `(N, 4 + nc)`. Ba'zi eksportlar allaqachon
        # transponirlangan holda keladi, shuning uchun qaysi o'q
        # "kanal" ekanini O'LCHAM bo'yicha aniqlaymiz: aniqlanishlar
        # soni (8400) klasslar sonidan (~80) har doim katta.
        if array.shape[0] < array.shape[1]:
            array = array.T

        if array.shape[1] < 5:
            log.error("YOLO chiqishida klasslar yo'q: %s", array.shape)
            return []

        boxes = xywh_to_xyxy(array[:, :4])
        class_scores = array[:, 4:]
        class_ids = class_scores.argmax(axis=1)
        scores = class_scores[np.arange(len(class_ids)), class_ids]

        keep = scores >= self._confidence
        if not keep.any():
            return []

        boxes, scores, class_ids = boxes[keep], scores[keep], class_ids[keep]

        # Ruxsat etilgan klasslar bo'yicha filtr NMS dan OLDIN:
        # keraksiz klasslarni NMS ga kiritish uni sekinlashtiradi va
        # (klasslararo bostirish tufayli) kerakli obyektni yo'qotishi
        # ham mumkin.
        if self._allowed is not None:
            mask = np.isin(class_ids, list(self._allowed))
            if not mask.any():
                return []
            boxes, scores, class_ids = boxes[mask], scores[mask], class_ids[mask]

        results: list[Detection] = []
        # NMS HAR BIR KLASS ICHIDA alohida: stol ustidagi telefon va
        # uning ustidagi qo'l ramkalari ustma-ust tushadi, lekin ular
        # boshqa obyektlar va biri ikkinchisini bostirmasligi kerak.
        for code in np.unique(class_ids):
            index = np.where(class_ids == code)[0]
            keep_index = nms(boxes[index], scores[index], self._iou)
            for position in keep_index:
                row = index[position]
                results.append(
                    Detection(
                        cls=self._label(int(code)),
                        code=int(code),
                        score=float(scores[row]),
                        bbox=boxes[row],
                    )
                )

        if results:
            restored = self._letterbox.restore(np.array([item.bbox for item in results]))
            for item, bbox in zip(results, restored):
                item.bbox = bbox
        return results

    # ------------------------------------------------------------------
    def _label(self, code: int) -> str:
        if self._allowed and code in self._allowed:
            return self._allowed[code]
        if 0 <= code < len(self._names):
            return self._names[code]
        return "class_{}".format(code)

    def _build_allowed(self, classes: Optional[list]) -> Optional[dict]:
        """
        `{kod: nom}` — serverdan kelgan ruxsat etilgan klasslar.

        `None` — filtr YO'Q (barcha klasslar o'tadi). Bu holat
        sozlama bo'sh bo'lganda uchraydi va u "hech narsani
        aniqlama" degani EMAS: filtrsiz ishlash administratorga
        model nimalarni ko'rayotganini sinab ko'rish imkonini
        beradi.
        """
        if not classes:
            return None
        mapping = {}
        for item in classes:
            try:
                mapping[int(item["code"])] = str(item.get("name") or item["code"])
            except (KeyError, TypeError, ValueError):
                log.warning("Klass yozuvi buzuq, o'tkazib yuborildi: %r", item)
        return mapping or None

    def _load_labels(self) -> list:
        """
        `<model>.labels.txt` — maxsus o'qitilgan model uchun.

        Yo'q bo'lsa bo'sh ro'yxat: nomlar serverdagi klass
        ro'yxatidan olinadi va u yetarli. Fayl faqat DIAGNOSTIKA
        uchun kerak - filtrga tushmagan klassni log'da nom bilan
        ko'rish uchun.
        """
        path = self._path.with_suffix(".labels.txt")
        if not path.exists():
            return []
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            log.warning("Klass nomlari o'qilmadi: %s", path)
            return []
        return [line.strip() for line in lines if line.strip()]
