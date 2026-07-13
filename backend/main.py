import os
import io
import sys
import asyncio
from datetime import datetime, timedelta
import secrets
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, Query, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, RedirectResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.orm import Session
import httpx
import pandas as pd
# Добавляем текущую директорию в sys.path для корректного импорта модулей
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from database import init_db, get_db, Config, SyncHistory, UserSnapshot, DiffLog, User, SessionToken, hash_password, verify_password, JiraUserSnapshot, JiraDiffLog
from jira_client import JiraClient
import json
# Initialize database
init_db()
app = FastAPI(title="M365 License and User Monitor API")
# Enable CORS for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# Active sync lock to prevent concurrent sync runs
sync_lock = asyncio.Lock()
current_sync_task = None
# -------------------------------------------------------------
# Authentication Dependency
# -------------------------------------------------------------
async def get_current_user(request: Request, db: Session = Depends(get_db)) -> User:
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Не авторизован")
    session = db.query(SessionToken).filter(
        SessionToken.token == token,
        SessionToken.expires_at > datetime.utcnow()
    ).first()
    if not session:
        raise HTTPException(status_code=401, detail="Сессия недействительна")
    user = db.query(User).filter(User.id == session.user_id).first()
    if not user:
        raise HTTPException(status_code=401, detail="Пользователь не найден")
    return user
# -------------------------------------------------------------
# Microsoft Graph Client Helper
# -------------------------------------------------------------
class GraphClient:
    def __init__(self, tenant_id: str, client_id: str, client_secret: str):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.access_token = None
    async def authenticate(self):
        url = f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token"
        data = {
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "scope": "https://graph.microsoft.com/.default",
            "grant_type": "client_credentials"
        }
        async with httpx.AsyncClient() as client:
            r = await client.post(url, data=data, timeout=10.0)
            if r.status_code != 200:
                raise Exception(f"OAuth failed: {r.text}")
            self.access_token = r.json()["access_token"]
    async def get_headers(self):
        if not self.access_token:
            await self.authenticate()
        return {"Authorization": f"Bearer {self.access_token}"}
    async def get_all_pages(self, start_url: str):
        headers = await self.get_headers()
        results = []
        url = start_url
        async with httpx.AsyncClient() as client:
            while url:
                r = await client.get(url, headers=headers, timeout=30.0)
                if r.status_code != 200:
                    raise Exception(f"Graph API error: {r.text}")
                data = r.json()
                results.extend(data.get("value", []))
                url = data.get("@odata.nextLink")
        return results
    async def send_graph_email(self, send_from: str, to_email: str, subject: str, body: str, attachment_path: Optional[str] = None):
        url = f"https://graph.microsoft.com/v1.0/users/{send_from}/sendMail"
        headers = await self.get_headers()
        message = {
            "subject": subject,
            "body": {
                "contentType": "Text",
                "content": body
            },
            "toRecipients": [
                {
                    "emailAddress": {
                        "address": to_email
                    }
                }
            ]
        }
        if attachment_path:
            filename = os.path.basename(attachment_path)
            with open(attachment_path, "rb") as f:
                content_bytes = f.read()
            import base64
            content_base64 = base64.b64encode(content_bytes).decode("utf-8")
            message["attachments"] = [
                {
                    "@odata.type": "#microsoft.graph.fileAttachment",
                    "name": filename,
                    "contentType": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    "contentBytes": content_base64
                }
            ]
        async with httpx.AsyncClient() as client:
            r = await client.post(url, json={"message": message, "saveToSentItems": "true"}, headers=headers, timeout=15.0)
            if r.status_code not in (200, 202):
                raise Exception(f"Send mail via Graph failed: {r.text}")
# -------------------------------------------------------------
# SMTP Email Helper
# -------------------------------------------------------------
def send_smtp_email(config: Config, subject: str, body: str, attachment_path: Optional[str] = None):
    import smtplib
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from email.mime.base import MIMEBase
    from email import encoders
    msg = MIMEMultipart()
    msg['From'] = config.email_from
    msg['To'] = config.email_to
    msg['Subject'] = subject
    msg.attach(MIMEText(body, 'plain'))
    if attachment_path:
        filename = os.path.basename(attachment_path)
        with open(attachment_path, "rb") as attachment:
            part = MIMEBase('application', 'octet-stream')
            part.set_payload(attachment.read())
            encoders.encode_base64(part)
            part.add_header('Content-Disposition', f"attachment; filename= {filename}")
            msg.attach(part)
    server = smtplib.SMTP(config.smtp_server, config.smtp_port, timeout=15)
    server.starttls()
    if config.use_smtp_auth:
        server.login(config.smtp_user, config.smtp_password)
    server.sendmail(config.email_from, config.email_to, msg.as_string())
    server.quit()
# -------------------------------------------------------------
# Report Generator
# -------------------------------------------------------------
def generate_excel_report(users, jira_users=None):
    if jira_users is None:
        jira_users = []
    data = []
    for u in users:
        data.append({
            "User Principal Name": u.user_principal_name,
            "Display Name": u.display_name,
            "Email": u.mail or "",
            "Account Enabled": "🟢" if u.account_enabled else "🔴",
            "Licenses": u.licenses,
            "Groups": u.groups
        })
    df = pd.DataFrame(data) if data else pd.DataFrame(columns=["User Principal Name", "Display Name", "Email", "Account Enabled", "Licenses", "Groups"])
    data_jira = []
    for u in jira_users:
        data_jira.append({
            "Display Name": u.display_name,
            "Email": u.email,
            "Account Active": "🟢" if u.active else "🔴",
            "Product Access": u.applications,
            "Groups": u.groups,
            "Project Roles": u.project_roles
        })
    df_jira = pd.DataFrame(data_jira) if data_jira else pd.DataFrame(columns=["Display Name", "Email", "Account Active", "Product Access", "Groups", "Project Roles"])
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df.to_excel(writer, sheet_name="M365 Users", index=False)
        worksheet = writer.sheets["M365 Users"]
        for col in worksheet.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            worksheet.column_dimensions[col_letter].width = max(max_len + 3, 12)
        df_jira.to_excel(writer, sheet_name="Jira Users", index=False)
        worksheet_jira = writer.sheets["Jira Users"]
        for col in worksheet_jira.columns:
            max_len = max(len(str(cell.value or '')) for cell in col)
            col_letter = col[0].column_letter
            worksheet_jira.column_dimensions[col_letter].width = max(max_len + 3, 12)
    output.seek(0)
    return output
# -------------------------------------------------------------
# Sync logic
# -------------------------------------------------------------
def cleanup_retention(db: Session):
    from datetime import timedelta
    limit_date = datetime.utcnow() - timedelta(days=30)
    old_syncs = db.query(SyncHistory).filter(SyncHistory.timestamp < limit_date).all()
    for s in old_syncs:
        db.delete(s)
    db.commit()
async def send_sync_report_email(config: Config, sync_run: SyncHistory, current_snapshots, diffs, jira_snapshots=None, jira_diffs=None):
    if jira_snapshots is None:
        jira_snapshots = []
    if jira_diffs is None:
        jira_diffs = []
    diff_text = ""
    if diffs:
        diff_text = "Изменения M365 за эту синхронизацию:\n"
        for d in diffs:
            icon = "🟢" if d.change_type == "added" else "🔴" if d.change_type == "removed" else "🟡"
            diff_text += f"{icon} [{d.change_type.upper()}] {d.display_name} ({d.user_principal_name}): {d.details}\n"
    else:
        diff_text = "Изменений M365 не обнаружено.\n"
    jira_diff_text = ""
    if jira_diffs:
        jira_diff_text = "\nИзменения Jira за эту синхронизацию:\n"
        for d in jira_diffs:
            icon = "🟢" if d.change_type == "added" else "🔴" if d.change_type == "removed" else "🟡"
            jira_diff_text += f"{icon} [{d.change_type.upper()}] {d.display_name} ({d.email}): {d.details}\n"
    elif config.jira_sync_enabled:
        jira_diff_text = "\nИзменений Jira не обнаружено.\n"
    subject = f"Отчет M365 & Jira: Синхронизация {sync_run.timestamp.strftime('%d.%m.%Y %H:%M')}"
    body = f"""Синхронизация завершена со статусом: {sync_run.status.upper()}
Всего пользователей M365: {sync_run.users_count}
{f'Всего пользователей Jira: {len(jira_snapshots)}' if config.jira_sync_enabled else ''}

{diff_text}
{jira_diff_text}

Полный отчет находится во вложении (Excel файл).
"""
    excel_buf = generate_excel_report(current_snapshots, jira_snapshots)
    temp_path = f"M365_Report_{sync_run.timestamp.strftime('%Y%m%d_%H%M%S')}.xlsx"
    with open(temp_path, "wb") as f:
        f.write(excel_buf.read())
    try:
        if config.send_via_graph:
            client = GraphClient(config.tenant_id, config.client_id, config.client_secret)
            await client.send_graph_email(
                send_from=config.send_from_graph_user,
                to_email=config.email_to,
                subject=subject,
                body=body,
                attachment_path=temp_path
            )
        else:
            send_smtp_email(config, subject, body, attachment_path=temp_path)
    except Exception as e:
        print(f"Failed to send email: {e}")
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
async def run_jira_sync_logic(db_session: Session, config: Config, sync_run: SyncHistory):
    client = JiraClient(config.jira_url, config.jira_username, config.jira_api_token)
    sync_run.progress = 55
    sync_run.message = "Jira: Получение списка пользователей..."
    db_session.commit()
    users_data = await client.fetch_users()
    sync_run.progress = 65
    sync_run.message = "Jira: Получение групп доступа..."
    db_session.commit()
    async def get_groups(u):
        u["_groups"] = await client.fetch_user_groups(u["accountId"])
    await asyncio.gather(*(get_groups(u) for u in users_data))
    sync_run.progress = 75
    sync_run.message = "Jira: Получение ролей проектов..."
    db_session.commit()
    roles_data = await client.fetch_projects_and_roles()
    user_roles_map = roles_data.get("users", {})
    group_roles_map = roles_data.get("groups", {})
    sync_run.progress = 90 if not config.jira_sync_enabled else 45
    sync_run.message = "Jira: Анализ изменений..."
    db_session.commit()
    prev_sync = db_session.query(SyncHistory).filter(SyncHistory.status == "success").order_by(SyncHistory.timestamp.desc()).first()
    prev_snapshots = {}
    if prev_sync:
        prev_snapshots = {s.account_id: s for s in db_session.query(JiraUserSnapshot).filter(JiraUserSnapshot.sync_id == prev_sync.id).all()}
    current_snapshots = []
    diffs = []
    for u in users_data:
        acc_id = u["accountId"]
        email = u.get("emailAddress", "").lower() if u.get("emailAddress") else ""
        disp_name = u.get("displayName", "")
        active = u.get("active", True)
        groups_list = u.get("_groups", [])
        apps = []
        for g in groups_list:
            g_lower = g.lower()
            if "jira-software" in g_lower:
                apps.append("Jira Software")
            elif "confluence" in g_lower:
                apps.append("Confluence")
            elif "jira-servicedesk" in g_lower or "jira-service-management" in g_lower:
                apps.append("Jira Service Management")
            elif "bitbucket" in g_lower:
                apps.append("Bitbucket")
        apps = list(set(apps))
        user_roles = user_roles_map.get(acc_id, {})
        for g in groups_list:
            g_roles = group_roles_map.get(g, {})
            for proj, roles in g_roles.items():
                if proj not in user_roles:
                    user_roles[proj] = []
                for r in roles:
                    if r not in user_roles[proj]:
                        user_roles[proj].append(r)
        groups_str = ",".join(groups_list)
        apps_str = ",".join(apps)
        roles_json = json.dumps(user_roles)
        snapshot = JiraUserSnapshot(
            sync_id=sync_run.id,
            account_id=acc_id,
            email=email,
            display_name=disp_name,
            active=active,
            groups=groups_str,
            applications=apps_str,
            project_roles=roles_json
        )
        current_snapshots.append(snapshot)
        if acc_id in prev_snapshots:
            prev = prev_snapshots[acc_id]
            details = []
            if prev.active != active:
                status_str = "активирован" if active else "деактивирован"
                details.append(f"Статус аккаунта изменен: {status_str}")
            prev_groups = set(prev.groups.split(",")) if prev.groups else set()
            curr_groups = set(groups_list)
            added_g = curr_groups - prev_groups
            removed_g = prev_groups - curr_groups
            if added_g:
                details.append(f"Добавлен в группы: {', '.join(added_g)}")
            if removed_g:
                details.append(f"Удален из групп: {', '.join(removed_g)}")
            prev_apps = set(prev.applications.split(",")) if prev.applications else set()
            curr_apps = set(apps)
            added_a = curr_apps - prev_apps
            removed_a = prev_apps - curr_apps
            if added_a:
                details.append(f"Добавлен доступ к продуктам: {', '.join(added_a)}")
            if removed_a:
                details.append(f"Удален доступ к продуктам: {', '.join(removed_a)}")
            prev_roles = json.loads(prev.project_roles) if prev.project_roles else {}
            if prev_roles != user_roles:
                details.append("Изменены проектные роли")
            if details:
                diffs.append(JiraDiffLog(
                    sync_id=sync_run.id,
                    email=email,
                    display_name=disp_name,
                    change_type="modified",
                    details="; ".join(details)
                ))
        else:
            diffs.append(JiraDiffLog(
                sync_id=sync_run.id,
                email=email,
                display_name=disp_name,
                change_type="added",
                details="Добавлен новый аккаунт Jira."
            ))
    for acc_id, prev in prev_snapshots.items():
        if not any(u["accountId"] == acc_id for u in users_data):
            diffs.append(JiraDiffLog(
                sync_id=sync_run.id,
                email=prev.email,
                display_name=prev.display_name,
                change_type="removed",
                details="Учетная запись Jira удалена."
            ))
    sync_run.progress = 92
    sync_run.message = "Jira: Сохранение результатов..."
    db_session.commit()
    db_session.add_all(current_snapshots)
    db_session.add_all(diffs)
    db_session.commit()
    return current_snapshots, diffs
async def run_sync_logic(db_session: Session, config: Config):
    async with sync_lock:
        sync_run = SyncHistory(timestamp=datetime.utcnow(), status="running", message="Синхронизация запущена...")
        db_session.add(sync_run)
        db_session.commit()
        db_session.refresh(sync_run)
        try:
            # 1. Connect and Authenticate
            client = GraphClient(config.tenant_id, config.client_id, config.client_secret)
            await client.authenticate()
            # 2. Get SKUs
            sync_run.progress = 25 if not config.jira_sync_enabled else 12
            sync_run.message = "Получение списка лицензий (SKU)..."
            db_session.commit()
            skus_data = await client.get_all_pages("https://graph.microsoft.com/v1.0/subscribedSkus")
            sku_map = {s["skuId"]: s["skuPartNumber"] for s in skus_data if "skuId" in s}
            # 3. Get Groups and member lists
            sync_run.progress = 40 if not config.jira_sync_enabled else 20
            sync_run.message = "Получение списка групп..."
            db_session.commit()
            groups_data = await client.get_all_pages("https://graph.microsoft.com/v1.0/groups?$select=id,displayName")
            user_groups_map = {}
            # Fetch members for each group
            for idx, g in enumerate(groups_data):
                group_id = g["id"]
                group_name = g["displayName"]
                if not config.jira_sync_enabled:
                    current_p = 45 + int((idx / len(groups_data)) * 30) if groups_data else 45
                else:
                    current_p = 20 + int((idx / len(groups_data)) * 15) if groups_data else 20
                sync_run.progress = current_p
                sync_run.message = f"Получение участников группы {idx+1}/{len(groups_data)}: {group_name}..."
                db_session.commit()
                try:
                    members = await client.get_all_pages(f"https://graph.microsoft.com/v1.0/groups/{group_id}/members?$select=id")
                    for member in members:
                        m_id = member.get("id")
                        if m_id:
                            if m_id not in user_groups_map:
                                user_groups_map[m_id] = []
                            user_groups_map[m_id].append(group_name)
                except Exception:
                    pass # Ignore group reading failures (e.g. system groups)
            # 4. Get Users
            sync_run.progress = 80 if not config.jira_sync_enabled else 40
            sync_run.message = "Получение учетных записей пользователей..."
            db_session.commit()
            users_data = await client.get_all_pages("https://graph.microsoft.com/v1.0/users?$select=id,userPrincipalName,displayName,mail,accountEnabled,assignedLicenses")
            # Find previous successful sync run
            prev_sync = db_session.query(SyncHistory).filter(SyncHistory.status == "success").order_by(SyncHistory.timestamp.desc()).first()
            prev_snapshots = {}
            if prev_sync:
                prev_snapshots = {s.user_id: s for s in db_session.query(UserSnapshot).filter(UserSnapshot.sync_id == prev_sync.id).all()}
            current_snapshots = []
            diffs = []
            for u in users_data:
                user_id = u["id"]
                upn = u["userPrincipalName"]
                disp_name = u.get("displayName") or ""
                mail = u.get("mail") or ""
                enabled = u.get("accountEnabled", True)
                # Sku mapping
                lics = []
                for lic in u.get("assignedLicenses", []):
                    sku_id = lic.get("skuId")
                    if sku_id:
                        lics.append(sku_map.get(sku_id, sku_id))
                lic_str = ", ".join(lics)
                # Groups mapping
                grps = user_groups_map.get(user_id, [])
                grp_str = ", ".join(grps)
                snap = UserSnapshot(
                    sync_id=sync_run.id,
                    user_id=user_id,
                    user_principal_name=upn,
                    display_name=disp_name,
                    mail=mail,
                    account_enabled=enabled,
                    licenses=lic_str,
                    groups=grp_str
                )
                current_snapshots.append(snap)
                # Compare
                if prev_sync:
                    if user_id not in prev_snapshots:
                        diffs.append(DiffLog(
                            sync_id=sync_run.id,
                            user_principal_name=upn,
                            display_name=disp_name,
                            change_type="added",
                            details=f"Пользователь добавлен. Лицензии: [{lic_str}]. Группы: [{grp_str}]"
                        ))
                    else:
                        prev_snap = prev_snapshots[user_id]
                        changes = []
                        # Compare licenses
                        p_lics = set(x.strip() for x in prev_snap.licenses.split(",") if x.strip())
                        c_lics = set(x.strip() for x in lic_str.split(",") if x.strip())
                        added_lic = c_lics - p_lics
                        rem_lic = p_lics - c_lics
                        if added_lic:
                            changes.append(f"выдана лицензия: {', '.join(added_lic)}")
                        if rem_lic:
                            changes.append(f"отозвана лицензия: {', '.join(rem_lic)}")
                        # Compare groups
                        p_grps = set(x.strip() for x in prev_snap.groups.split(",") if x.strip())
                        c_grps = set(x.strip() for x in grp_str.split(",") if x.strip())
                        added_grp = c_grps - p_grps
                        rem_grp = p_grps - c_grps
                        if added_grp:
                            changes.append(f"добавлен в группы: {', '.join(added_grp)}")
                        if rem_grp:
                            changes.append(f"удален из групп: {', '.join(rem_grp)}")
                        # Other attributes
                        if prev_snap.account_enabled != enabled:
                            changes.append(f"статус учетной записи изменен на {'Активен' if enabled else 'Отключен'}")
                        if prev_snap.display_name != disp_name:
                            changes.append(f"имя изменено с '{prev_snap.display_name}' на '{disp_name}'")
                        if changes:
                            diffs.append(DiffLog(
                                sync_id=sync_run.id,
                                user_principal_name=upn,
                                display_name=disp_name,
                                change_type="modified",
                                details="; ".join(changes)
                            ))
            # Check for deleted users
            if prev_sync:
                curr_user_ids = {u["id"] for u in users_data}
                for p_id, p_snap in prev_snapshots.items():
                    if p_id not in curr_user_ids:
                        diffs.append(DiffLog(
                            sync_id=sync_run.id,
                            user_principal_name=p_snap.user_principal_name,
                            display_name=p_snap.display_name,
                            change_type="removed",
                            details=f"Пользователь удален. Ранее имел лицензии: [{p_snap.licenses}] и группы: [{p_snap.groups}]"
                        ))
            sync_run.progress = 95 if not config.jira_sync_enabled else 48
            sync_run.message = "Сохранение результатов M365..."
            db_session.commit()
            db_session.add_all(current_snapshots)
            db_session.add_all(diffs)
            db_session.commit()
            jira_snapshots = []
            jira_diffs = []
            if config.jira_sync_enabled:
                jira_snapshots, jira_diffs = await run_jira_sync_logic(db_session, config, sync_run)
            sync_run.status = "success"
            sync_run.message = "Синхронизация завершена успешно."
            sync_run.users_count = len(users_data)
            sync_run.progress = 100
            db_session.commit()
            cleanup_retention(db_session)
            if config.jira_sync_enabled:
                limit_date = datetime.utcnow() - timedelta(days=30)
                old_sync_ids = [s.id for s in db_session.query(SyncHistory).filter(SyncHistory.timestamp < limit_date).all()]
                if old_sync_ids:
                    db_session.query(JiraUserSnapshot).filter(JiraUserSnapshot.sync_id.in_(old_sync_ids)).delete(synchronize_session=False)
                    db_session.query(JiraDiffLog).filter(JiraDiffLog.sync_id.in_(old_sync_ids)).delete(synchronize_session=False)
                    db_session.commit()
            should_send_email = False
            freq = config.email_report_frequency or "sync"
            if freq == "sync":
                should_send_email = True
            elif freq == "disabled":
                should_send_email = False
            else:
                now = datetime.utcnow()
                if not config.last_email_sent:
                    should_send_email = True
                else:
                    delta = now - config.last_email_sent
                    if freq == "daily" and delta.total_seconds() >= 24 * 3600:
                        should_send_email = True
                    elif freq == "weekly" and delta.total_seconds() >= 7 * 24 * 3600:
                        should_send_email = True
                    elif freq == "monthly" and delta.total_seconds() >= 30 * 24 * 3600:
                        should_send_email = True
            if should_send_email:
                await send_sync_report_email(config, sync_run, current_snapshots, diffs, jira_snapshots, jira_diffs)
                config.last_email_sent = datetime.utcnow()
                db_session.commit()
        except Exception as e:
            import traceback
            sync_run.status = "failed"
            sync_run.message = f"Ошибка: {str(e)}\n{traceback.format_exc()}"
            db_session.commit()
# -------------------------------------------------------------
# Authentication Endpoints (Public)
# -------------------------------------------------------------
@app.post("/api/auth/login")
def login(login_data: dict, response: Response, db: Session = Depends(get_db)):
    username = login_data.get("username", "")
    password = login_data.get("password", "")
    user = db.query(User).filter(User.username == username).first()
    if not user or not verify_password(password, user.password_hash):
        raise HTTPException(status_code=400, detail="Неверное имя пользователя или пароль")
    token_str = secrets.token_hex(32)
    session = SessionToken(
        token=token_str,
        user_id=user.id,
        expires_at=datetime.utcnow() + timedelta(days=7)
    )
    db.add(session)
    db.commit()
    response.set_cookie(
        key="session_token",
        value=token_str,
        httponly=True,
        samesite="lax",
        max_age=7 * 24 * 3600,
        secure=False  # Set True if HTTPS is configured
    )
    return {"status": "success", "username": user.username}
@app.post("/api/auth/logout")
def logout(request: Request, response: Response, db: Session = Depends(get_db)):
    token = request.cookies.get("session_token")
    if token:
        db.query(SessionToken).filter(SessionToken.token == token).delete()
        db.commit()
    response.delete_cookie("session_token")
    return {"status": "success"}
@app.get("/api/auth/me")
def get_me(current_user: User = Depends(get_current_user)):
    return {
        "username": current_user.username,
        "email": current_user.email,
        "auth_provider": current_user.auth_provider
    }
@app.post("/api/auth/change-password")
def change_password(data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    old_password = data.get("current_password", "")
    new_password = data.get("new_password", "")
    if current_user.auth_provider != "local":
        raise HTTPException(status_code=400, detail="Смена пароля поддерживается только для локальных учетных записей.")
    if not verify_password(old_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Неверный текущий пароль.")
    if len(new_password) < 4:
        raise HTTPException(status_code=400, detail="Новый пароль должен содержать минимум 4 символа.")
    current_user.password_hash = hash_password(new_password)
    db.commit()
    return {"status": "success", "message": "Пароль успешно изменен."}
@app.get("/api/auth/microsoft")
def microsoft_login(request: Request, db: Session = Depends(get_db)):
    config = db.query(Config).first()
    if not config or not config.tenant_id or not config.client_id:
        raise HTTPException(status_code=400, detail="M365 integration is not configured in settings.")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    redirect_uri = f"{proto}://{request.url.netloc}/api/auth/callback"
    state = secrets.token_hex(16)
    microsoft_url = (
        f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/v2.0/authorize"
        f"?client_id={config.client_id}"
        f"&response_type=code"
        f"&redirect_uri={redirect_uri}"
        f"&response_mode=query"
        f"&scope=openid profile email User.Read"
        f"&state={state}"
    )
    return {"url": microsoft_url}
@app.get("/api/auth/callback")
async def microsoft_callback(request: Request, response: Response, code: str, state: str = None, db: Session = Depends(get_db)):
    config = db.query(Config).first()
    if not config or not config.tenant_id or not config.client_id or not config.client_secret:
        raise HTTPException(status_code=400, detail="M365 integration is not configured in settings.")
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    redirect_uri = f"{proto}://{request.url.netloc}/api/auth/callback"
    # Exchange code for token
    token_url = f"https://login.microsoftonline.com/{config.tenant_id}/oauth2/v2.0/token"
    data = {
        "client_id": config.client_id,
        "client_secret": config.client_secret,
        "code": code,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code"
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(token_url, data=data)
        if r.status_code != 200:
            return HTMLResponse(content=f"<h3>Authentication failed:</h3><pre>{r.text}</pre>", status_code=400)
        token_data = r.json()
        access_token = token_data["access_token"]
        # Get user info
        me_headers = {"Authorization": f"Bearer {access_token}"}
        r_me = await client.get("https://graph.microsoft.com/v1.0/me", headers=me_headers)
        if r_me.status_code != 200:
            return HTMLResponse(content=f"<h3>Failed to fetch user profile:</h3><pre>{r_me.text}</pre>", status_code=400)
        me_data = r_me.json()
        upn = me_data["userPrincipalName"]
        display_name = me_data.get("displayName", upn)
        mail = me_data.get("mail") or upn
        # Find or create user
        user = db.query(User).filter(User.username == upn).first()
        if not user:
            user = User(
                username=upn,
                password_hash=hash_password(secrets.token_hex(16)),  # random password for OAuth user
                email=mail,
                auth_provider="microsoft"
            )
            db.add(user)
            db.commit()
            db.refresh(user)
        # Create local session
        token_str = secrets.token_hex(32)
        session = SessionToken(
            token=token_str,
            user_id=user.id,
            expires_at=datetime.utcnow() + timedelta(days=7)
        )
        db.add(session)
        db.commit()
        # Redirect back to home
        redir = RedirectResponse(url="/")
        redir.set_cookie(
            key="session_token",
            value=token_str,
            httponly=True,
            samesite="lax",
            max_age=7 * 24 * 3600,
            secure=False
        )
        return redir
# -------------------------------------------------------------
# Protected API Endpoints
# -------------------------------------------------------------
@app.get("/api/config")
def get_config(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    config = db.query(Config).first()
    return config
@app.post("/api/config")
def update_config(config_data: dict, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    config = db.query(Config).first()
    if not config:
        config = Config()
        db.add(config)
    config.tenant_id = config_data.get("tenant_id", "")
    config.client_id = config_data.get("client_id", "")
    config.client_secret = config_data.get("client_secret", "")
    config.email_to = config_data.get("email_to", "")
    config.email_from = config_data.get("email_from", "")
    config.smtp_server = config_data.get("smtp_server", "")
    config.smtp_port = int(config_data.get("smtp_port", 587))
    config.use_smtp_auth = bool(config_data.get("use_smtp_auth", False))
    config.smtp_user = config_data.get("smtp_user", "")
    config.smtp_password = config_data.get("smtp_password", "")
    config.send_via_graph = bool(config_data.get("send_via_graph", False))
    config.send_from_graph_user = config_data.get("send_from_graph_user", "")
    config.auto_sync_enabled = bool(config_data.get("auto_sync_enabled", False))
    config.sync_interval_hours = int(config_data.get("sync_interval_hours", 24))
    config.email_report_frequency = config_data.get("email_report_frequency", "sync")
    config.jira_url = config_data.get("jira_url", "")
    config.jira_username = config_data.get("jira_username", "")
    config.jira_api_token = config_data.get("jira_api_token", "")
    config.jira_sync_enabled = bool(config_data.get("jira_sync_enabled", False))
    db.commit()
    return {"status": "success", "message": "Настройки сохранены."}
@app.get("/api/dashboard")
def get_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    last_sync = db.query(SyncHistory).order_by(SyncHistory.timestamp.desc()).first()
    total_users = 0
    active_licenses = {}
    last_sync_status = "Никогда"
    last_sync_time = None
    if last_sync and last_sync.status == "success":
        total_users = last_sync.users_count
        last_sync_status = "Успешно"
        last_sync_time = last_sync.timestamp
        # Count licenses
        snapshots = db.query(UserSnapshot).filter(UserSnapshot.sync_id == last_sync.id).all()
        for s in snapshots:
            if s.licenses:
                for lic in s.licenses.split(","):
                    lic_name = lic.strip()
                    if lic_name:
                        active_licenses[lic_name] = active_licenses.get(lic_name, 0) + 1
    elif last_sync:
        last_sync_status = "Ошибка"
        last_sync_time = last_sync.timestamp
    recent_diffs = db.query(DiffLog).order_by(DiffLog.timestamp.desc()).limit(50).all()
    return {
        "total_users": total_users,
        "active_licenses": active_licenses,
        "last_sync_status": last_sync_status,
        "last_sync_time": last_sync_time.strftime("%Y-%m-%dT%H:%M:%SZ") if last_sync_time else None,
        "recent_diffs": [
            {
                "id": d.id,
                "timestamp": d.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ") if d.timestamp else None,
                "user_principal_name": d.user_principal_name,
                "display_name": d.display_name,
                "change_type": d.change_type,
                "details": d.details
            }
            for d in recent_diffs
        ]
    }
@app.get("/api/users")
def get_users(
    page: int = 1,
    limit: int = 50,
    search: Optional[str] = None,
    group: Optional[str] = None,
    license: Optional[str] = None,
    show_deactivated: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    last_success_sync = db.query(SyncHistory).filter(SyncHistory.status == "success").order_by(SyncHistory.timestamp.desc()).first()
    if not last_success_sync:
        return {"users": [], "total": 0, "page": page, "limit": limit}
    query = db.query(UserSnapshot).filter(UserSnapshot.sync_id == last_success_sync.id)
    if not show_deactivated:
        query = query.filter(UserSnapshot.account_enabled == True)
    if search:
        query = query.filter(
            (UserSnapshot.user_principal_name.like(f"%{search}%")) |
            (UserSnapshot.display_name.like(f"%{search}%")) |
            (UserSnapshot.mail.like(f"%{search}%"))
        )
    if group:
        query = query.filter(UserSnapshot.groups.like(f"%{group}%"))
    if license:
        query = query.filter(UserSnapshot.licenses.like(f"%{license}%"))
    total = query.count()
    users = query.offset((page - 1) * limit).limit(limit).all()
    return {
        "users": [
            {
                "user_principal_name": u.user_principal_name,
                "display_name": u.display_name,
                "mail": u.mail,
                "account_enabled": u.account_enabled,
                "licenses": u.licenses,
                "groups": u.groups
            }
            for u in users
        ],
        "total": total,
        "page": page,
        "limit": limit
    }
@app.post("/api/sync")
def trigger_sync(background_tasks: BackgroundTasks, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if sync_lock.locked():
        raise HTTPException(status_code=400, detail="Синхронизация уже выполняется.")
    config = db.query(Config).first()
    if not config or not config.tenant_id or not config.client_id or not config.client_secret:
        raise HTTPException(status_code=400, detail="Пожалуйста, сначала заполните настройки подключения к M365.")
    background_tasks.add_task(run_sync_logic, db, config)
    return {"status": "started", "message": "Синхронизация запущена в фоновом режиме."}
@app.get("/api/syncs")
def get_syncs(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    syncs = db.query(SyncHistory).order_by(SyncHistory.timestamp.desc()).limit(20).all()
    return [
        {
            "id": s.id,
            "timestamp": s.timestamp.strftime("%Y-%m-%dT%H:%M:%SZ") if s.timestamp else None,
            "status": s.status,
            "message": s.message,
            "users_count": s.users_count
        } for s in syncs
    ]
@app.get("/api/export")
def export_excel(sync_id: Optional[int] = None, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    if sync_id:
        sync_run = db.query(SyncHistory).filter(SyncHistory.id == sync_id).first()
    else:
        sync_run = db.query(SyncHistory).filter(SyncHistory.status == "success").order_by(SyncHistory.timestamp.desc()).first()
    if not sync_run:
        raise HTTPException(status_code=404, detail="Отчеты не найдены. Сначала запустите синхронизацию.")
    users = db.query(UserSnapshot).filter(UserSnapshot.sync_id == sync_run.id).all()
    config = db.query(Config).first()
    jira_users = []
    if config and config.jira_sync_enabled:
        jira_users = db.query(JiraUserSnapshot).filter(JiraUserSnapshot.sync_id == sync_run.id).all()
    excel_buf = generate_excel_report(users, jira_users)
    filename = f"M365_Export_{sync_run.timestamp.strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        excel_buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

@app.get("/api/jira/dashboard")
def get_jira_dashboard(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    last_success_sync = db.query(SyncHistory).filter(SyncHistory.status == "success").order_by(SyncHistory.timestamp.desc()).first()
    stats = {
        "total_users": 0,
        "active_users": 0,
        "jira_software": 0,
        "confluence": 0,
        "bitbucket": 0,
        "recent_diffs": []
    }
    if last_success_sync:
        stats["total_users"] = db.query(JiraUserSnapshot).filter(JiraUserSnapshot.sync_id == last_success_sync.id).count()
        stats["active_users"] = db.query(JiraUserSnapshot).filter(JiraUserSnapshot.sync_id == last_success_sync.id, JiraUserSnapshot.active == True).count()
        stats["jira_software"] = db.query(JiraUserSnapshot).filter(JiraUserSnapshot.sync_id == last_success_sync.id, JiraUserSnapshot.applications.like("%Jira Software%")).count()
        stats["confluence"] = db.query(JiraUserSnapshot).filter(JiraUserSnapshot.sync_id == last_success_sync.id, JiraUserSnapshot.applications.like("%Confluence%")).count()
        stats["bitbucket"] = db.query(JiraUserSnapshot).filter(JiraUserSnapshot.sync_id == last_success_sync.id, JiraUserSnapshot.applications.like("%Bitbucket%")).count()
    recent_diffs = db.query(JiraDiffLog).order_by(JiraDiffLog.timestamp.desc()).limit(20).all()
    stats["recent_diffs"] = [
        {
            "id": d.id,
            "timestamp": d.timestamp.isoformat(),
            "email": d.email,
            "display_name": d.display_name,
            "change_type": d.change_type,
            "details": d.details
        } for d in recent_diffs
    ]
    return stats

@app.get("/api/jira/users")
def get_jira_users(
    page: int = 1,
    limit: int = 50,
    search: Optional[str] = None,
    group: Optional[str] = None,
    application: Optional[str] = None,
    show_deactivated: bool = False,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    last_success_sync = db.query(SyncHistory).filter(SyncHistory.status == "success").order_by(SyncHistory.timestamp.desc()).first()
    if not last_success_sync:
        return {"users": [], "total": 0, "page": page, "limit": limit}
    query = db.query(JiraUserSnapshot).filter(JiraUserSnapshot.sync_id == last_success_sync.id)
    if not show_deactivated:
        query = query.filter(JiraUserSnapshot.active == True)
    if search:
        query = query.filter(
            (JiraUserSnapshot.email.like(f"%{search}%")) |
            (JiraUserSnapshot.display_name.like(f"%{search}%"))
        )
    if group:
        query = query.filter(JiraUserSnapshot.groups.like(f"%{group}%"))
    if application:
        query = query.filter(JiraUserSnapshot.applications.like(f"%{application}%"))
    total = query.count()
    users = query.offset((page - 1) * limit).limit(limit).all()
    return {
        "users": [
            {
                "id": u.id,
                "email": u.email,
                "display_name": u.display_name,
                "active": u.active,
                "groups": u.groups,
                "applications": u.applications,
                "project_roles": u.project_roles
            } for u in users
        ],
        "total": total,
        "page": page,
        "limit": limit
    }
# -------------------------------------------------------------
# Background Scheduler Loop
# -------------------------------------------------------------
async def auto_sync_worker():
    while True:
        try:
            db = next(get_db())
            config = db.query(Config).first()
            if config and config.auto_sync_enabled and config.tenant_id and config.client_id:
                now = datetime.utcnow()
                should_sync = False
                if not config.last_auto_sync:
                    should_sync = True
                else:
                    delta = now - config.last_auto_sync
                    if delta.total_seconds() >= config.sync_interval_hours * 3600:
                        should_sync = True
                if should_sync:
                    print("Auto-sync worker: starting sync...")
                    await run_sync_logic(db, config)
                    config.last_auto_sync = now
                    db.commit()
            db.close()
        except Exception as e:
            print(f"Auto-sync worker error: {e}")
        await asyncio.sleep(300) # Check every 5 minutes
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(auto_sync_worker())
# Serve static frontend files
frontend_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "frontend")
if os.path.exists(frontend_dir):
    app.mount("/", StaticFiles(directory=frontend_dir, html=True), name="frontend")