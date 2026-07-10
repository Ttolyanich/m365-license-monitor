# Microsoft 365 License and User Monitor

Утилита и веб-сервис для автоматического мониторинга пользователей, лицензий и членства в группах в Microsoft 365 (Entra ID).

Система позволяет предотвратить утерю информации о назначениях лицензий, ведет лог изменений (diff) за последние 30 дней и высылает регулярные отчеты на электронную почту с прикрепленным Excel-файлом.

---

## Возможности системы

1. **PowerShell-скрипт (`Export-M365UsersInfo.ps1`)**:
   - Автономный скрипт для интеграции с планировщиками (например, Windows Task Scheduler).
   - Оптимизированное кэширование SKU (лицензий) и групп в памяти для ускорения работы на крупных тенантах.
   - Отправка CSV-отчета через SMTP или Microsoft Graph API.

2. **Веб-сервис (FastAPI + SQLite + HTML5/CSS/JS)**:
   - **Панель мониторинга (Dashboard)**: Общая статистика (активные лицензии, статус последней выгрузки) и хронология (таймлайн) изменений за 30 дней.
   - **Таблица сотрудников**: Просмотр UPN, имен, почты, статуса аккаунта, выданных лицензий и групп. Фильтрация и поиск, а также кнопка экспорта в Excel.
   - **История синхронизаций**: Лог сессий выполнения с описанием результатов.
   - **Настройки**: Удобное сохранение параметров авторизации в Azure AD / Entra ID, почтовых серверов и расписания фонового сбора.
   - **Красивый интерфейс**: Премиальный темный дизайн в стиле Glassmorphism (эффект матового стекла), адаптивная верстка и плавные микро-анимации.

---

## Настройка интеграции в Microsoft Entra ID

Для работы скрипта и веб-сервиса необходимо зарегистрировать приложение (App Registration) на портале [Microsoft Entra ID admin center](https://admin.entra.microsoft.com/):

1. Перейдите в **Identity -> Applications -> App registrations -> New registration**.
2. Введите имя приложения и выберите **Single tenant** (или Multi-tenant, если требуется).
3. Перейдите в раздел **API permissions -> Add a permission -> Microsoft Graph -> Application permissions**:
   - `User.Read.All` (Чтение учетных записей)
   - `Group.Read.All` (Чтение групп)
   - `Directory.Read.All` (Чтение каталога)
   - `Mail.Send` *(опционально: требуется только при отправке отчетов через Graph API от имени пользователя)*
4. Нажмите **Grant admin consent** для подтверждения прав администратором.
5. Перейдите в **Certificates & secrets -> New client secret**, создайте и скопируйте секрет приложения.
6. Скопируйте значения **Application (client) ID** и **Directory (tenant) ID** со вкладки Overview.

---

## Способы запуска веб-сервиса

### Способ 1: С помощью Docker (Рекомендуемый)

Благодаря настроенному GitHub Actions, вам **не нужно собирать образ вручную**. Вы можете запустить уже собранный контейнер напрямую из GitHub Container Registry (GHCR).

СУБД SQLite сохраняет базу данных `monitor.db` в каталоге `/app/backend`. Чтобы сохранить настройки и историю изменений при перезапуске контейнера, примонтируйте эту папку на хост-машину.

**Запуск контейнера из реестра GHCR**:
```bash
docker run -d \
  -p 8000:8000 \
  -v /path/to/local/data:/app/backend \
  --name m365-monitor \
  ghcr.io/ttolyanich/m365-license-monitor:latest
```
*(Замените `/path/to/local/data` на реальный локальный путь на сервере для хранения БД).*

---

### Способ 2: Запуск с помощью Python локально

1. Установите необходимые зависимости:
   ```bash
   pip install -r requirements.txt
   ```
   *(На Windows может потребоваться `py -m pip install -r requirements.txt`)*

2. Запустите веб-сервер Uvicorn из корня проекта:
   ```bash
   py -m uvicorn backend.main:app --reload
   ```

3. Откройте в браузере: [http://localhost:8000](http://localhost:8000)

---

## Использование PowerShell скрипта отдельно

Скрипт `Export-M365UsersInfo.ps1` расположен в корне проекта. Для автоматического запуска по расписанию настройте его в планировщике задач Windows.

**Пример команды запуска**:
```powershell
.\Export-M365UsersInfo.ps1 `
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

Для отправки писем через API Graph без SMTP, используйте флаги `-SendViaGraph` и `-SendFromGraphUser "sender@company.com"`.
