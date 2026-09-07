from collections import OrderedDict

from rest_framework.pagination import CursorPagination, PageNumberPagination
from rest_framework.response import Response


class DefaultPagination(PageNumberPagination):
    """Konfiguratsiya jadvallari uchun oddiy sahifalash."""

    page_size = 25
    page_size_query_param = "page_size"
    max_page_size = 200

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("count", self.page.paginator.count),
                    ("page", self.page.number),
                    ("pages", self.page.paginator.num_pages),
                    ("page_size", self.get_page_size(self.request)),
                    ("results", data),
                ]
            )
        )


class EventCursorPagination(CursorPagination):
    """
    Hodisalar/skrinshotlar uchun — MAJBURIY ravishda cursor.

    Sabab: `ProctoringEvent` jadvalida milliardlab qator bo'ladi.
    OFFSET-based sahifalashda `LIMIT 25 OFFSET 1000000` Postgres'ni
    million qatorni skanerlashga majbur qiladi. Cursor esa har doim
    indeks bo'yicha `WHERE occurred_at < ?` — o'lchamdan qat'i nazar tez.
    """

    page_size = 100
    max_page_size = 500
    page_size_query_param = "page_size"
    ordering = "-occurred_at"

    def get_paginated_response(self, data):
        return Response(
            OrderedDict(
                [
                    ("next", self.get_next_link()),
                    ("previous", self.get_previous_link()),
                    ("results", data),
                ]
            )
        )


class SessionCursorPagination(EventCursorPagination):
    ordering = "-created_at"


class ScreenshotCursorPagination(EventCursorPagination):
    """
    Skrinshotlar uchun — kursor `-captured_at` bo'yicha.

    `EventCursorPagination` ni to'g'ridan-to'g'ri ishlatib bo'lmaydi: uning
    `ordering` i `-occurred_at`, bunday ustun esa skrinshot jadvallarida
    umuman yo'q va DRF `FieldError` bilan yiqiladi.
    """

    ordering = "-captured_at"


class AuditCursorPagination(EventCursorPagination):
    """
    Audit uchun — kursor `-id` bo'yicha.

    `created_at` unikal EMAS: bitta so'rov bir necha audit yozuvi yaratsa,
    ular bir xil `auto_now_add` qiymatini oladi. Kursor unikal bo'lmagan
    ustunga qurilsa, sahifa chegarasiga tushgan yozuvlar takrorlanadi
    yoki umuman tushib qoladi — huquqiy dalil bo'lgan jurnal uchun bu
    qabul qilib bo'lmaydi. `-id` monoton va unikal, `AuditLog.Meta.ordering`
    ham aynan shunday.
    """

    page_size = 50
    ordering = "-id"
