#!/usr/bin/env bash
#
# Proctoring — deploy (bitta server, `/srv/proctoring` = repo ildizi).
#
#   sudo -u proctoring bash backend/deploy/deploy.sh                  # yangilash
#   sudo -u proctoring bash backend/deploy/deploy.sh --first-install  # birinchi marta
#
# Takroriy ishga tushirish xavfsiz. Har qadam oldingisi muvaffaqiyatli
# bo'lsagina bajariladi (`set -e`): yarim yangilangan server — eng yomon holat.
# Frontend ATOMIK almashtiriladi: yangi build to'liq chiqmaguncha nginx
# eskisini beradi, eskisi `dist.old` da qoladi (tezkor orqaga qaytish).
#
# systemd'ni qayta ishga tushirish uchun `proctoring` foydalanuvchisiga
# faqat `systemctl restart proctoring-*` sudo huquqi kerak (README).

set -euo pipefail

APP="${APP:-/srv/proctoring}"
BACKEND="$APP/backend"
FRONTEND="$APP/frontend"
VENV="$BACKEND/.venv"
PY="$VENV/bin/python"
FIRST_INSTALL=0
[[ "${1:-}" == "--first-install" ]] && FIRST_INSTALL=1

step() { printf '\n\033[1;34m==> %s\033[0m\n' "$*"; }
die()  { printf '\033[1;31mXATO: %s\033[0m\n' "$*" >&2; exit 1; }

# ---------------------------------------------------------------- .env
step ".env tekshiruvi"
[[ -f "$BACKEND/.env" ]] || die "$BACKEND/.env yo'q — deploy/env.production.example dan nusxalang"
for key in SECRET_KEY TOKEN_HASH_KEY FIELD_ENCRYPTION_KEY JWT_SIGNING_KEY POSTGRES_PASSWORD ALLOWED_HOSTS; do
  value="$(grep -E "^${key}=" "$BACKEND/.env" | tail -1 | cut -d= -f2-)"
  [[ -n "$value" ]] || die "$key .env da bo'sh"
done
grep -qE '^DJANGO_SETTINGS_MODULE=config\.settings\.production$' "$BACKEND/.env" \
  || die "DJANGO_SETTINGS_MODULE=config.settings.production emas"
# `.env` da sirlar bor — boshqalar o'qimasin.
chmod 600 "$BACKEND/.env"

# ---------------------------------------------------------------- kataloglar
step "Kataloglar"
# systemd `ReadWritePaths` ular MAVJUD bo'lishini talab qiladi.
mkdir -p "$APP/storage/screenshots" "$BACKEND/logs" "$BACKEND/var"

# ---------------------------------------------------------------- backend
step "Python paketlari"
[[ -x "$PY" ]] || python3 -m venv "$VENV"
"$PY" -m pip install --quiet --upgrade pip
"$PY" -m pip install --quiet -r "$BACKEND/requirements.txt"
# `src/` ni yo'lga qo'shadi — `celery -A config` va `manage.py` uchun
# (systemd'da PYTHONPATH ham bor, bu esa qo'lda chaqirilgan buyruqlar uchun).
"$PY" -m pip install --quiet --no-deps -e "$BACKEND"

cd "$BACKEND"
step "Django: production tekshiruvi"
"$PY" manage.py check --deploy --fail-level WARNING

step "Migratsiyalar"
"$PY" manage.py migrate --noinput

if (( FIRST_INSTALL )); then
  step "Birinchi o'rnatish: rollar va partitsiyalar"
  "$PY" manage.py seed_base_data
  # Bo'sh jadvalda bir zumda; katta jadvalda buyruqning o'zi to'xtaydi.
  "$PY" manage.py setup_partitions --apply --days 30
else
  # Faqat holat: kunlik partitsiyalarni Celery beat yaratadi.
  "$PY" manage.py setup_partitions
fi

step "Statik fayllar"
"$PY" manage.py collectstatic --noinput --verbosity 0

# ---------------------------------------------------------------- frontend
step "Frontend build"
cd "$FRONTEND"
npm ci --no-audit --no-fund
rm -rf dist.new
npm run build -- --outDir dist.new --emptyOutDir
[[ -f dist.new/index.html ]] || die "frontend build'da index.html yo'q"
rm -rf dist.old
[[ -d dist ]] && mv dist dist.old
mv dist.new dist

# ---------------------------------------------------------------- servislar
step "Servislarni qayta ishga tushirish"
sudo systemctl restart proctoring-api proctoring-ws \
  proctoring-celery-ingest proctoring-celery-maintenance proctoring-celery-beat

step "Salomatlik tekshiruvi"
# nginx kabi so'raymiz: `127.0.0.1` ALLOWED_HOSTS da yo'q (400), HTTPS
# belgisisiz esa SECURE_SSL_REDIRECT 301 qaytaradi — ikkalasi ham sog'lom
# serverni "yiqildi" deb ko'rsatardi.
HOST="$(grep -E '^ALLOWED_HOSTS=' "$BACKEND/.env" | tail -1 | cut -d= -f2- | cut -d, -f1)"
for _ in $(seq 1 20); do
  if curl -fsS -H "Host: $HOST" -H "X-Forwarded-Proto: https"        http://127.0.0.1:8000/readyz/ >/dev/null 2>&1; then
    printf '\033[1;32mTayyor: API javob beryapti (/readyz/).\033[0m\n'
    exit 0
  fi
  sleep 1
done
die "API 20 soniyada tayyor bo'lmadi — journalctl -u proctoring-api -n 100"
