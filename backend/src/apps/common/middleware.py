import uuid

from apps.common.logging import request_id_var


class RequestIDMiddleware:
    """
    Har bir so'rovga id beradi va uni log'larga hamda javob header'iga qo'shadi.

    Minglab client bir vaqtda ishlaganda, aniq bitta talabaning muammosini
    log'dan ajratib olishning yagona amaliy yo'li shu.
    """

    HEADER = "HTTP_X_REQUEST_ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request_id = request.META.get(self.HEADER) or uuid.uuid4().hex[:16]
        request.request_id = request_id
        token = request_id_var.set(request_id)
        try:
            response = self.get_response(request)
        finally:
            request_id_var.reset(token)
        response["X-Request-ID"] = request_id
        return response
