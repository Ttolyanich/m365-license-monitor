# Microsoft 365 License and User Monitor

Утилита и веб-сервис для автоматического мониторинга пользователей, лицензий и членства в группах в Microsoft 365 (Entra ID).

Система позволяет отслеживать назначение лицензий, ведет лог изменений (diff) за последние 30 дней и высылает регулярные отчеты на электронную почту с прикрепленным Excel-файлом.

---

## Возможности системы

1. **PowerShell-скрипт (`Export-M365UsersInfo.ps1`)**:
   - Автономный скрипт для интеграции с планировщиками (например, Windows Task Scheduler).
   - Оптимизированное кэширование SKU (лицензий) и групп в памяти для ускорения работы на крупных тенантах.
   - Отправка Excel-отчета через SMTP или Microsoft Graph API.

2. **Веб-сервис (FastAPI + SQLite + HTML5/CSS/JS)**:
   - **Авторизация**: Встроенная система защиты сессий по HttpOnly-кукам с поддержкой локального входа (логин/пароль) и бесшовного входа в один клик через Microsoft 365 (SSO OAuth 2.0).
   - **Панель мониторинга (Dashboard)**: Общая статистика (активные лицензии, статус последней выгрузки) и хронология (таймлайн) изменений за 30 дней.
   - **Таблица сотрудников**: Просмотр UPN, имен, почты, статуса аккаунта, выданных лицензий и групп. Фильтрация по кастомным выпадающим спискам в стиле Glassmorphism, умный поиск и кнопка экспорта в Excel.
   - **История синхронизаций**: Лог сессий выполнения с описанием результатов.
   - **Настройки**: Удобная настройка параметров авторизации в Entra ID, почтовых серверов, периодичности синхронизации и частоты отправки Excel-отчетов на почту.
   - **Красивый интерфейс**: Премиальный темный дизайн в стиле Glassmorphism (эффект матового стекла), адаптивная верстка и плавные микро-анимации.

---

## Настройка интеграции и получение Tenant ID, Client ID, Client Secret

Для подключения к Microsoft Graph API необходимо зарегистрировать приложение (App Registration) на портале Microsoft Entra ID. Для этого вам понадобятся права администратора (Global Administrator или Application Administrator).

### Шаг 1. Создание (регистрация) приложения
1. Перейдите в [Microsoft Entra ID admin center](https://entra.microsoft.com/) и авторизуйтесь.
2. В левом меню выберите **Identity (Удостоверение)** -> **Applications (Приложения)** -> **App registrations (Регистрация приложений)**.
3. Нажмите кнопку **New registration (Новая регистрация)** вверху страницы.
4. В поле **Name (Имя)** введите название приложения, например: `M365 License Monitor`.
5. В разделе **Supported account types** оставьте первый пункт: **Accounts in this organizational directory only (Single tenant)**.
6. В разделе **Redirect URI**:
   - Выберите тип платформы **Web**.
   - Укажите адрес обратного вызова для входа через Microsoft 365 (SSO):
     `https://<IP-вашего-сервера-или-домен>/api/auth/callback`
     *(Примечание: Microsoft требует использования **HTTPS** для всех Redirect URI, за исключением localhost. См. раздел настройки Nginx ниже)*.
   - Нажмите **Register (Зарегистрировать)** внизу.

### Шаг 2. Копирование Tenant ID и Client ID
После нажатия кнопки "Register" вы попадете на страницу **Overview (Обзор)** созданного приложения.
Скопируйте отсюда два GUID-значения:
* **Application (client) ID** — это ваш будущий `Client ID`.
* **Directory (tenant) ID** — это ваш будущий `Tenant ID`.

### Шаг 3. Создание Client Secret (Секрета приложения)
1. В меню приложения слева выберите раздел **Certificates & secrets (Сертификаты и секреты)**.
2. Перейдите во вкладку **Client secrets (Секреты клиента)** и нажмите кнопку **New client secret (Создать секрет клиента)**.
3. Введите описание (например, `Monitor Key`) и выберите срок действия. Нажмите **Add (Добавить)**.
4. **КРИТИЧЕСКИ ВАЖНО**: Скопируйте строку из столбца **Value (Значение)** (а не ID секрета!). Это значение показывается один единственный раз при создании. Скопированное значение — это ваш `Client Secret`.

### Шаг 4. Настройка разрешений API (API Permissions)
1. В меню приложения слева перейдите в раздел **API permissions (Разрешения API)**.
2. Нажмите кнопку **Add a permission (Добавить разрешение)**.
3. Выберите плитку **Microsoft Graph**.
4. Нажмите на кнопку **Application permissions (Разрешения приложений)** (это важно, именно Application, так как бэкенд и скрипт работают автономно без прямого участия пользователя).
5. В строке поиска найдите и отметьте следующие разрешения:
   - `User.Read.All` (для чтения учетных записей пользователей)
   - `Group.Read.All` (для чтения информации о группах)
   - `Directory.Read.All` (для чтения структуры каталога)
   - `Mail.Send` *(необязательно: отметьте только если будете отправлять письма с отчетами через Microsoft Graph API от имени пользователя)*
6. Нажмите кнопку **Add permissions (Добавить разрешения)** внизу страницы.

### Шаг 5. Предоставление согласия администратора (Admin Consent)
1. Находясь на странице **API permissions**, нажмите кнопку **Grant admin consent for <Название вашей компании>** (Предоставить согласие администратора).
2. В появившемся диалоговом окне нажмите **Yes (Да)**.
3. Убедитесь, что в столбце **Status** для всех добавленных разрешений появились зеленые галочки с надписью **Granted (Предоставлено)**.

---

## Запуск веб-сервиса с помощью Docker Compose

По соображениям безопасности контейнер Docker настроен на привязку порта `8000` строго к локальному интерфейсу `127.0.0.1` (localhost). Это исключает прямой доступ к бэкенду по HTTP в обход защищенного прокси Nginx.

1. Клонируйте репозиторий в каталог `/opt/m365-license-monitor` и перейдите в него:
   ```bash
   git clone https://github.com/Ttolyanich/m365-license-monitor.git /opt/m365-license-monitor
   cd /opt/m365-license-monitor
   ```

2. Запустите контейнер:
   ```bash
   docker compose up -d
   ```

База данных SQLite (`monitor.db`) автоматически сохраняется в локальную папку `./data` внутри каталога проекта.

> **CORS**: фронтенд раздается тем же приложением (same-origin), поэтому дополнительная настройка не нужна. Если фронтенд запускается отдельным дев-сервером, задайте список разрешенных origins через переменную окружения `CORS_ORIGINS` (через запятую, по умолчанию `http://localhost:3000,http://127.0.0.1:3000`).

---

## Настройка веб-сервера Nginx и SSL (HTTPS)

Microsoft Identity Platform требует использования HTTPS для редиректов авторизации (OAuth). Ниже приведена инструкция по настройке Nginx в качестве реверс-прокси с самоподписанным SSL-сертификатом на 10 лет.

### Шаг 1. Выпуск SSL сертификата на 10 лет
Выполните команды на сервере под рутом:
```bash
# Создание папки для ключей
mkdir -p /etc/nginx/ssl

# Генерация самоподписанного ключа и сертификата на 3650 дней (10 лет)
openssl req -x509 -nodes -days 3650 -newkey rsa:2048 \
  -keyout /etc/nginx/ssl/m365-monitor.key \
  -out /etc/nginx/ssl/m365-monitor.crt \
  -subj "/C=RU/ST=KZ/L=Almaty/O=Company/OU=IT/CN=m365-monitor.local"
```
*(Замените `<IP-вашего-сервера-или-домен>` в параметре CN на IP-адрес или доменное имя вашего сервера).*

### Шаг 2. Настройка виртуального хоста Nginx
Создайте конфигурационный файл `/etc/nginx/conf.d/m365-monitor.conf` (или `/etc/nginx/sites-available/m365-monitor`):

```nginx
server {
    listen 80;
    server_name _; # слушать любой входящий хост

    # Автоматический редирект с HTTP на HTTPS
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name _; # слушать любой входящий хост

    ssl_certificate /etc/nginx/ssl/m365-monitor.crt;
    ssl_certificate_key /etc/nginx/ssl/m365-monitor.key;

    # Параметры безопасности SSL/TLS
    ssl_protocols TLSv1.2 TLSv1.3;
    ssl_prefer_server_ciphers on;
    ssl_ciphers 'ECDHE-ECDSA-AES128-GCM-SHA256:ECDHE-RSA-AES128-GCM-SHA256:ECDHE-ECDSA-AES256-GCM-SHA384:ECDHE-RSA-AES256-GCM-SHA384:DHE-RSA-AES128-GCM-SHA256:DHE-RSA-AES256-GCM-SHA384';
    ssl_session_cache shared:SSL:10m;
    ssl_session_timeout 1d;
    ssl_session_tickets off;

    client_max_body_size 50M;

    location / {
        proxy_pass http://127.0.0.1:8000;
        proxy_http_version 1.1;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection 'upgrade';
        proxy_set_header Host $host;
        
        # Передача реальных заголовков протоколов и IP
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        proxy_read_timeout 300s;
        proxy_connect_timeout 75s;
        proxy_send_timeout 300s;
    }
}
```

При использовании `/etc/nginx/sites-available/` не забудьте сделать символическую ссылку в `sites-enabled` и перезапустить Nginx:
```bash
nginx -t
systemctl restart nginx
```

---

## Использование системы

### Вход в веб-интерфейс
* **Локальный вход**: По умолчанию создан суперадминистратор:
  - **Логин**: `admin`
  - **Пароль**: `admin`
  *(После первого входа обязательно измените пароль во вкладке **«Настройки»**).*
* **Вход через Microsoft 365**: Клик по кнопке авторизует вас через учетную запись Entra ID. Для этого пользователь должен находиться внутри вашего тенанта M365. 

### Ограничение круга лиц для авторизации O365
Если вы хотите, чтобы вход через Microsoft 365 был разрешен не всем сотрудникам организации, а только избранным администраторам:
1. Откройте **Microsoft Entra ID** -> **Enterprise applications (Корпоративные приложения)**.
2. Найдите в списке ваше приложение и откройте вкладку **Properties (Свойства)**.
3. Установите флаг **Assignment required? (Требуется назначение?)** в положение **Yes (Да)** и сохраните.
4. Во вкладке **Users and groups (Пользователи и группы)** добавьте только тех сотрудников, которым разрешен вход.

---

## Использование PowerShell скрипта отдельно

Скрипт `Export-M365UsersInfo.ps1` можно запускать автономно (например, через Планировщик задач Windows).

Скрипт автоматически скачивает и устанавливает необходимые модули Graph SDK (`Microsoft.Graph.Authentication`, `Microsoft.Graph.Users.Actions` и др.), а также модуль `ImportExcel` для сборки красивого отчета с автофильтрами.

**Пример запуска с отправкой через SMTP**:
```powershell
powershell -ExecutionPolicy Bypass -File .\Export-M365UsersInfo.ps1 `
  -TenantId "Tenant-ID-из-Entra" `
  -ClientId "Client-ID-приложения" `
  -ClientSecret "Секрет-приложения" `
  -EmailTo "admin@company.com" `
  -EmailFrom "noreply@company.com" `
  -SmtpServer "smtp.company.com" `
  -SmtpPort 587 `
  -UseSmtpAuth `
  -SmtpUser "smtp_username" `
  -SmtpPassword "smtp_password"
```

**Пример запуска с отправкой через MS Graph API** (требуется разрешение `Mail.Send` для приложения):
```powershell
powershell -ExecutionPolicy Bypass -File .\Export-M365UsersInfo.ps1 `
  -TenantId "Tenant-ID-из-Entra" `
  -ClientId "Client-ID-приложения" `
  -ClientSecret "Секрет-приложения" `
  -EmailTo "admin@company.com" `
  -EmailFrom "noreply@company.com" `
  -SendViaGraph `
  -SendFromGraphUser "sender@company.com"
```
