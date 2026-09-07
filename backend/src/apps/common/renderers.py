from rest_framework.renderers import JSONRenderer


class ApiJSONRenderer(JSONRenderer):
    """
    Barcha javoblarni bitta konvertga o'raydi:

        {"success": true,  "data": ..., "error": null}
        {"success": false, "data": null, "error": {...}}

    React tomonda har bir endpoint uchun alohida xato ishlovini yozmaslik
    imkonini beradi.
    """

    def render(self, data, accepted_media_type=None, renderer_context=None):
        renderer_context = renderer_context or {}
        response = renderer_context.get("response")
        status_code = getattr(response, "status_code", 200)

        # 204 No Content — RFC bo'yicha tanasi BO'LMASLIGI shart.
        # Konvertni bu yerda ham qo'shsak, `Content-Length` javob tanasi
        # bilan mos kelmaydi va brauzer `ERR_CONTENT_LENGTH_MISMATCH`
        # beradi (DRF `DestroyModelMixin` aynan 204 qaytaradi).
        if status_code == 204 or data is None and status_code in (205, 304):
            return b""

        # Allaqachon o'ralgan bo'lsa (exception handler) — qayta o'ramaymiz.
        if isinstance(data, dict) and "success" in data and "error" in data:
            payload = data
        elif status_code >= 400:
            payload = {"success": False, "data": None, "error": data}
        else:
            payload = {"success": True, "data": data, "error": None}

        return super().render(payload, accepted_media_type, renderer_context)
