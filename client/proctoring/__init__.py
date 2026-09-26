"""
AI proktorlik moduli.

Bu paket mavjud `services/` dan ATAYLAB ajratilgan. `services/` —
imtihon oqimining o'zi (auth, sessiya, hodisa buferi, skrinshot) va u
proktorliksiz ham to'liq ishlaydi. Bu yerdagi kod esa qo'shimcha
qatlam: u kadrdan xulosa chiqaradi va hodisa taklif qiladi, lekin
hech qachon o'zi qaror qabul qilmaydi.

Chegara qat'iy: bu paket `services/monitoring.py` dagi buferga
hodisa qo'yadi va boshqa hech qayerga yozmaydi. Serverga to'g'ridan
to'g'ri murojaat qilmaydi, sessiyani boshqarmaydi, UI ni bilmaydi.
Shu tufayli AI qismini butunlay o'chirib qo'yish (`policy.enabled =
False`) imtihon oqimiga umuman tegmaydi.
"""
