"""Usage: python -X utf8 scripts/build_bm25_index.py <DATABASE_URL> <index_directory>."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from app.retrieval.bm25_index import rebuild
from app.storage.postgres.models import OrgMemberRecord, UserRecord
from app.storage.postgres.runtime import PostgresSourceStore


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Usage: build_bm25_index.py <DATABASE_URL> <index_directory>")
    engine = create_engine(sys.argv[1])
    factory = sessionmaker(engine)
    try:
        with factory() as db:
            owners = list(db.scalars(select(UserRecord.user_id)))
            memberships = list(db.execute(select(OrgMemberRecord.user_id, OrgMemberRecord.space_id)
                                          .where(OrgMemberRecord.status == "ACTIVE")))
        count = 0
        for owner in owners:
            count += len(rebuild(PostgresSourceStore(factory, owner), sys.argv[2]).documents)
        for owner, space in memberships:
            count += len(rebuild(PostgresSourceStore(factory, owner, space_id=space), sys.argv[2]).documents)
        print(f"Built {len(owners) + len(memberships)} scoped indexes ({count} chunks) in {sys.argv[2]}")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
