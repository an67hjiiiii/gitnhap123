"""Usage: python -X utf8 scripts/build_doc_cards.py <DATABASE_URL>."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.retrieval.doc_route import rebuild_doc_cards


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: build_doc_cards.py <DATABASE_URL>")
    engine = create_engine(sys.argv[1])
    try:
        print(f"Built {rebuild_doc_cards(sessionmaker(engine))} document cards")
    finally:
        engine.dispose()


if __name__ == "__main__":
    main()
