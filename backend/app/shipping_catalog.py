"""Trusted operator CLI; configuration contains no default rates or guarantees."""
import argparse
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.checkout_models import ShippingConfiguration, ShippingState
from app.checkout_schemas import ShippingCatalog
from app.database import get_engine


def publish(db, document):
    config = ShippingCatalog.model_validate(document)
    state = db.scalar(select(ShippingState).where(ShippingState.id == 1).with_for_update())
    if state is None:
        raise ValueError("Apply migration 0005 first")
    record = ShippingConfiguration(document=config.model_dump())
    db.add(record)
    db.flush()
    state.current_version = record.version
    db.flush()
    return record


def main():
    parser = argparse.ArgumentParser(description="Validate or publish verified return-shipping configuration")
    parser.add_argument("action", choices=("validate", "publish"))
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.file.stat().st_size > 1_000_000:
        parser.error("Configuration exceeds 1 MB")
    document = json.loads(args.file.read_text(encoding="utf-8-sig"))
    ShippingCatalog.model_validate(document)
    if args.action == "validate":
        print("Valid shipping configuration; verify coverage evidence before publication")
        return
    with Session(get_engine()) as db:
        record = publish(db, document)
        db.commit()
        print(f"Published shipping configuration {record.version}")


if __name__ == "__main__":
    main()
