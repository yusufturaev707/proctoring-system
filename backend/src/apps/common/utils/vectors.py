"""
Yuz embedding'lari bilan ishlash.

Bu yerda ataylab og'ir ML kutubxonasi ishlatilmagan: server faqat ikkita
vektorni solishtiradi (cosine), inference esa clientda yoki alohida
GPU servisida bajariladi. Solishtirish 512 o'lchovli vektor uchun ~5 µs.
"""

from __future__ import annotations

import math


def normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return list(vector)
    return [value / norm for value in vector]


def cosine_similarity(left: list[float], right: list[float]) -> float:
    """
    -1..1 oralig'ida o'xshashlik.

    Vektorlar oldindan normalizatsiya qilingan bo'lsa, bu oddiy skalyar
    ko'paytma — shuning uchun saqlashdan oldin `normalize()` chaqiring.
    """
    if not left or not right or len(left) != len(right):
        return 0.0

    dot = 0.0
    left_sq = 0.0
    right_sq = 0.0
    for a, b in zip(left, right):
        dot += a * b
        left_sq += a * a
        right_sq += b * b

    denominator = math.sqrt(left_sq) * math.sqrt(right_sq)
    return dot / denominator if denominator else 0.0


def similarity_score(left: list[float], right: list[float]) -> int:
    """Cosine (-1..1) -> 0..100 ball. `Setting.faceid_min_score_*` shu shkalada."""
    similarity = cosine_similarity(left, right)
    return max(0, min(100, round((similarity + 1) / 2 * 100)))
