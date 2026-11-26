from contextlib import contextmanager

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from ..config import get_settings

_engines = {}


def get_engine(url=None):
    url = url or get_settings().database_url
    if url not in _engines:
        _engines[url] = create_engine(url, pool_pre_ping=True)
    return _engines[url]


@contextmanager
def session_scope(url=None):
    """One transaction: commit on success, roll back on error."""
    session = sessionmaker(bind=get_engine(url), expire_on_commit=False)()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def database_status(url=None):
    """(ok, message) for `cn-agent doctor`."""
    try:
        with get_engine(url).connect() as conn:
            version = conn.execute(text("select extversion from pg_extension where extname = 'vector'")).scalar()
            revision = conn.execute(text("select version_num from alembic_version")).scalar() \
                if conn.execute(text("select to_regclass('alembic_version')")).scalar() else None
    except Exception as exc:  # noqa: BLE001 - reported to the user as-is
        return False, f"无法连接数据库：{exc.__class__.__name__}: {str(exc).splitlines()[0]}"
    if not version:
        return False, "已连接，但没有安装 pgvector 扩展；请运行 cn-agent db upgrade"
    return True, f"已连接；pgvector {version}；迁移版本 {revision or '未迁移'}"


__all__ = ["Session", "get_engine", "session_scope", "database_status"]
