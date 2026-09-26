"""
YOLO oilasidagi modellar uchun umumiy amallar.

Obyekt aniqlash va poza baholash BIR XIL kirish tayyorlashdan
o'tadi (letterbox) va bir xil NMS ishlatadi. Ularni ikki faylda
takrorlash koordinata o'girishdagi xatoni ikki joyga tarqatardi -
va u eng yomon turdagi xato: hech narsa yiqilmaydi, ramkalar
shunchaki siljigan bo'ladi.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass
class Letterbox:
    """
    Kadrni model kirishiga NISBATNI SAQLAB moslashtiradi.

    NIMA UCHUN oddiy `resize` EMAS: 16:9 kadrni 640x640 ga cho'zish
    obyektlarni gorizontal ravishda siqadi. Model esa nisbati
    buzilmagan rasmlarda o'qitilgan va siqilgan telefonni
    "telefon" deb tanimasligi mumkin - aniqlik sezilarli tushadi.

    Bo'sh joy kulrang (114) bilan to'ldiriladi - Ultralytics
    o'qitishda ishlatadigan qiymat. Boshqa rang model uchun
    "begona" tekstura bo'lardi.

    `scale`, `pad_x`, `pad_y` SAQLANADI: natijadagi ramkalarni
    asl kadr koordinatalariga qaytarish uchun ular kerak.
    """

    size: int
    scale: float = 1.0
    pad_x: float = 0.0
    pad_y: float = 0.0
    original_width: int = 0
    original_height: int = 0

    def apply(self, frame: np.ndarray) -> np.ndarray:
        """BGR kadr -> `(1, 3, size, size)` float32 tensor."""
        import cv2

        height, width = frame.shape[:2]
        self.original_width, self.original_height = width, height

        self.scale = min(self.size / max(1, width), self.size / max(1, height))
        new_width = int(round(width * self.scale))
        new_height = int(round(height * self.scale))

        # `INTER_LINEAR` kichraytirishda `INTER_AREA` dan tezroq va
        # detektsiya aniqligiga sezilarli ta'sir qilmaydi. Bu yerda
        # tezlik muhimroq: amal har kadrda bajariladi.
        resized = cv2.resize(frame, (new_width, new_height), interpolation=cv2.INTER_LINEAR)

        canvas = np.full((self.size, self.size, 3), 114, dtype=np.uint8)
        self.pad_x = (self.size - new_width) / 2
        self.pad_y = (self.size - new_height) / 2
        top, left = int(self.pad_y), int(self.pad_x)
        canvas[top : top + new_height, left : left + new_width] = resized

        # BGR -> RGB, HWC -> CHW, 0..255 -> 0..1.
        tensor = canvas[:, :, ::-1].transpose(2, 0, 1).astype(np.float32) / 255.0
        return np.ascontiguousarray(tensor[None])

    def restore(self, boxes: np.ndarray) -> np.ndarray:
        """Model koordinatalarini ASL kadr koordinatalariga qaytaradi."""
        if len(boxes) == 0:
            return boxes
        restored = np.asarray(boxes, dtype=np.float32).copy()
        restored[:, [0, 2]] = (restored[:, [0, 2]] - self.pad_x) / max(self.scale, 1e-6)
        restored[:, [1, 3]] = (restored[:, [1, 3]] - self.pad_y) / max(self.scale, 1e-6)

        # Kadr chegarasiga qisamiz: letterbox to'ldirmasida topilgan
        # obyekt manfiy koordinata berishi mumkin va u keyinchalik
        # kesib olishda (dalil kadri) istisno berardi.
        restored[:, [0, 2]] = restored[:, [0, 2]].clip(0, self.original_width)
        restored[:, [1, 3]] = restored[:, [1, 3]].clip(0, self.original_height)
        return restored

    def restore_points(self, points: np.ndarray) -> np.ndarray:
        """Nuqtalar (poza kalit nuqtalari) uchun — `(N, K, 2+)` shaklida."""
        if len(points) == 0:
            return points
        restored = np.asarray(points, dtype=np.float32).copy()
        restored[..., 0] = (restored[..., 0] - self.pad_x) / max(self.scale, 1e-6)
        restored[..., 1] = (restored[..., 1] - self.pad_y) / max(self.scale, 1e-6)
        return restored


def xywh_to_xyxy(boxes: np.ndarray) -> np.ndarray:
    """
    `(cx, cy, w, h)` -> `(x1, y1, x2, y2)`.

    YOLOv8 markaz + o'lcham shaklida chiqaradi, qolgan hamma narsa
    (NMS, IoU, kesib olish) burchaklar bilan ishlaydi.
    """
    boxes = np.asarray(boxes, dtype=np.float32)
    result = np.empty_like(boxes)
    result[:, 0] = boxes[:, 0] - boxes[:, 2] / 2
    result[:, 1] = boxes[:, 1] - boxes[:, 3] / 2
    result[:, 2] = boxes[:, 0] + boxes[:, 2] / 2
    result[:, 3] = boxes[:, 1] + boxes[:, 3] / 2
    return result


def nms(boxes: np.ndarray, scores: np.ndarray, threshold: float = 0.45) -> list:
    """
    Non-Maximum Suppression — takroriy ramkalarni olib tashlaydi.

    YOLO bitta obyekt uchun o'nlab ustma-ust ramka chiqaradi. Ularsiz
    bitta telefon o'nta "aniqlanish" bo'lardi va kuzatuvchi (ByteTrack)
    ularning har biriga alohida iz ochardi.

    `cv2.dnn.NMSBoxes` ISHLATILMAYDI: u ba'zi OpenCV nashrlarida
    bo'sh kirishda istisno beradi va qaytaradigan shakli versiyaga
    qarab farq qiladi ((N,) yoki (N,1)). Bu yerdagi ~15 qator undan
    qisqaroq va xulqi barqaror.
    """
    if len(boxes) == 0:
        return []

    boxes = np.asarray(boxes, dtype=np.float32)
    scores = np.asarray(scores, dtype=np.float32)

    x1, y1, x2, y2 = boxes[:, 0], boxes[:, 1], boxes[:, 2], boxes[:, 3]
    areas = np.clip(x2 - x1, 0, None) * np.clip(y2 - y1, 0, None)
    order = scores.argsort()[::-1]

    keep: list = []
    while order.size > 0:
        current = int(order[0])
        keep.append(current)
        if order.size == 1:
            break

        rest = order[1:]
        left = np.maximum(x1[current], x1[rest])
        top = np.maximum(y1[current], y1[rest])
        right = np.minimum(x2[current], x2[rest])
        bottom = np.minimum(y2[current], y2[rest])

        inter = np.clip(right - left, 0, None) * np.clip(bottom - top, 0, None)
        union = areas[current] + areas[rest] - inter
        iou = np.where(union > 0, inter / np.maximum(union, 1e-6), 0.0)

        order = rest[iou <= threshold]
    return keep
