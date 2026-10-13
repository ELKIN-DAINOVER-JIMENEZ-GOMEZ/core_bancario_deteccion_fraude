"""Base declarativa de SQLAlchemy para todas las entidades del fraud-engine."""

from sqlalchemy import MetaData
from sqlalchemy.orm import DeclarativeBase

# Convención de nombres para índices y constraints.
# Permite que Alembic genere nombres estables y reproducibles en las migraciones.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Clase base de la que heredan todos los modelos."""

    metadata = MetaData(naming_convention=NAMING_CONVENTION)