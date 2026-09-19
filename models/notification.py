# models/notification.py
from datetime import datetime
from extensions import db
from models.base import BaseModel


class SystemSetting(BaseModel):
    __tablename__ = 'system_settings'

    setting_id    = db.Column(db.Integer, primary_key=True, autoincrement=True)
    setting_key   = db.Column(db.String(100), unique=True, nullable=False, index=True)
    setting_value = db.Column(db.Text)
    setting_type  = db.Column(db.String(20))   # string | integer | boolean | json
    description   = db.Column(db.Text)

    updated_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))
    # updated_at inherited from TimestampMixin


class Notification(BaseModel):
    __tablename__ = 'notifications'

    notification_id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'), index=True)

    title             = db.Column(db.String(200), nullable=False)
    message           = db.Column(db.Text, nullable=False)
    notification_type = db.Column(db.String(50))
    priority          = db.Column(db.String(20), default='Normal')

    related_entity_type = db.Column(db.String(50))
    related_entity_id   = db.Column(db.Integer)

    is_read      = db.Column(db.Boolean, default=False, index=True)
    read_at      = db.Column(db.DateTime)
    is_dismissed = db.Column(db.Boolean, default=False)
    dismissed_at = db.Column(db.DateTime)

    @classmethod
    def create_ai_alert(cls, title, message, related_entity_type=None,
                        related_entity_id=None, severity='Medium', user_id=None):
        n = cls(
            user_id=user_id,
            title=title,
            message=message,
            notification_type='AI_Alert',
            priority=severity,
            related_entity_type=related_entity_type,
            related_entity_id=related_entity_id,
        )
        db.session.add(n)
        return n