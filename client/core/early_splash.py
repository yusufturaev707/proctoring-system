"""
Nativ ishga tushish oynasi — Qt'dan OLDIN, bosilgan zahoti.

NIMA UCHUN QT SPLASH YETMAYDI. `ui/widgets/startup_splash.py` faqat
QApplication paydo bo'lgandan keyin chiqadi, undan oldin esa: monitorlarni
uzish, boshqa dasturlarni yopish, tahdid skaneri, PyQt importi va -
administrator huquqisiz ochilganda - butun jarayonni vazifa orqali qayta
ochish (`core/elevation.py`). Sekin mashinada bu 2-4 soniya bo'sh ekran
edi va xodim "ochilmadi" deb belgini qayta bosardi.

NIMA UCHUN O'Z THREAD'IDA. Asosiy thread shu soniyalarda band (tozalash,
import, oyna qurish) va hodisa sikli yo'q. Oyna o'z xabar sikliga ega
bo'lgan fon thread'ida yashaydi, ya'ni asosiy thread qotganda ham
chiziladi va progress chizig'i yuguradi - "dastur ishlayapti" belgisi.
Win32 oyna xabarlari faqat uni yaratgan thread'ga keladi, shuning uchun
asosiy thread unga faqat `PostMessageW` bilan murojaat qiladi.

Faqat ctypes (user32/gdi32/gdiplus/dwmapi) - yangi bog'liqlik yo'q,
Qt yuklanmaydi. Har qanday xato JIMGINA yutiladi: bu bezak, ishga
tushishning sharti emas (`main` Qt splash'ga qaytadi).

`WS_EX_NOACTIVATE` + `MA_NOACTIVATE`: oyna fokusni olmaydi, ya'ni
`app_closer` va kiosk oynasi bilan fokus uchun kurashmaydi. Kursor -
`IDC_APPSTARTING` (o'q + qum soat), Windows'ning "dastur ochilmoqda"
belgisi.
"""

from __future__ import annotations

import logging
import sys
import threading

log = logging.getLogger(__name__)

_CARD_W = 420
_CARD_H = 230
_TICK_MS = 16

_WM_DESTROY = 0x0002
_WM_PAINT = 0x000F
_WM_CLOSE = 0x0010
_WM_ERASEBKGND = 0x0014
_WM_MOUSEACTIVATE = 0x0021
_WM_TIMER = 0x0113
_WM_APP_TEXT = 0x8000 + 1
_MA_NOACTIVATE = 3

_WS_POPUP = 0x80000000
_WS_EX_TOPMOST = 0x00000008
_WS_EX_TOOLWINDOW = 0x00000080
_WS_EX_NOACTIVATE = 0x08000000
_CS_DROPSHADOW = 0x00020000
_SW_SHOWNOACTIVATE = 4
_IDC_APPSTARTING = 32650
_SPI_GETWORKAREA = 0x0030
_DT_CENTER = 0x0001
_DT_VCENTER = 0x0004
_DT_SINGLELINE = 0x0020
_DT_END_ELLIPSIS = 0x8000
_SRCCOPY = 0x00CC0020
_TRANSPARENT = 1
_CLEARTYPE_QUALITY = 5
_DWMWA_WINDOW_CORNER_PREFERENCE = 33
_DWMWCP_ROUND = 2
_PER_MONITOR_AWARE_V2 = -4


def _rgb(hex_color: str) -> int:
    value = hex_color.lstrip("#")
    r, g, b = int(value[0:2], 16), int(value[2:4], 16), int(value[4:6], 16)
    return r | (g << 8) | (b << 16)  # COLORREF - BGR


class EarlySplash:
    """`show()` -> `set_text()` ... -> `close()`. Hamma metod xatoga chidamli."""

    def __init__(self, title: str, text: str = "Dastur ishga tushmoqda…", *, logo_path: str = "") -> None:
        self._title = title
        self._text = text
        self._logo_path = logo_path
        self._hwnd = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._phase = 0
        self.shown = False

    # ------------------------------------------------------------------
    # Asosiy thread tomoni
    # ------------------------------------------------------------------
    def show(self, timeout: float = 1.0) -> bool:
        """Oyna chizilguncha kutadi (qisqa) - `True` ko'rsatildi."""
        if sys.platform != "win32":
            return False
        self._thread = threading.Thread(target=self._run, name="early-splash", daemon=True)
        self._thread.start()
        self._ready.wait(timeout)
        return self.shown

    def set_text(self, text: str) -> None:
        self._text = text
        self._post(_WM_APP_TEXT)

    def close(self) -> None:
        if self._post(_WM_CLOSE) and self._thread is not None:
            self._thread.join(timeout=1.0)
        self.shown = False

    def _post(self, message: int) -> bool:
        if not self._hwnd:
            return False
        try:
            import ctypes
            from ctypes import wintypes

            post = ctypes.WinDLL("user32").PostMessageW
            post.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
            post.restype = wintypes.BOOL
            return bool(post(self._hwnd, message, 0, 0))
        except Exception:  # noqa: BLE001
            return False

    # ------------------------------------------------------------------
    # Splash thread'i
    # ------------------------------------------------------------------
    def _run(self) -> None:
        try:
            self._loop()
        except Exception:  # noqa: BLE001
            log.debug("Nativ splash ishlamadi", exc_info=True)
        finally:
            self._hwnd = None
            self._ready.set()

    def _loop(self) -> None:
        import ctypes
        from ctypes import wintypes

        from ui.styles import COLORS

        user32 = ctypes.WinDLL("user32", use_last_error=True)
        gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        self._declare(user32, gdi32, kernel32)

        # Faqat SHU thread'ning oynalari DPI'ni biladi - jarayon
        # standartiga tegilmaydi, uni Qt o'zi o'rnatadi.
        try:
            user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(_PER_MONITOR_AWARE_V2))
        except Exception:  # noqa: BLE001 - Windows 10 1607 dan eski
            pass
        try:
            dpi = user32.GetDpiForSystem() or 96
        except Exception:  # noqa: BLE001
            dpi = 96
        scale = dpi / 96.0
        width, height = int(_CARD_W * scale), int(_CARD_H * scale)

        area = wintypes.RECT()
        if not user32.SystemParametersInfoW(_SPI_GETWORKAREA, 0, ctypes.byref(area), 0):
            area.left, area.top = 0, 0
            area.right, area.bottom = user32.GetSystemMetrics(0), user32.GetSystemMetrics(1)
        x = area.left + (area.right - area.left - width) // 2
        y = area.top + (area.bottom - area.top - height) // 2

        palette = {
            "bg": _rgb(COLORS.get("surface_container_lowest", "#FFFFFF")),
            "title": _rgb(COLORS.get("on_surface", "#171D19")),
            "text": _rgb(COLORS.get("on_surface_variant", "#414941")),
            "track": _rgb(COLORS.get("surface_container_highest", "#DEE4DD")),
            "bar": _rgb(COLORS.get("primary", "#16A34A")),
        }
        title_font = gdi32.CreateFontW(-int(20 * scale), 0, 0, 0, 700, 0, 0, 0, 1, 0, 0,
                                       _CLEARTYPE_QUALITY, 0, "Segoe UI")
        text_font = gdi32.CreateFontW(-int(14 * scale), 0, 0, 0, 400, 0, 0, 0, 1, 0, 0,
                                      _CLEARTYPE_QUALITY, 0, "Segoe UI")
        logo = _GdiplusImage(self._logo_path)

        WNDPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, wintypes.HWND, wintypes.UINT,
                                     wintypes.WPARAM, wintypes.LPARAM)

        def paint(hwnd) -> None:
            ps = _PAINTSTRUCT()
            hdc = user32.BeginPaint(hwnd, ctypes.byref(ps))
            try:
                # Ikki buferli chizish - animatsiya miltillamasin.
                mem = gdi32.CreateCompatibleDC(hdc)
                bitmap = gdi32.CreateCompatibleBitmap(hdc, width, height)
                old_bitmap = gdi32.SelectObject(mem, bitmap)
                try:
                    self._draw(gdi32, user32, mem, width, height, scale, palette,
                               title_font, text_font, logo)
                    gdi32.BitBlt(hdc, 0, 0, width, height, mem, 0, 0, _SRCCOPY)
                finally:
                    gdi32.SelectObject(mem, old_bitmap)
                    gdi32.DeleteObject(bitmap)
                    gdi32.DeleteDC(mem)
            finally:
                user32.EndPaint(hwnd, ctypes.byref(ps))

        def wndproc(hwnd, msg, wparam, lparam):
            try:
                if msg == _WM_PAINT:
                    paint(hwnd)
                    return 0
                if msg == _WM_ERASEBKGND:
                    return 1
                if msg == _WM_TIMER:
                    self._phase += 1
                    user32.InvalidateRect(hwnd, None, False)
                    return 0
                if msg == _WM_APP_TEXT:
                    user32.InvalidateRect(hwnd, None, False)
                    return 0
                if msg == _WM_MOUSEACTIVATE:
                    return _MA_NOACTIVATE
                if msg == _WM_CLOSE:
                    user32.DestroyWindow(hwnd)
                    return 0
                if msg == _WM_DESTROY:
                    user32.PostQuitMessage(0)
                    return 0
            except Exception:  # noqa: BLE001 - callback'dan istisno chiqmasin
                log.debug("Splash xabarida xato", exc_info=True)
            return user32.DefWindowProcW(hwnd, msg, wparam, lparam)

        proc = WNDPROC(wndproc)  # havola thread oxirigacha tirik
        instance = kernel32.GetModuleHandleW(None)
        from core.single_instance import SPLASH_CLASS_NAME as class_name  # ikkinchi nusxa shu bo'yicha topadi
        wc = _WNDCLASSEXW()
        wc.cbSize = ctypes.sizeof(_WNDCLASSEXW)
        wc.style = _CS_DROPSHADOW
        wc.lpfnWndProc = ctypes.cast(proc, ctypes.c_void_p)
        wc.hInstance = instance
        wc.hCursor = user32.LoadCursorW(None, ctypes.c_void_p(_IDC_APPSTARTING))
        wc.lpszClassName = class_name
        atom = user32.RegisterClassExW(ctypes.byref(wc))
        if not atom:
            return

        hwnd = None
        try:
            hwnd = user32.CreateWindowExW(
                _WS_EX_TOPMOST | _WS_EX_TOOLWINDOW | _WS_EX_NOACTIVATE,
                class_name, self._title + " — yuklanmoqda", _WS_POPUP,
                x, y, width, height, None, None, instance, None,
            )
            if not hwnd:
                return
            try:
                corner = ctypes.c_int(_DWMWCP_ROUND)
                ctypes.WinDLL("dwmapi").DwmSetWindowAttribute(
                    wintypes.HWND(hwnd), _DWMWA_WINDOW_CORNER_PREFERENCE,
                    ctypes.byref(corner), ctypes.sizeof(corner),
                )
            except Exception:  # noqa: BLE001 - Windows 10: to'g'ri burchak
                pass
            self._hwnd = hwnd
            user32.ShowWindow(hwnd, _SW_SHOWNOACTIVATE)
            user32.UpdateWindow(hwnd)
            user32.SetTimer(hwnd, 1, _TICK_MS, None)
            self.shown = True
            self._ready.set()

            msg = wintypes.MSG()
            while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) > 0:
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        finally:
            self._hwnd = None
            if hwnd and user32.IsWindow(hwnd):
                user32.DestroyWindow(hwnd)
            user32.UnregisterClassW(class_name, instance)
            gdi32.DeleteObject(title_font)
            gdi32.DeleteObject(text_font)
            logo.dispose()

    def _draw(self, gdi32, user32, hdc, width, height, scale, palette, title_font, text_font, logo) -> None:
        import ctypes
        from ctypes import wintypes

        def fill(left, top, right, bottom, color):
            brush = gdi32.CreateSolidBrush(color)
            rect = wintypes.RECT(int(left), int(top), int(right), int(bottom))
            user32.FillRect(hdc, ctypes.byref(rect), brush)
            gdi32.DeleteObject(brush)

        def text(value, font, color, top, bottom):
            old = gdi32.SelectObject(hdc, font)
            gdi32.SetTextColor(hdc, color)
            rect = wintypes.RECT(int(24 * scale), int(top), int(width - 24 * scale), int(bottom))
            user32.DrawTextW(hdc, value, -1, ctypes.byref(rect),
                             _DT_CENTER | _DT_VCENTER | _DT_SINGLELINE | _DT_END_ELLIPSIS)
            gdi32.SelectObject(hdc, old)

        fill(0, 0, width, height, palette["bg"])
        gdi32.SetBkMode(hdc, _TRANSPARENT)

        logo_h = int(52 * scale)
        top = int(28 * scale)
        if logo.ok:
            logo_w = int(logo_h * logo.width / max(1, logo.height))
            logo.draw(hdc, (width - logo_w) // 2, top, logo_w, logo_h)
        text(self._title, title_font, palette["title"], top + logo_h + 8 * scale, top + logo_h + 40 * scale)
        text(self._text, text_font, palette["text"], top + logo_h + 42 * scale, top + logo_h + 66 * scale)

        # Noaniq progress: chiziq bo'ylab yuguruvchi bo'lak. Qotgan
        # dastur bilan "ishlayotgan" dasturning farqi aynan shunda.
        bar_left, bar_right = 36 * scale, width - 36 * scale
        bar_top = height - 34 * scale
        bar_h = max(3, int(4 * scale))
        fill(bar_left, bar_top, bar_right, bar_top + bar_h, palette["track"])
        span = bar_right - bar_left
        seg = span * 0.28
        period = 90  # kadr (~1.4 s)
        pos = (self._phase % period) / period * (span + seg) - seg
        start = max(bar_left, bar_left + pos)
        end = min(bar_right, bar_left + pos + seg)
        if end > start:
            fill(start, bar_top, end, bar_top + bar_h, palette["bar"])

    @staticmethod
    def _declare(user32, gdi32, kernel32) -> None:
        # `argtypes` MAJBURIY (CLAUDE.md, ctypes tuzog'i): 64-bit
        # deskriptorlar usiz `OverflowError` beradi yoki kesiladi.
        import ctypes
        from ctypes import wintypes

        H = wintypes.HANDLE
        user32.SetThreadDpiAwarenessContext.argtypes = (ctypes.c_void_p,)
        user32.SetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.GetDpiForSystem.restype = wintypes.UINT
        user32.SystemParametersInfoW.argtypes = (wintypes.UINT, wintypes.UINT, wintypes.LPVOID, wintypes.UINT)
        user32.GetSystemMetrics.argtypes = (ctypes.c_int,)
        user32.LoadCursorW.argtypes = (wintypes.HINSTANCE, ctypes.c_void_p)
        user32.LoadCursorW.restype = H
        user32.RegisterClassExW.argtypes = (ctypes.c_void_p,)
        user32.RegisterClassExW.restype = wintypes.ATOM
        user32.UnregisterClassW.argtypes = (wintypes.LPCWSTR, wintypes.HINSTANCE)
        user32.CreateWindowExW.argtypes = (
            wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, wintypes.LPVOID,
        )
        user32.CreateWindowExW.restype = wintypes.HWND
        user32.DefWindowProcW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
        user32.DefWindowProcW.restype = ctypes.c_ssize_t
        for name in ("ShowWindow",):
            getattr(user32, name).argtypes = (wintypes.HWND, ctypes.c_int)
        for name in ("UpdateWindow", "DestroyWindow", "IsWindow"):
            getattr(user32, name).argtypes = (wintypes.HWND,)
        user32.SetTimer.argtypes = (wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p)
        user32.SetTimer.restype = ctypes.c_size_t
        user32.InvalidateRect.argtypes = (wintypes.HWND, ctypes.c_void_p, wintypes.BOOL)
        user32.BeginPaint.argtypes = (wintypes.HWND, ctypes.c_void_p)
        user32.BeginPaint.restype = wintypes.HDC
        user32.EndPaint.argtypes = (wintypes.HWND, ctypes.c_void_p)
        user32.FillRect.argtypes = (wintypes.HDC, ctypes.c_void_p, wintypes.HBRUSH)
        user32.DrawTextW.argtypes = (wintypes.HDC, wintypes.LPCWSTR, ctypes.c_int, ctypes.c_void_p, wintypes.UINT)
        user32.GetMessageW.argtypes = (ctypes.c_void_p, wintypes.HWND, wintypes.UINT, wintypes.UINT)
        user32.GetMessageW.restype = wintypes.BOOL
        user32.TranslateMessage.argtypes = (ctypes.c_void_p,)
        user32.DispatchMessageW.argtypes = (ctypes.c_void_p,)
        user32.DispatchMessageW.restype = ctypes.c_ssize_t
        user32.PostQuitMessage.argtypes = (ctypes.c_int,)
        kernel32.GetModuleHandleW.argtypes = (wintypes.LPCWSTR,)
        kernel32.GetModuleHandleW.restype = wintypes.HMODULE

        gdi32.CreateFontW.argtypes = (
            ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
            wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPCWSTR,
        )
        gdi32.CreateFontW.restype = wintypes.HFONT
        gdi32.CreateCompatibleDC.argtypes = (wintypes.HDC,)
        gdi32.CreateCompatibleDC.restype = wintypes.HDC
        gdi32.CreateCompatibleBitmap.argtypes = (wintypes.HDC, ctypes.c_int, ctypes.c_int)
        gdi32.CreateCompatibleBitmap.restype = wintypes.HBITMAP
        gdi32.SelectObject.argtypes = (wintypes.HDC, wintypes.HGDIOBJ)
        gdi32.SelectObject.restype = wintypes.HGDIOBJ
        gdi32.DeleteObject.argtypes = (wintypes.HGDIOBJ,)
        gdi32.DeleteDC.argtypes = (wintypes.HDC,)
        gdi32.BitBlt.argtypes = (
            wintypes.HDC, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            wintypes.HDC, ctypes.c_int, ctypes.c_int, wintypes.DWORD,
        )
        gdi32.CreateSolidBrush.argtypes = (wintypes.COLORREF,)
        gdi32.CreateSolidBrush.restype = wintypes.HBRUSH
        gdi32.SetBkMode.argtypes = (wintypes.HDC, ctypes.c_int)
        gdi32.SetTextColor.argtypes = (wintypes.HDC, wintypes.COLORREF)


class _GdiplusImage:
    """
    PNG logotip (alfa kanal bilan) - GDI'ning o'zi PNG o'qimaydi.

    Fayl yo'q yoki GDI+ ishlamasa `ok=False` va logotipsiz chiziladi.
    """

    def __init__(self, path: str) -> None:
        self.ok = False
        self.width = self.height = 0
        self._token = None
        self._image = None
        if not path:
            return
        try:
            import ctypes
            from ctypes import wintypes

            self._gdip = ctypes.WinDLL("gdiplus")
            g = self._gdip
            g.GdiplusStartup.argtypes = (ctypes.POINTER(ctypes.c_size_t), ctypes.c_void_p, ctypes.c_void_p)
            g.GdipLoadImageFromFile.argtypes = (wintypes.LPCWSTR, ctypes.POINTER(ctypes.c_void_p))
            g.GdipGetImageWidth.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.UINT))
            g.GdipGetImageHeight.argtypes = (ctypes.c_void_p, ctypes.POINTER(wintypes.UINT))
            g.GdipCreateFromHDC.argtypes = (wintypes.HDC, ctypes.POINTER(ctypes.c_void_p))
            g.GdipSetInterpolationMode.argtypes = (ctypes.c_void_p, ctypes.c_int)
            g.GdipDrawImageRectI.argtypes = (ctypes.c_void_p, ctypes.c_void_p,
                                             ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int)
            g.GdipDeleteGraphics.argtypes = (ctypes.c_void_p,)
            g.GdipDisposeImage.argtypes = (ctypes.c_void_p,)
            g.GdiplusShutdown.argtypes = (ctypes.c_size_t,)

            class _Input(ctypes.Structure):
                _fields_ = [("version", wintypes.UINT), ("callback", ctypes.c_void_p),
                            ("no_thread", wintypes.BOOL), ("no_codecs", wintypes.BOOL)]

            token = ctypes.c_size_t()
            startup = _Input(1, None, False, False)
            if g.GdiplusStartup(ctypes.byref(token), ctypes.byref(startup), None) != 0:
                return
            self._token = token.value
            image = ctypes.c_void_p()
            if g.GdipLoadImageFromFile(path, ctypes.byref(image)) != 0 or not image.value:
                self.dispose()
                return
            self._image = image
            w, h = wintypes.UINT(), wintypes.UINT()
            g.GdipGetImageWidth(image, ctypes.byref(w))
            g.GdipGetImageHeight(image, ctypes.byref(h))
            self.width, self.height = w.value, h.value
            self.ok = self.width > 0 and self.height > 0
        except Exception:  # noqa: BLE001
            log.debug("Splash logotipi yuklanmadi", exc_info=True)
            self.dispose()

    def draw(self, hdc, x: int, y: int, w: int, h: int) -> None:
        import ctypes

        graphics = ctypes.c_void_p()
        if self._gdip.GdipCreateFromHDC(hdc, ctypes.byref(graphics)) != 0:
            return
        try:
            self._gdip.GdipSetInterpolationMode(graphics, 7)  # HighQualityBicubic
            self._gdip.GdipDrawImageRectI(graphics, self._image, x, y, w, h)
        finally:
            self._gdip.GdipDeleteGraphics(graphics)

    def dispose(self) -> None:
        self.ok = False
        try:
            if self._image is not None:
                self._gdip.GdipDisposeImage(self._image)
            if self._token is not None:
                self._gdip.GdiplusShutdown(self._token)
        except Exception:  # noqa: BLE001
            pass
        self._image = None
        self._token = None


def _structures():
    import ctypes
    from ctypes import wintypes

    class WNDCLASSEXW(ctypes.Structure):
        _fields_ = [
            ("cbSize", wintypes.UINT), ("style", wintypes.UINT), ("lpfnWndProc", ctypes.c_void_p),
            ("cbClsExtra", ctypes.c_int), ("cbWndExtra", ctypes.c_int), ("hInstance", wintypes.HINSTANCE),
            ("hIcon", wintypes.HICON), ("hCursor", wintypes.HANDLE), ("hbrBackground", wintypes.HBRUSH),
            ("lpszMenuName", wintypes.LPCWSTR), ("lpszClassName", wintypes.LPCWSTR), ("hIconSm", wintypes.HICON),
        ]

    class PAINTSTRUCT(ctypes.Structure):
        _fields_ = [
            ("hdc", wintypes.HDC), ("fErase", wintypes.BOOL), ("rcPaint", wintypes.RECT),
            ("fRestore", wintypes.BOOL), ("fIncUpdate", wintypes.BOOL), ("rgbReserved", ctypes.c_byte * 32),
        ]

    return WNDCLASSEXW, PAINTSTRUCT


if sys.platform == "win32":
    _WNDCLASSEXW, _PAINTSTRUCT = _structures()
