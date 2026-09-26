"""
Dastur versiyasi va nomi — YAGONA manba.

Versiya uch joyda kerak va ular ilgari ajralib ketishi mumkin edi:

  * dasturning o'zi (`config.APP_VERSION` -> log, handshake'dagi
    `app_version`, oynadagi "v1.0.0");
  * `.exe` ning Windows versiya resursi (Explorer -> Xususiyatlar ->
    Tafsilotlar) - PyInstaller spec'i shu fayldan o'qiydi;
  * o'rnatuvchi (`AppVersion`, "Programs and Features" ro'yxati) -
    `installer/build.ps1` shu fayldan o'qib `ISCC /DAppVersion=` ga
    uzatadi.

Qo'lda uch joyda yozilgan versiya albatta ajralib ketardi: server
panelida "1.0.3" ko'rinib turgan mashinada aslida 1.0.2 ishlayotgan
bo'lardi va nosozlikni qidirish noto'g'ri build'dan boshlanardi.

FAYL HECH NARSA IMPORT QILMAYDI va shunday qolishi kerak: build
vositalari uni `runpy` bilan alohida o'qiydi (client muhitini -
Qt, onnxruntime - yuklamasdan).
"""

#: Semantik versiya. Windows resursi uchun faqat boshidagi raqamlar
#: olinadi ("1.2.0-rc1" -> 1.2.0.0), shuning uchun qo'shimcha
#: (`-rc1`) ixtiyoriy va faqat ko'rsatish uchun.
__version__ = "1.0.0"

APP_NAME = "Proctoring Client"

#: Katalog, `.exe` va ProgramData/AppData papkalari nomi. O'ZGARTIRMANG:
#: `core/bundle_paths.APP_DIR_NAME` bilan bir xil bo'lishi shart - aks
#: holda yangilangan dastur eski `device_id.json` ni topmaydi va har
#: bir mashina serverda qaytadan ro'yxatdan o'tadi.
EXE_NAME = "ProctoringClient"

COMPANY_NAME = "Proctoring System"
FILE_DESCRIPTION = "Imtihon kuzatuv tizimi - operator ish o'rni"
COPYRIGHT = "(c) Proctoring System"
