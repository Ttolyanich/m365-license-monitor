import os
from datetime import datetime
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

class SyncHistory(Base):
    __tablename__ = "sync_history"
    
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow)
    status = Column(String)  # "success", "failed"
    message = Column(Text, default="")
    users_count = Column(Integer, default=0)

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

def init_db():
    Base.metadata.create_all(bind=engine)
    
    # Create default config if not exists
    session = SessionLocal()
    try:
        config = session.query(Config).first()
        if not config:
            config = Config()
            session.add(config)
            session.commit()
    finally:
        session.close()

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
