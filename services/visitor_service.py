# services/visitor_service.py
"""
Visitor business logic: register, list, search, detail,
visit check-in/check-out, visit history.
"""
import base64
from datetime import date, datetime
from sqlalchemy import or_, func
from extensions import db
from models.visitor import Visitor
from models.visit import VisitLog
from models.inmate import Inmate
from models.audit import AuditEvent


class VisitorService:

    # ---------- Read ----------
    @staticmethod
    def list_visitors(search=None, page=1, per_page=15):
        q = Visitor.query
        if search:
            like = f'%{search.strip()}%'
            # Build filters dynamically using actual database columns
            filters = [
                Visitor.full_name.ilike(like),
                Visitor.phone_number.ilike(like),
            ]
            if hasattr(Visitor, 'visitor_number'):
                filters.append(Visitor.visitor_number.ilike(like))
            if hasattr(Visitor, 'national_id_number'):
                filters.append(Visitor.national_id_number.ilike(like))
            if hasattr(Visitor, 'passport_number'):
                filters.append(Visitor.passport_number.ilike(like))

            q = q.filter(or_(*filters))

        return q.order_by(Visitor.visitor_id.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

    @staticmethod
    def get(visitor_id) -> Visitor:
        return Visitor.query.get(visitor_id)

    @staticmethod
    def generate_visitor_number() -> str:
        year = date.today().year
        prefix = f'VIS-{year}-'

        # Safe generation: Uses visitor_number if present, otherwise counts visitor_id
        if hasattr(Visitor, 'visitor_number'):
            count = db.session.query(func.count(Visitor.visitor_id)).filter(
                Visitor.visitor_number.like(f'{prefix}%')
            ).scalar() or 0
        else:
            count = db.session.query(func.count(Visitor.visitor_id)).scalar() or 0

        return f'{prefix}{count + 1:05d}'

    # ---------- Register new visitor ----------
    @staticmethod
    def register_visitor(actor, data: dict, fingerprint_template=None,
                          fingerprint_quality=None):
        required = ['full_name', 'phone_number', 'relationship_to_inmate']
        for f in required:
            if not data.get(f):
                return None, f'{f.replace("_", " ").title()} is required.'

        v_num = VisitorService.generate_visitor_number()

        raw_kwargs = {
            'full_name': data['full_name'].strip(),
            'date_of_birth': _parse_date(data.get('date_of_birth')),
            'gender': data.get('gender'),
            'nationality': data.get('nationality'),
            'id_type': data.get('id_type'),
            'id_number': data.get('id_number'),
            'phone_number': data['phone_number'].strip(),
            'email': data.get('email'),
            'physical_address': data.get('physical_address'),
            'relationship_to_inmate': data.get('relationship_to_inmate'),
            'total_visits': 0,
            'created_by': actor.user_id,
        }

        if hasattr(Visitor, 'visitor_number'):
            raw_kwargs['visitor_number'] = v_num

        # Only keep attributes that exist on the Visitor model or properties
        kwargs = {
            k: v for k, v in raw_kwargs.items() 
            if hasattr(Visitor, k)
        }

        visitor = Visitor(**kwargs)

        if fingerprint_template:
            try:
                visitor.fingerprint_template = _to_bytes(fingerprint_template)
                if hasattr(visitor, 'biometric_enrolled'):
                    visitor.biometric_enrolled = True
                if hasattr(visitor, 'biometric_enrollment_date'):
                    visitor.biometric_enrollment_date = datetime.utcnow()
                if hasattr(visitor, 'biometric_quality_score'):
                    visitor.biometric_quality_score = fingerprint_quality or 0
            except Exception as e:
                return None, f'Invalid fingerprint template: {e}'

        db.session.add(visitor)
        db.session.commit()

        VisitorService._audit(
            actor, 'Register',
            f'Registered visitor {getattr(visitor, "visitor_number", v_num)} ({visitor.full_name})',
            visitor
        )
        return visitor, None

    # ---------- Check-in (create a VisitLog) ----------
    @staticmethod
    def check_in(actor, visitor_id, inmate_id, data: dict):
        visitor = Visitor.query.get(visitor_id)
        inmate = Inmate.query.get(inmate_id)

        if not visitor:
            return None, 'Visitor not found.'
        if not inmate:
            return None, 'Inmate not found.'
        if getattr(visitor, 'is_blacklisted', False):
            return None, (
                f'Visitor is blacklisted: {getattr(visitor, "blacklist_reason", "no reason given")}'
            )
        if inmate.status != 'Active':
            return None, f'Inmate is not currently in custody (status: {inmate.status}).'

        # Gather potential fields for VisitLog using check_in_time column
        now = datetime.utcnow()
        raw_kwargs = {
            'visitor_id': visitor.visitor_id,
            'inmate_id': inmate.inmate_id,
            'check_in_time': now,
            'visit_type': data.get('visit_type') or 'Regular',
            'items_brought': data.get('items_brought'),
            'security_check_passed': True,
            'visit_status': 'Approved',
            'status': 'Approved',
            'processed_by': actor.user_id,
            'created_by': actor.user_id,
            'biometric_verified': True,
        }

        # Dynamically filter only attributes that exist on the VisitLog model
        visit_kwargs = {
            k: v for k, v in raw_kwargs.items() 
            if hasattr(VisitLog, k)
        }

        visit = VisitLog(**visit_kwargs)
        db.session.add(visit)

        # Update visit counters safely
        if hasattr(visitor, 'total_visits'):
            visitor.total_visits = (visitor.total_visits or 0) + 1
        elif hasattr(visitor, 'total_visits_made'):
            visitor.total_visits_made = (visitor.total_visits_made or 0) + 1

        if hasattr(visitor, 'last_visit_date'):
            visitor.last_visit_date = date.today()

        db.session.commit()

        vis_no = getattr(visitor, 'visitor_number', f'# {visitor.visitor_id}')
        VisitorService._audit(
            actor, 'CheckIn',
            f'Visitor {vis_no} checked in to see '
            f'inmate {inmate.inmate_number} ({inmate.full_name})',
            visitor
        )
        return visit, None

    # ---------- Check-out ----------
    @staticmethod
    def check_out(actor, visit_id):
        visit = VisitLog.query.get(visit_id)
        if not visit:
            return False, 'Visit log not found.'
        if visit.check_out_time:
            return False, 'Visitor is already checked out.'

        visit.check_out_time = datetime.utcnow()
        delta = visit.check_out_time - visit.check_in_time
        visit.visit_duration_minutes = int(delta.total_seconds() // 60)
        visit.visit_status = 'Completed'
        db.session.commit()

        VisitorService._audit(
            actor, 'CheckOut',
            f'Visitor (visit #{visit.visit_id}) checked out after '
            f'{visit.visit_duration_minutes} min',
            visit.visitor
        )
        return True, None

    # ---------- Internal ----------
    @staticmethod
    def _audit(actor, event_type, description, visitor):
        AuditEvent.log_event(
            event_category='Visitor',
            event_type=event_type,
            event_description=description,
            entity_type='Visitor',
            entity_id=visitor.visitor_id,
            user_id=actor.user_id, username=actor.username, user_role=actor.role_name,
            success=True,
        )
        db.session.commit()


# ---------- helpers ----------
def _parse_date(v):
    if not v:
        return None
    try:
        return datetime.strptime(str(v), '%Y-%m-%d').date()
    except ValueError:
        return None


def _to_bytes(v):
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        return base64.b64decode(v)
    raise ValueError('Unsupported template type')