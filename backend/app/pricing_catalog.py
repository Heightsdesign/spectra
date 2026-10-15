"""Operator-only CLI. No customer catalog mutation endpoint or admin UI."""
import argparse
import json
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.database import get_engine
from app.pricing_models import PricingCatalog, PricingState
from app.pricing_schemas import Catalog


def publish(db, document, settings):
    config = Catalog.model_validate(document)
    if config.tax_mode == "pending" or (not config.development_only and not config.tax_validation_reference):
        raise ValueError("Tax treatment must be configured and validated before commercial publication")
    if config.development_only and settings.auth_environment == "production":
        raise ValueError("Development example catalogs cannot be published in production")
    state = db.scalar(select(PricingState).where(PricingState.id == 1).with_for_update())
    if state is None:
        raise ValueError("Apply migration 0004 before publishing a catalog")
    record = PricingCatalog(document=config.model_dump())
    db.add(record)
    db.flush()
    state.current_version = record.version
    db.flush()
    return record


def main():
    parser = argparse.ArgumentParser(description="Validate or publish a complete versioned pricing catalog")
    parser.add_argument("action", choices=("validate", "publish"))
    parser.add_argument("file", type=Path)
    args = parser.parse_args()
    if args.file.stat().st_size > 1_000_000:
        parser.error("Catalog exceeds 1 MB")
    document = json.loads(args.file.read_text(encoding="utf-8-sig"))
    config = Catalog.model_validate(document)
    if args.action == "validate":
        if config.tax_mode == "pending" or (not config.development_only and not config.tax_validation_reference):
            print("Valid document; TAX VALIDATION PENDING - PUBLICATION BLOCKED")
            return
        print("Valid catalog; DEVELOPMENT EXAMPLES ONLY" if config.development_only else "Valid catalog; operator approval reference recorded")
        return
    with Session(get_engine()) as db:
        record = publish(db, document, get_settings())
        db.commit()
        print(f"Published pricing configuration {record.version}")


if __name__ == "__main__":
    main()
