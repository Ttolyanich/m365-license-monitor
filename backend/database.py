import os
import hashlib
import uuid
from datetime import datetime, timedelta
from sqlalchemy import create_engine, Column, Integer, String, Boolean, DateTime, Text, ForeignKey
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DB_DIR = os.environ.get("DB_DIR", os.path.dirname(os.path.abspath(__file__)))
os.makedirs(DB_DIR, exist_ok=True)
DB_PATH = os.path.join(DB_DIR, "monitor.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Helper functions for password hashing
def hash_password(password: str, salt: str = None) -> str:
    if not salt:
        salt = uuid.uuid4().hex
    pwd_hash = hashlib.sha256((password + salt).encode('utf-8')).hexdigest()
    return f"{salt}:{pwd_hash}"

def verify_password(password: str, stored_password: str) -> bool:
    if not stored_password or ":" not in stored_password:
        return False
    salt, pwd_hash = stored_password.split(":")
    return hash_password(password, salt).split(":")[1] == pwd_hash

class User(Base):
    __tablename__ = "users"
    
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)
    password_hash = Column(String)  # stored as "salt:sha256"
    email = Column(String, nullable=True)
    auth_provider = Column(String, default="local")  # "local" or "microsoft"
    created_at = Column(DateTime, default=datetime.utcnow)

class SessionToken(Base):
    __tablename__ = "session_tokens"
    
    id = Column(Integer, primary_key=True, index=True)
    token = Column(String, unique=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime)

class Config(Base):
    __tablename__ = "configs"
    
    id = Column(Integer, primary_key=True, index=True)
    tenant_id = Column(String, default="")
    client_id = Column(String, default="")
    client_secret = Column(String, default="")
    
    # Email settings
    email_to = Column(String, default="")
    email_from = Column(String, default="")
    smtp_server = Column(String, default="")
    smtp_port = Column(Integer, default=587)
    use_smtp_auth = Column(Boolean, default=False)
    smtp_user = Column(String, default="")
    smtp_password = Column(String, default="")
    
    # Graph sending settings
    send_via_graph = Column(Boolean, default=False)
    send_from_graph_user = Column(String, default="")
    
    # Scheduling settings
    auto_sync_enabled = Column(Boolean, default=False)
    sync_interval_hours = Column(Integer, default=24)
    last_auto_sync = Column(DateTime, nullable=True)
    
    # Email reporting scheduler settings
    email_report_frequency = Column(String, default="sync") # "sync", "daily", "weekly", "monthly", "disabled"
    last_email_sent = Column(DateTime, nullable=True)
    
    # Jira Cloud Integration settings
    jira_url = Column(String, nullable=True)
    jira_username = Column(String, nullable=True)
    jira_api_token = Column(String, nullable=True)
    jira_sync_enabled = Column(Boolean, default=False)

class SyncHistory(Base):
    __tablename__ = "sync_history"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String)  # "success", "failed"
    message = Column(Text, default="")
    users_count = Column(Integer, default=0)
    progress = Column(Integer, default=0)

class UserSnapshot(Base):
    __tablename__ = "user_snapshots"
    
    id = Column(Integer, primary_key=True, index=True)
    sync_id = Column(Integer, ForeignKey("sync_history.id", ondelete="CASCADE"), index=True)
    user_id = Column(String, index=True)  # Graph User ID
    user_principal_name = Column(String, index=True)
    display_name = Column(String)
    mail = Column(String)
    account_enabled = Column(Boolean)
    licenses = Column(Text)  # Comma-separated licenses
    groups = Column(Text)    # Comma-separated groups

class DiffLog(Base):
    __tablename__ = "diff_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    sync_id = Column(Integer, ForeignKey("sync_history.id", ondelete="CASCADE"), index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    user_principal_name = Column(String, index=True)
    display_name = Column(String)
    change_type = Column(String)  # "added", "removed", "modified"
    details = Column(Text)        # Human readable description of changes

class JiraUserSnapshot(Base):
    __tablename__ = "jira_user_snapshots"
    
    id = Column(Integer, primary_key=True, index=True)
    sync_id = Column(Integer, ForeignKey("sync_history.id", ondelete="CASCADE"), index=True)
    account_id = Column(String, index=True)
    email = Column(String, index=True)
    display_name = Column(String)
    active = Column(Boolean, default=True)
    groups = Column(Text)  # Comma-separated group names
    applications = Column(Text)  # Comma-separated product access (Jira Software, Confluence, etc.)
    project_roles = Column(Text)  # JSON-serialized dict of project keys and role names

class JiraDiffLog(Base):
    __tablename__ = "jira_diff_logs"
    
    id = Column(Integer, primary_key=True, index=True)
    sync_id = Column(Integer, ForeignKey("sync_history.id", ondelete="CASCADE"), index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    email = Column(String, index=True)
    display_name = Column(String)
    change_type = Column(String)  # "added", "removed", "modified"
    details = Column(Text)

from sqlalchemy import text

def init_db():
    Base.metadata.create_all(bind=engine)
    
    # Автоматическая миграция для добавления новых колонок в существующую БД SQLite
    try:
        with engine.begin() as conn:
            result = conn.execute(text("PRAGMA table_info(configs);"))
            column_names = [row[1] for row in result.fetchall()]
            
            if "email_report_frequency" not in column_names:
                conn.execute(text("ALTER TABLE configs ADD COLUMN email_report_frequency TEXT DEFAULT 'sync';"))
                print("Migration: Added email_report_frequency column to configs table.")
                
            if "last_email_sent" not in column_names:
                conn.execute(text("ALTER TABLE configs ADD COLUMN last_email_sent DATETIME;"))
                print("Migration: Added last_email_sent column to configs table.")
                
            if "jira_url" not in column_names:
                conn.execute(text("ALTER TABLE configs ADD COLUMN jira_url TEXT;"))
                print("Migration: Added jira_url column to configs table.")
                
            if "jira_username" not in column_names:
                conn.execute(text("ALTER TABLE configs ADD COLUMN jira_username TEXT;"))
                print("Migration: Added jira_username column to configs table.")
                
            if "jira_api_token" not in column_names:
                conn.execute(text("ALTER TABLE configs ADD COLUMN jira_api_token TEXT;"))
                print("Migration: Added jira_api_token column to configs table.")
                
            if "jira_sync_enabled" not in column_names:
                conn.execute(text("ALTER TABLE configs ADD COLUMN jira_sync_enabled INTEGER DEFAULT 0;"))
                print("Migration: Added jira_sync_enabled column to configs table.")
                
            # Проверяем колонки в sync_history
            result_sh = conn.execute(text("PRAGMA table_info(sync_history);"))
            sh_cols = [row[1] for row in result_sh.fetchall()]
            if "progress" not in sh_cols:
                conn.execute(text("ALTER TABLE sync_history ADD COLUMN progress INTEGER DEFAULT 0;"))
                print("Migration: Added progress column to sync_history table.")
    except Exception as migration_error:
        print(f"Migration error: {migration_error}")
    
    # Сброс зависших сессий синхронизации при запуске сервера
    try:
        session_cleanup = SessionLocal()
        interrupted = session_cleanup.query(SyncHistory).filter(SyncHistory.status == "running").all()
        for s in interrupted:
            s.status = "error"
            s.message = "Синхронизация прервана (сервер был перезапущен)."
            s.progress = 0
        session_cleanup.commit()
        session_cleanup.close()
        print("Startup cleanup: Resetted interrupted sync history records.")
    except Exception as cleanup_err:
        print(f"Startup cleanup error: {cleanup_err}")

    session = SessionLocal()
    try:
        # Create default config if not exists
        config = session.query(Config).first()
        if not config:
            config = Config()
            session.add(config)
            
        # Create default admin user if no users exist
        user_count = session.query(User).count()
        if user_count == 0:
            admin_user = User(
                username="admin",
                password_hash=hash_password("admin"),
                email="admin@local.host",
                auth_provider="local"
            )
            session.add(admin_user)
            
        session.commit()
    finally:
        session.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
