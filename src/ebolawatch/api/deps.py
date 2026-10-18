from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy.orm import Session

from ..db.session import SessionLocal


def get_session() -> Iterator[Session]:
    s = SessionLocal()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
