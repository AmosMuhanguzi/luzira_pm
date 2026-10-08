# services/edit_request_service.py
"""
Change-request workflow for inmate edits.
Anyone with INMATE_EDIT_REQUEST can submit; only INMATE_EDIT_APPROVE can approve.
"""
from datetime import datetime, date
from extensions import db
from models.edit_request import EditRequest
from models.inmate import Inmate
from models.visitor import Visitor
from models.audit import AuditEvent


# Fields that can be edited and their type (for coercion on apply)
INMATE_EDITABLE_FIELDS = {
    'full_name': str, 'date_of_birth': 'date', 'gender': str, 'nationality': str,
    'tribe': str, 'religion': str, 'national_id_number': str,
    'next_of_kin_name': str, 'next_of_kin_relationship': str,
    'next_of_kin_phone': str, 'next_of_kin_address': str,
    'height_cm': int, 'weight_kg': int,
    'crime_category': str, 'crime_description': str,
    'court_case_number': str, 'sentencing_court': str, 'judge_name': str,
    'sentence_type': str, 'sentence_duration': str,
    'sentence_start_date': 'date', 'expected_release_date': 'date',
    'cell_block': str, 'cell_number': str, 'security_classification': str,
    'has_medical_condition': bool, 'medical_alert': str,
    'risk_level': str,
}

VISITOR_EDITABLE_FIELDS = {
    'full_name': str,
    'date_of_birth': 'date',
    'gender': str,
    'nationality': str,
    'national_id_number': str,
    'passport_number': str,
    'phone_number': str,
    'email': str,
    'address': str,
    'relationship_type': str,
}


class EditRequestService:

    # ---------- Submit ----------
    @staticmethod
    def submit_inmate_edit(
        actor, inmate_id, form_data: dict, reason: str = None,
        photo_path: str = None,
    ):
        """
        Build a diff from form_data vs the current inmate, create an EditRequest.
        Returns (edit_request, error)
        """
        inmate = Inmate.query.get(inmate_id)
        if not inmate:
            return None, 'Inmate not found.'

        changes = {}
        for field, ftype in INMATE_EDITABLE_FIELDS.items():
            if field not in form_data:
                continue
            raw_new = form_data.get(field)
            old_val = getattr(inmate, field)
            new_val = _coerce(raw_new, ftype)

            # Normalise for comparison
            if not _equal(old_val, new_val):
                changes[field] = {
                    'old': _serialize(old_val),
                    'new': _serialize(new_val),
                }

        if photo_path and not _equal(inmate.photo_path, photo_path):
            changes['photo_path'] = {
                'old': _serialize(inmate.photo_path),
                'new': _serialize(photo_path),
            }

        if not changes:
            return None, 'No changes detected. Modify at least one field.'

        req = EditRequest(
            target_type='Inmate',
            target_id=inmate_id,
            target_label=f'{inmate.inmate_number} — {inmate.full_name}',
            requested_by=actor.user_id,
            request_reason=(reason or '').strip() or None,
        )
        req.set_changes(changes)
        req.status = 'Pending'

        db.session.add(req)
        db.session.commit()

        AuditEvent.log_event(
            event_category='EditRequest',
            event_type='Submit',
            event_description=(
                f'Edit request #{req.request_id} submitted for inmate '
                f'{inmate.inmate_number} ({len(changes)} field(s))'
            ),
            entity_type='EditRequest',
            entity_id=req.request_id,
            user_id=actor.user_id, username=actor.username, user_role=actor.role_name,
            success=True,
        )
        db.session.commit()
        return req, None

    @staticmethod
    def submit_visitor_edit(
        actor, visitor_id, form_data: dict, reason: str = None,
        photo_path: str = None,
    ):
        visitor = Visitor.query.get(visitor_id)
        if not visitor:
            return None, 'Visitor not found.'

        changes = {}
        for field, ftype in VISITOR_EDITABLE_FIELDS.items():
            if field not in form_data:
                continue
            old_value = getattr(visitor, field)
            new_value = _coerce(form_data[field], ftype)
            if not _equal(old_value, new_value):
                changes[field] = {
                    'old': _serialize(old_value),
                    'new': _serialize(new_value),
                }

        if photo_path and not _equal(visitor.photo_path, photo_path):
            changes['photo_path'] = {
                'old': _serialize(visitor.photo_path),
                'new': _serialize(photo_path),
            }

        if not changes:
            return None, 'No changes detected. Modify at least one field.'

        visitor_label = visitor.visitor_number or f'Visitor #{visitor.visitor_id}'
        req = EditRequest(
            target_type='Visitor',
            target_id=visitor.visitor_id,
            target_label=f'{visitor_label} — {visitor.full_name}',
            requested_by=actor.user_id,
            request_reason=(reason or '').strip() or None,
        )
        req.set_changes(changes)
        req.status = 'Pending'
        db.session.add(req)
        db.session.commit()

        AuditEvent.log_event(
            event_category='EditRequest',
            event_type='Submit',
            event_description=(
                f'Edit request #{req.request_id} submitted for visitor '
                f'{visitor_label} ({len(changes)} field(s))'
            ),
            entity_type='EditRequest',
            entity_id=req.request_id,
            user_id=actor.user_id,
            username=actor.username,
            user_role=actor.role_name,
            success=True,
        )
        db.session.commit()
        return req, None

    # ---------- Apply / Reject ----------
    @staticmethod
    def approve(actor, request_id, notes: str = None):
        req = EditRequest.query.get(request_id)
        if not req:
            return False, 'Request not found.'
        if req.status != 'Pending':
            return False, f'Request is already {req.status.lower()}.'

        if req.target_type == 'Inmate':
            target = Inmate.query.get(req.target_id)
            editable_fields = {**INMATE_EDITABLE_FIELDS, 'photo_path': str}
            target_description = (
                f'inmate {target.inmate_number}' if target else 'inmate'
            )
        elif req.target_type == 'Visitor':
            target = Visitor.query.get(req.target_id)
            editable_fields = {**VISITOR_EDITABLE_FIELDS, 'photo_path': str}
            target_id = target.visitor_id if target else req.target_id
            visitor_label = (
                (target.visitor_number or f'#{target.visitor_id}')
                if target else f'#{req.target_id}'
            )
            target_description = f'visitor {visitor_label}' if target else 'visitor'
        else:
            return False, f'Unsupported target type: {req.target_type}'

        if not target:
            return False, f'Target {req.target_type.lower()} no longer exists.'
        if req.target_type == 'Inmate':
            target_id = target.inmate_id

        # Apply each change
        for field, delta in req.changes.items():
            ftype = editable_fields.get(field)
            if ftype is None:
                continue   # field no longer editable; skip
            setattr(target, field, _coerce(delta['new'], ftype))

        req.status = 'Approved'
        req.reviewed_by = actor.user_id
        req.reviewed_at = datetime.utcnow()
        req.review_notes = (notes or '').strip() or None

        db.session.commit()

        AuditEvent.log_event(
            event_category='EditRequest',
            event_type='Approve',
            event_description=(
                f'Edit request #{req.request_id} approved '
                f'({len(req.changes)} field(s)) for {target_description}'
            ),
            entity_type=req.target_type,
            entity_id=target_id,
            user_id=actor.user_id, username=actor.username, user_role=actor.role_name,
            success=True,
        )
        db.session.commit()
        return True, None

    @staticmethod
    def reject(actor, request_id, notes: str = None):
        req = EditRequest.query.get(request_id)
        if not req:
            return False, 'Request not found.'
        if req.status != 'Pending':
            return False, f'Request is already {req.status.lower()}.'

        req.status = 'Rejected'
        req.reviewed_by = actor.user_id
        req.reviewed_at = datetime.utcnow()
        req.review_notes = (notes or '').strip() or None
        db.session.commit()

        AuditEvent.log_event(
            event_category='EditRequest',
            event_type='Reject',
            event_description=(
                f'Edit request #{req.request_id} rejected'
                + (f' — {notes}' if notes else '')
            ),
            entity_type='EditRequest',
            entity_id=req.request_id,
            user_id=actor.user_id, username=actor.username, user_role=actor.role_name,
            success=True,
        )
        db.session.commit()
        return True, None

    # ---------- Reads ----------
    @staticmethod
    def list_requests(status='Pending', target_type=None, page=1, per_page=15):
        q = EditRequest.query
        if status:
            q = q.filter(EditRequest.status == status)
        if target_type:
            q = q.filter(EditRequest.target_type == target_type)
        return q.order_by(EditRequest.requested_at.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

    @staticmethod
    def pending_count():
        return EditRequest.query.filter_by(status='Pending').count()

    @staticmethod
    def pending_for_inmate(inmate_id):
        return EditRequest.query.filter_by(
            target_type='Inmate', target_id=inmate_id, status='Pending'
        ).order_by(EditRequest.requested_at.desc()).all()


# ---------- helpers ----------
def _coerce(value, ftype):
    if value is None:
        return None
    if ftype is bool:
        return str(value).lower() in ('on', 'true', '1', 'yes')
    if ftype == 'date':
        if isinstance(value, date):
            return value
        try:
            return datetime.strptime(str(value), '%Y-%m-%d').date()
        except ValueError:
            return None
    if ftype is int:
        try:
            return int(value) if value != '' else None
        except (ValueError, TypeError):
            return None
    if ftype is str:
        return str(value).strip() or None
    return value


def _serialize(value):
    if value is None:
        return None
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, bool):
        return value
    return str(value)


def _equal(a, b):
    # Normalise None and empty strings
    if a in (None, '') and b in (None, ''):
        return True
    sa = _serialize(a)
    sb = _serialize(b)
    return sa == sb