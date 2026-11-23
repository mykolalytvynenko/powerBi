# Зразки викладок — веб-перегляд (Python)

Адреса: **https://merch.vsisvoi.ua**

Веб-застосунок **тільки для перегляду** фото викладок з SharePoint. Логіка та сама, що в Power Apps:
магазин → бренд → остання викладка кожного відділу → фото (+ 10 попередніх викладок), режим «Всі магазини».
Працює в браузері на телефоні й комп'ютері. Дані не змінює: flow MB-01/MB-03 і списки лишаються як є.

- **FastAPI + Jinja2**, без окремого фронтенду.
- **Вхід:** Entra ID (MSAL, authorization code + PKCE). Хто може входити, керується в Entra
  (Enterprise app → Assignment required + група).
  Вхід можна вимкнути параметром `AUTH_DISABLED=1`: тоді сторінки відкриті кожному, хто має мережевий
  доступ до сайту. На сервері docker він зараз вимкнений (`deploy/k3s-mbviewer.yaml`), бо сайт видно лише
  з внутрішньої мережі. Перед відкриттям в інтернет вхід треба повернути.
- **Дані:** Microsoft Graph, app-only, дозвіл `Sites.Selected` (read лише на сайт Merchandising).
- **Фото:** сервер бере мініатюри з Graph і кешує їх на диску, браузер токенів SharePoint не бачить.
- Списки (магазини, бренди, відділи, пакети) кешуються в пам'яті на `CACHE_TTL` секунд (типово 120).

Що потрібно від адміністратора Entra: `notes/python-viewer-for-oleksiy.md` у файлах проєкту
(App registration, `Sites.Selected`, домен, сертифікат).

## Запуск на своєму комп'ютері (демо-дані, без Entra)

```bash
cd viewer
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
FAKE_DATA=1 AUTH_DISABLED=1 uvicorn --factory app.main:app_factory --reload
# відкрити http://localhost:8000
pytest -q
```

З реальними даними: скопіюйте `.env.example` у `.env`, заповніть TENANT_ID, CLIENT_ID, CLIENT_SECRET,
SESSION_SECRET, `BASE_URL=http://localhost:8000`, потім `set -a; . ./.env; set +a` і той самий `uvicorn`.

## Розгортання на сервері docker (10.10.252.108): pod у k3s

Порти 80/443 на сервері належать Traefik у k3s, тому застосунок працює як pod у кластері.
Traefik маршрутизує на нього `merch.vsisvoi.ua`, сертифікат видає cert-manager
(`letsencrypt-prod`, DNS-01 через Cloudflare). Наявні Ingress не змінюються.

На сервері немає Docker, тому власний образ не збирається. Як у sync і mail-relay:
образ `python:3.13-slim`, код у ConfigMap, залежності ставить initContainer під час старту пода.
Усе це робить `deploy/k3s-deploy.sh`.

Перед початком:
- запис `merch.vsisvoi.ua` у внутрішньому DNS (CNAME на `docker.vsisvoi.ua`, як у wiki/git/grafana);
- Redirect URI `https://merch.vsisvoi.ua/auth/callback` в App registration.

Перший раз:

```bash
sudo git clone https://github.com/mykolalytvynenko/powerBi /opt/mbviewer

# секрети: тільки на сервері, у git їх немає
sudo mkdir -p /etc/mbviewer
sudo cp /opt/mbviewer/viewer/deploy/mbviewer-secrets.env.example /etc/mbviewer/mbviewer.env
sudo chmod 600 /etc/mbviewer/mbviewer.env
sudo nano /etc/mbviewer/mbviewer.env        # TENANT_ID, CLIENT_ID, CLIENT_SECRET, SESSION_SECRET
sudo kubectl create namespace mbviewer
sudo kubectl -n mbviewer create secret generic mbviewer-env --from-env-file=/etc/mbviewer/mbviewer.env

# код у ConfigMap, маніфест, очікування запуску
sudo /opt/mbviewer/viewer/deploy/k3s-deploy.sh

sudo kubectl -n mbviewer get certificate    # дочекатися READY=True
curl -I https://merch.vsisvoi.ua/health
```

Оновлення коду: `cd /opt/mbviewer && sudo git pull && sudo viewer/deploy/k3s-deploy.sh`.

Зміна секретів: відредагувати `/etc/mbviewer/mbviewer.env`, потім

```bash
sudo kubectl -n mbviewer create secret generic mbviewer-env --from-env-file=/etc/mbviewer/mbviewer.env \
  --dry-run=client -o yaml | sudo kubectl apply -f -
sudo kubectl -n mbviewer rollout restart deployment/mbviewer
```

Корисне: `sudo kubectl -n mbviewer logs deploy/mbviewer`, `sudo kubectl -n mbviewer get pods`.
Якщо pod у стані CrashLoopBackOff, у логах буде, якої змінної бракує.
Сайт SharePoint (MerchandisingTest або Merchandising2) і `BASE_URL` задаються в ConfigMap
у `deploy/k3s-mbviewer.yaml`. Кеш мініатюр лежить у тимчасовому томі й після перезапуску
пода наповнюється заново. Під час старту pod завантажує залежності з PyPI (близько пів хвилини).

Сервер видно тільки з внутрішньої мережі (публічних DNS-записів немає). Доступ з інтернету
налаштовується окремо.

`Dockerfile` лишається для запуску там, де образ є чим зібрати; на цьому сервері він не використовується.

## Розгортання на окремому сервері з Nginx (без k3s)

Якщо порти 80/443 вільні: застосунок працює як служба systemd на `127.0.0.1:8000`, перед нею Nginx.

```bash
sudo apt install -y python3-venv nginx certbot python3-certbot-nginx git
sudo useradd --system --home /opt/mbviewer --shell /usr/sbin/nologin mbviewer
sudo git clone https://github.com/mykolalytvynenko/powerBi /opt/mbviewer
sudo python3 -m venv /opt/mbviewer/venv
sudo /opt/mbviewer/venv/bin/pip install -r /opt/mbviewer/viewer/requirements.txt

sudo mkdir -p /etc/mbviewer
sudo cp /opt/mbviewer/viewer/.env.example /etc/mbviewer/mbviewer.env
sudo nano /etc/mbviewer/mbviewer.env
sudo chown root:mbviewer /etc/mbviewer/mbviewer.env && sudo chmod 640 /etc/mbviewer/mbviewer.env

sudo cp /opt/mbviewer/viewer/deploy/mbviewer.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now mbviewer
curl http://127.0.0.1:8000/health

# Сертифікат потрібен до підключення сайту, бо конфіг Nginx на нього посилається.
sudo certbot certonly --nginx -d merch.vsisvoi.ua
sudo cp /opt/mbviewer/viewer/deploy/nginx-mbviewer.conf /etc/nginx/sites-available/mbviewer
sudo ln -s /etc/nginx/sites-available/mbviewer /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

Оновлення: `cd /opt/mbviewer && sudo git pull && sudo systemctl restart mbviewer`.

## Колонки SharePoint, які читає застосунок

| Список | Колонки |
|---|---|
| MerchandisingStores | Title, City, Aliases, IsActive |
| MerchandisingBrands | Title, Aliases, IsActive |
| MerchandisingDepartments | Title, IsActive (порядок як у списку) |
| MerchandisingBatches | Title (BatchID), Store, Brand, Department, Collection, MessageCreated, ProcessedPhotos, ChangeType, Status |
| MerchandisingPhotos | BatchID, PhotoIndex, LinkStatus, FileLeafRef |

Показуються пакети зі статусом Completed, Corrected, Partial і фото з LinkStatus = Linked (або порожнім).
Пакети без магазину видно тільки в режимі «Всі магазини».
