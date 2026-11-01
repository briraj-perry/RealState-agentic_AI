"""One-time, read-only import of an earlier local SQLite workspace into MongoDB."""

import argparse
import sqlite3
from pathlib import Path

from estate_ai.config import get_settings
from estate_ai.db import MODELS, connect


def migrate(source, factory):
    path = Path(source).resolve(strict=True)
    counts = {"imported": 0, "existing": 0}
    with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as legacy:
        legacy.row_factory = sqlite3.Row
        tables = {row[0] for row in legacy.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for model in MODELS:
            table = model.collection  # Server-owned names; no user SQL identifiers.
            if table not in tables:
                continue
            cursor = legacy.execute(f'SELECT * FROM "{table}"')
            while rows := cursor.fetchmany(100):
                with factory() as session:
                    for row in rows:
                        original = dict(row)
                        values = {name: original[name] for name in model.fields() if name in original}
                        for name, field in model.fields().items():
                            if isinstance(field.default, bool) and name in values:
                                values[name] = bool(values[name])
                        if session.get(model, values[model.pk]):
                            counts["existing"] += 1
                        else:
                            session.add(model(**values))
                            counts["imported"] += 1
                    session.commit()
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, help="Path to the existing local .db file")
    args = parser.parse_args()
    settings = get_settings()
    factory = connect(settings.mongodb_uri.get_secret_value(), settings.mongodb_database)
    try:
        counts = migrate(args.source, factory)
        print(
            f"Imported {counts['imported']} records; kept {counts['existing']} existing records. Source unchanged."
        )
    finally:
        factory.close()


if __name__ == "__main__":
    main()
