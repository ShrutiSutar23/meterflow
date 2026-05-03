# backend/config/database.py
"""
Database Connections
=====================
We manage 3 databases here:
  1. PostgreSQL  → Users, API Keys, Billing (structured, relational)
  2. MongoDB     → API Request Logs (unstructured, high-volume)
  3. Redis       → Rate Limiting, Caching (in-memory, ultra-fast)

Think of it like a company's filing system:
  - PostgreSQL = Official legal documents (structured, organized)
  - MongoDB    = Sticky notes / memos (flexible, many of them)
  - Redis      = Whiteboard (temporary, fast to read/write)
"""

from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase
from motor.motor_asyncio import AsyncIOMotorClient
import redis.asyncio as aioredis

from backend.config.settings import settings


# ═══════════════════════════════════════════════════════════════════════════════
# PostgreSQL Setup (via SQLAlchemy ORM)
# ═══════════════════════════════════════════════════════════════════════════════

# The "engine" is the actual connection to PostgreSQL
# async = non-blocking (doesn't freeze the server while waiting for DB)
pg_engine = create_async_engine(
    settings.POSTGRES_URL,
    echo=settings.DEBUG,        # Print SQL queries when DEBUG=True (helpful!)
    pool_size=10,               # Keep 10 connections ready (connection pooling)
    max_overflow=20,            # Allow 20 extra connections in heavy traffic
    pool_pre_ping=True,         # Check connection health before using it
)

# Session factory - creates DB sessions (like opening a drawer to work with files)
AsyncSessionLocal = async_sessionmaker(
    bind=pg_engine,
    class_=AsyncSession,
    expire_on_commit=False,     # Don't auto-expire objects after commit
)


class Base(DeclarativeBase):
    """Base class for all PostgreSQL models. Every model will inherit from this."""
    pass


async def get_db():
    """
    FastAPI Dependency Injection for DB sessions.
    
    Usage in a route:
        @router.get("/users")
        async def get_users(db: AsyncSession = Depends(get_db)):
            ...
    
    The 'async with' ensures the session is ALWAYS closed, even if an error occurs.
    This prevents connection leaks (a very common production bug!).
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()    # Undo changes if something went wrong
            raise
        finally:
            await session.close()


# ═══════════════════════════════════════════════════════════════════════════════
# MongoDB Setup (via Motor - async MongoDB driver)
# ═══════════════════════════════════════════════════════════════════════════════

mongo_client: AsyncIOMotorClient = None
mongo_db = None


async def get_mongo_db():
    """Returns the MongoDB database instance for use in routes."""
    return mongo_db


# ═══════════════════════════════════════════════════════════════════════════════
# Redis Setup
# ═══════════════════════════════════════════════════════════════════════════════

redis_client: aioredis.Redis = None


async def get_redis():
    """Returns the Redis client for use in rate limiting and caching."""
    return redis_client


# ═══════════════════════════════════════════════════════════════════════════════
# Startup & Shutdown Lifecycle
# ═══════════════════════════════════════════════════════════════════════════════

async def connect_db():
    """Called when FastAPI starts up. Establishes all database connections."""
    global mongo_client, mongo_db, redis_client

    # Connect to MongoDB
    mongo_client = AsyncIOMotorClient(settings.MONGODB_URL)
    mongo_db = mongo_client[settings.MONGODB_DB_NAME]
    print("✅ MongoDB connected")

    # Connect to Redis
    redis_client = aioredis.from_url(
        settings.REDIS_URL,
        encoding="utf-8",
        decode_responses=True,      # Return strings, not bytes
    )
    print("✅ Redis connected")

    # Create PostgreSQL tables (runs migrations)
    async with pg_engine.begin() as conn:
        from backend.models.user_model import User        # noqa
        from backend.models.apikey_model import APIKey    # noqa
        from backend.models.billing_model import UsageRecord  # noqa
        await conn.run_sync(Base.metadata.create_all)
    print("✅ PostgreSQL tables ready")


async def disconnect_db():
    """Called when FastAPI shuts down. Cleans up all connections."""
    global mongo_client, redis_client
    if mongo_client:
        mongo_client.close()
    if redis_client:
        await redis_client.close()
    await pg_engine.dispose()
    print("🔌 All database connections closed")
