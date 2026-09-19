# models/edit_request.py
from datetime import datetime
import json
from extensions import db
from models.base import BaseModel


class EditRequest(BaseModel):
    __tablename__ = 'edit_requests'

    request_id = db.Column(db.Integer, primary_key=True, autoincrement=True)

    # What is being edited
    target_type = db.Column(db.String(50), nullable=False, index=True)   # 'Inmate' | 'Visitor' | 'UserAccount'
    target_id   = db.Column(db.Integer, nullable=False, index=True)
    target_label = db.Column(db.String(200))   # e.g. "LZR-2026-00001 John Doe" for display

    # Who requested
    requested_by = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'),
                             nullable=False, index=True)
    requested_at = db.Column(db.DateTime, default=datetime.utcnow,
                             nullable=False, index=True)
    request_reason = db.Column(db.Text)

    # The proposed changes: {"field": {"old": ..., "new": ...}, ...}
    changes_json = db.Column(db.Text, nullable=False)

    # Workflow status
    status = db.Column(db.String(20), default='Pending', nullable=False, index=True)

    # Review
    reviewed_by  = db.Column(db.Integer, db.ForeignKey('user_accounts.user_id'))
    reviewed_at  = db.Column(db.DateTime)
    review_notes = db.Column(db.Text)

    # Relationships
    requestor = db.relationship('UserAccount', foreign_keys=[requested_by])
    reviewer  = db.relationship('UserAccount', foreign_keys=[reviewed_by])

    # ---------- helpers ----------
    @property
    def changes(self) -> dict:
        try:
            return json.loads(self.changes_json or '{}')
        except Exception:
            return {}

    def set_changes(self, changes: dict):
        self.changes_json = json.dumps(changes)

    @property
    def change_count(self) -> int:
        return len(self.changes)

    def __repr__(self):
        return (f'<EditRequest #{self.request_id} {self.target_type}'
                f'/{self.target_id} status={self.status}>')