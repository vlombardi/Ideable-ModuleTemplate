import os
from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker
from sqlalchemy_continuum import make_versioned
from sqlalchemy_continuum.plugins import TransactionMetaPlugin
from .audit import ActorPlugin

DATABASE_URL = os.getenv('DATABASE_URL', 'postgresql://template_user:template_password@localhost:5432/template_db')

make_versioned(user_cls=None, plugins=[TransactionMetaPlugin(), ActorPlugin()])

engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
