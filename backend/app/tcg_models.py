"""Identification metadata; never joined into confirmed declaration snapshots."""
from uuid import UUID, uuid4
from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column
from app.database import Base


class Game(Base):
    __tablename__ = 'tcg_games'
    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))


class Expansion(Base):
    __tablename__ = 'tcg_expansions'
    __table_args__ = (UniqueConstraint('provider', 'external_id', 'language'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    game: Mapped[str] = mapped_column(ForeignKey('tcg_games.id'), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    code: Mapped[str] = mapped_column(String(200))
    release_year: Mapped[int | None]


class CatalogCard(Base):
    __tablename__ = 'tcg_cards'
    __table_args__ = (UniqueConstraint('provider', 'external_id', 'language'),)
    id: Mapped[UUID] = mapped_column(primary_key=True, default=uuid4)
    expansion_id: Mapped[UUID] = mapped_column(ForeignKey('tcg_expansions.id'), index=True)
    provider: Mapped[str] = mapped_column(String(64))
    external_id: Mapped[str] = mapped_column(String(200))
    language: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(200))
    collector_number: Mapped[str] = mapped_column(String(64))
