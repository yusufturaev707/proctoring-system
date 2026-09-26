# AI modellari

Model fayllari **versiya nazoratida saqlanmaydi** — ular 10–100 MB
va har bir muassasa o'z ro'yxati bilan o'qitilgan modelni
ishlatishi mumkin (`controls.ModelVersion` modeli aynan shuning
uchun mavjud).

## Kutilayotgan tuzilma

```
models/
  buffalo_l/          InsightFace (shaxs + yuz nuqtalari) — BUNDLE'DA BOR
    det_10g.onnx
    w600k_r50.onnx
    2d106det.onnx     nigoh moduli uchun 106 nuqta
  yolo/
    yolov8{n,s,m}.onnx        obyekt aniqlash
    yolov8{n,s,m}.labels.txt  (ixtiyoriy) maxsus o'qitilgan model uchun
  pose/
    yolov8{n,s,m}-pose.onnx   poza va qo'llar
```

Qaysi `{n,s,m}` ishlatilishini **unumdorlik profili** belgilaydi
(`proctoring/hardware/performance_profile.py`): CPU va zaif GPU
uchun `n`, GTX 1660S sinfida `s`, RTX 4070+ uchun `m`.

## Model yo'q bo'lsa nima bo'ladi

Modul **jimgina o'chadi**, dastur to'xtamaydi:

* `YoloDetector.load()` `False` qaytaradi, sabab `error` da;
* `detect()` bo'sh ro'yxat beradi va istisno tashlamaydi;
* kuzatuv qolgan qismi (shaxs, nigoh) ishlayveradi.

Bu ataylab: obyekt aniqlash modeli qo'shilmagan o'rnatishda ham
imtihon o'tishi kerak. Lekin sabab log'ga tushadi va u
`proctoring_degraded` hodisasiga aylanadi — "obyekt aniqlanmadi"
va "obyekt aniqlash umuman ishlamadi" bayonnomada ajratilishi
shart.

## Eksport

Ultralytics modelini ONNX'ga:

```bash
yolo export model=yolov8s.pt format=onnx opset=12 simplify=True dynamic=True
yolo export model=yolov8s-pose.pt format=onnx opset=12 simplify=True dynamic=True
```

**`dynamic=True` SHART.** Client kirish o'lchamini profilga qarab
tanlaydi (`performance_profile.detect_size` / `pose_size`: `high` 640,
`medium` 512, `low`/`cpu` 416, `minimal` 320). Qat'iy 640 bilan
eksport qilingan model 512 li kirishda ONNX Runtime xatosi bilan
yiqiladi va modul jimgina o'chadi.

**Kamida ikki o'lcham kerak**: mashinaning o'z profili uchun (GTX 1660
sinfida `s`) va `n` - GPU ishlamay qolsa client `cpu` profiliga tushadi
va aynan `yolov8n*.onnx` ni qidiradi.

Klass nomlari (`yolov8s.labels.txt`) ixtiyoriy - faqat log'da nom
ko'rish uchun; hodisaga tushadigan klasslar serverdagi sozlamadan.

Eksportni ALOHIDA vaqtinchalik muhitda qiling (`ultralytics` + CPU
`torch`): client muhitiga `ultralytics` o'rnatilmaydi. Windows'da
muhitni QISQA yo'lga qo'ying (masalan `D:\tmp_yolo_export`) - `torch`
ichidagi fayllar 260 belgilik yo'l chegarasidan oshib ketadi.

**Litsenziya**: Ultralytics YOLOv8 - AGPL-3.0.

Dekoder **YOLOv8 formatini** kutadi (`(1, 4+nc, N)`). YOLOv5
eksporti boshqa shaklga ega va u qabul qilinmaydi — shakl
tekshiruvi buni ishga tushishda ushlaydi.
