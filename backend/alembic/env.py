from alembic import context
from sqlalchemy import create_engine

from app.config import get_settings
from app.database import Base
from app import models  # noqa: F401
from app import customer_models  # noqa: F401
from app import submission_models  # noqa: F401
from app import stripe_models  # noqa: F401
from app import logistics_models  # noqa: F401
from app import commercial_models  # noqa: F401
from app import pricing_models  # noqa: F401
from app import checkout_models  # noqa: F401
from app import intake_models  # noqa: F401

from app import inspection_models  # noqa: F401

from app import tcg_models  # noqa: F401
from app import library_models  # noqa: F401
from app import production_models  # noqa: F401
from app import intake_voids  # noqa: F401

target_metadata = Base.metadata
url = get_settings().database_url

if context.is_offline_mode():
    context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()
else:
    engine = create_engine(url)
    with engine.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()
    engine.dispose()
