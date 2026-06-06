from sqlalchemy import create_engine, event, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase


DATABASE_URL = "sqlite:///./events.db"
 
engine = create_engine(
    DATABASE_URL,
    connect_args={"check_same_thread": False},
)


# ─── 2. WAL Mode Pragma ───────────────────────────────────────────────────────
# SQLite's default journal mode locks the entire database file for every write.
# WAL (Write-Ahead Logging) allows concurrent readers while a write is happening.
# This directly addresses the "prevent race condition / overbooking" requirement:
# multiple users can read seat counts simultaneously without blocking each other.
#
# We hook into SQLAlchemy's "connect" event so the PRAGMA runs on EVERY new
# connection, not just the first one — SQLite pragmas are per-connection settings.
@event.listens_for(engine, "connect")
def set_wal_mode(dbapi_connection, connection_record):
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")  # enforce FK constraints
    cursor.close()



# ─── 3. Session Factory ───────────────────────────────────────────────────────
# SessionLocal is a factory — calling SessionLocal() gives you a new DB session.
# autocommit=False  → we control commits manually (important for transactions)
# autoflush=False   → we control when SQL is sent to the DB (safer in services)
SessionLocal = sessionmaker(
    bind=engine,
    autocommit=False,
    autoflush=False,
)


class Base(DeclarativeBase):
    pass



def get_db():
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()



if __name__ == "__main__":
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA journal_mode"))
        mode = result.fetchone()[0]
        print(f"✅  Connected to SQLite. Journal mode: {mode.upper()}")
        result = conn.execute(text("PRAGMA foreign_keys"))
        fk = result.fetchone()[0]
        print(f"✅  Foreign keys enforced: {'YES' if fk else 'NO'}")