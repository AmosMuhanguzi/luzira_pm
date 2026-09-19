# models/audit.py
from datetime import datetime
from extensions import db
from models.base import SerializableMixin


class AuditEvent(db.Model, SerializableMixin):
    __tablename__ = 'audit_events'

    event_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    event_category    = db.Column(db.String(50), nullable=False, index=True)
    event_type        = db.Column(db.String(50), nullable=False)
    event_description = db.Column(db.Text, nullable=False)

    entity_type = db.Column(db.String(50))
    entity_id   = db.Column(db.Integer)

    user_id    = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'), index=True)
    username   = db.Column(db.String(80))
    user_role  = db.Column(db.String(50))
    ip_address = db.Column(db.String(45))
    user_agent = db.Column(db.Text)

    old_values = db.Column(db.Text)   # JSON
    new_values = db.Column(db.Text)   # JSON

    session_id     = db.Column(db.String(100))
    request_method = db.Column(db.String(10))
    request_path   = db.Column(db.String(255))

    success       = db.Column(db.Boolean, default=True)
    error_message = db.Column(db.Text)

    event_timestamp = db.Column(db.DateTime, default=datetime.utcnow, nullable=False, index=True)

    @classmethod
    def log_event(cls, event_category, event_type, event_description,
                  entity_type=None, entity_id=None, user_id=None, username=None,
                  user_role=None, ip_address=None, user_agent=None,
                  old_values=None, new_values=None, success=True, error_message=None):
        """Convenience helper to write an audit event."""
        import json
        event = cls(
            event_category=event_category,
            event_type=event_type,
            event_description=event_description,
            entity_type=entity_type,
            entity_id=entity_id,
            user_id=user_id,
            username=username,
            user_role=user_role,
            ip_address=ip_address,
            user_agent=user_agent,
            old_values=json.dumps(old_values) if old_values else None,
            new_values=json.dumps(new_values) if new_values else None,
            success=success,
            error_message=error_message,
        )
        db.session.add(event)
        return event

    def __repr__(self):
        return f'<AuditEvent {self.event_category}/{self.event_type} by {self.username}>'