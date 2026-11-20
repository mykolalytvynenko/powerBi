# Зразки викладок — веб-перегляд (Python)

Адреса: **https://merch.vsisvoi.ua**

Веб-застосунок **тільки для перегляду** фото викладок з SharePoint. Логіка та сама, що в Power Apps:
магазин → бренд → остання викладка кожного відділу → фото (+ 10 попередніх викладок), режим «Всі магазини».
Працює в браузері на телефоні й комп'ютері. Дані не змінює: flow MB-01/MB-03 і списки лишаються як є.

- **FastAPI + Jinja2**, без окремого фронтенду.
- **Вхід:** Entra ID (MSAL, authorization code + PKCE). Хто може входити, керується в Entra
  (Enterprise app → Assignment required + група).
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

## Розгортання на сервері docker (10.10.252.108, Traefik у k3s)

Порти 80/443 на сервері належать Traefik у k3s, тому окремий Nginx і certbot не потрібні.
Застосунок працює як служба systemd на порту 8090, а k3s маршрутизує на нього `merch.vsisvoi.ua`
і видає сертифікат через cert-manager.

Перед початком: DNS-запис `merch.vsisvoi.ua` (CNAME на `docker.vsisvoi.ua`, як у wiki/git/grafana)
і Redirect URI `https://merch.vsisvoi.ua/auth/callback` в App registration.

```bash
sudo apt install -y python3-venv git
sudo useradd --system --home /opt/mbviewer --shell /usr/sbin/nologin mbviewer
sudo git clone https://github.com/mykolalytvynenko/powerBi /opt/mbviewer
sudo python3 -m venv /opt/mbviewer/venv
sudo /opt/mbviewer/venv/bin/pip install -r /opt/mbviewer/viewer/requirements.txt

sudo mkdir -p /etc/mbviewer
sudo cp /opt/mbviewer/viewer/.env.example /etc/mbviewer/mbviewer.env
sudo nano /etc/mbviewer/mbviewer.env   # TENANT_ID, CLIENT_ID, CLIENT_SECRET, SESSION_SECRET;
                                       # розкоментувати LISTEN_HOST, LISTEN_PORT, FORWARDED_ALLOW_IPS
sudo chown root:mbviewer /etc/mbviewer/mbviewer.env && sudo chmod 640 /etc/mbviewer/mbviewer.env

sudo cp /opt/mbviewer/viewer/deploy/mbviewer.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now mbviewer
curl http://10.10.252.108:8090/health  # {"status":"ok"}

sudo kubectl apply -f /opt/mbviewer/viewer/deploy/k3s-merch.yaml
sudo kubectl -n mbviewer get ingress,certificate   # дочекатися READY=True у certificate
curl -I https://merch.vsisvoi.ua/health
```

Порт 8090 слухає на адресі сервера без TLS, бо Traefik звертається до нього з мережі подів.
Вхід працює тільки через `https://merch.vsisvoi.ua` (cookie сесії позначена Secure).

## Розгортання на окремому сервері з Nginx

Якщо порти 80/443 вільні: служба лишається на `127.0.0.1:8000` (типові значення), перед нею Nginx.

```bash
sudo apt install -y nginx certbot python3-certbot-nginx
# кроки встановлення ті самі, що вище, без LISTEN_* у mbviewer.env і без kubectl

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
