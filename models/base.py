# models/base.py
from datetime import datetime
from extensions import db


class TimestampMixin:
    """Adds created_at / updated_at to any model."""
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(
        db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow, nullable=False
    )


class SerializableMixin:
    """Generic to_dict() using column introspection."""
    def to_dict(self, exclude=None, include=None):
        exclude = set(exclude or [])
        # Never expose binary blobs in default serialization
        exclude.update({'fingerprint_template', 'password_hash'})

        data = {}
        for col in self.__table__.columns:
            if col.name in exclude:
                continue
            if include and col.name not in include:
                continue
            value = getattr(self, col.name)
            if isinstance(value, datetime):
                value = value.isoformat()
            elif isinstance(value, bytes):
                value = f'<binary {len(value)} bytes>'
            data[col.name] = value
        return data


class BaseModel(db.Model, TimestampMixin, SerializableMixin):
    """Abstract base — inherits db.Model + mixins."""
    __abstract__ = True