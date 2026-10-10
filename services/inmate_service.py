# services/inmate_service.py
"""
Inmate business logic: create new, re-admit, list, search, detail.
"""
import base64
from datetime import date, datetime, timezone
from sqlalchemy import or_, func
from extensions import db
from models.cell import CellBlock
from models.inmate import Inmate, AdmissionEpisode
from models.audit import AuditEvent
from services.medical_record_service import MedicalRecordService
from services.sentence import expected_release, parse_sentence, sentence_label


class InmateService:
    SECURITY_CLASSIFICATIONS = ('Minimum', 'Medium', 'Maximum')

    @staticmethod
    def cell_block_options(
        security_classification=None,
        medical_isolation_required=False,
        exclude_inmate_id=None,
    ):
        query = CellBlock.query
        if security_classification:
            query = query.filter_by(
                security_classification=security_classification
            )
        query = query.filter_by(
            medical_isolation_unit=medical_isolation_required
        )

        blocks = query.order_by(CellBlock.name.asc()).all()
        occupancy_query = db.session.query(
            Inmate.cell_block, func.count(Inmate.inmate_id)
        ).filter(Inmate.status == 'Active', Inmate.cell_block.isnot(None))
        if exclude_inmate_id is not None:
            occupancy_query = occupancy_query.filter(
                Inmate.inmate_id != exclude_inmate_id
            )
        occupancy_by_name = dict(
            occupancy_query.group_by(Inmate.cell_block).all()
        )
        return [{
            'name': block.name,
            'security_classification': block.security_classification,
            'medical_isolation_unit': block.medical_isolation_unit,
            'capacity': block.capacity,
            'occupancy': occupancy_by_name.get(block.name, 0),
            'available': occupancy_by_name.get(block.name, 0) < block.capacity,
        } for block in blocks]

    @staticmethod
    def validate_cell_assignment(
        cell_name,
        security_classification,
        medical_isolation_required=False,
        exclude_inmate_id=None,
    ):
        if security_classification not in InmateService.SECURITY_CLASSIFICATIONS:
            return 'Select a valid security classification before assigning a cell.'
        if not cell_name:
            if medical_isolation_required:
                return 'A medical-isolation cell block is required for this inmate.'
            return None

        option = next(
            (
                cell for cell in InmateService.cell_block_options(
                    security_classification,
                    medical_isolation_required=medical_isolation_required,
                    exclude_inmate_id=exclude_inmate_id,
                )
                if cell['name'] == cell_name
            ),
            None,
        )
        if not option:
            if medical_isolation_required:
                return (
                    f'Cell block "{cell_name}" is not a designated medical-isolation '
                    f'unit for {security_classification} classification.'
                )
            return (
                f'Cell block "{cell_name}" is not configured for '
                f'{security_classification} classification.'
            )
        if not option['available']:
            return f'Cell block "{cell_name}" is at capacity.'
        return None

    @staticmethod
    def suggest_cell_block(
        security_classification,
        medical_isolation_required=False,
        exclude_inmate_id=None,
    ):
        options = [
            option for option in InmateService.cell_block_options(
                security_classification,
                medical_isolation_required=medical_isolation_required,
                exclude_inmate_id=exclude_inmate_id,
            )
            if option['available']
        ]
        if not options:
            return None
        return min(
            options,
            key=lambda option: (
                option['occupancy'] / option['capacity'],
                option['occupancy'],
                option['name'],
            ),
        )

    # ---------- Read ----------
    @staticmethod
    def list_inmates(search=None, status=None, page=1, per_page=15):
        q = Inmate.query
        if search:
            like = f'%{search.strip()}%'
            q = q.filter(or_(
                Inmate.full_name.ilike(like),
                Inmate.inmate_number.ilike(like),
                Inmate.crime_category.ilike(like),
            ))
        if status:
            q = q.filter(Inmate.status == status)
        return q.order_by(Inmate.inmate_id.desc()).paginate(
            page=page, per_page=per_page, error_out=False
        )

    @staticmethod
    def get(inmate_id) -> Inmate:
        return Inmate.query.get(inmate_id)

    @staticmethod
    def validate_legal_status(data):
        status = (data.get('sentence_type') or '').strip()
        if status == 'Remand':
            try:
                datetime.strptime(data.get('next_court_date') or '', '%Y-%m-%d')
            except ValueError:
                return 'Enter the next date to court for a remand inmate.'
        elif status == 'Convict':
            if not parse_sentence(data.get('sentence_value'), data.get('sentence_unit')):
                return 'Enter the sentence for a convicted inmate.'
        return None

    @staticmethod
    def _apply_sentence(inmate, data):
        status = (data.get('sentence_type') or '').strip()
        if status == 'Remand':
            inmate.next_court_date = datetime.strptime(data['next_court_date'], '%Y-%m-%d').date()
            inmate.sentence_duration = None
            inmate.sentence_start_date = None
            inmate.expected_release_date = None
            return
        if status != 'Convict':
            return
        inmate.next_court_date = None
        parsed = parse_sentence(data.get('sentence_value'), data.get('sentence_unit'))
        if not parsed:
            return
        number, unit = parsed
        start = date.today()
        inmate.sentence_duration = sentence_label(number, unit)
        inmate.sentence_start_date = start
        inmate.expected_release_date = expected_release(start, number, unit)['release_date']

    @staticmethod
    def generate_inmate_number() -> str:
        year = date.today().year
        prefix = f'LZR-{year}-'
        count = db.session.query(func.count(Inmate.inmate_id)).filter(
            Inmate.inmate_number.like(f'{prefix}%')
        ).scalar() or 0
        return f'{prefix}{count + 1:05d}'

    # ---------- Create new inmate ----------
    @staticmethod
    def create_inmate(actor, data: dict, fingerprint_template=None,
                      fingerprint_quality=None):
        required = ['full_name', 'date_of_birth', 'gender', 'nationality']
        for f in required:
            if not data.get(f):
                return None, f'{f.replace("_", " ").title()} is required.'

        try:
            dob = datetime.strptime(data['date_of_birth'], '%Y-%m-%d').date()
        except (ValueError, TypeError):
            return None, 'Date of birth is not a valid date.'

        legal_error = InmateService.validate_legal_status(data)
        if legal_error:
            return None, legal_error

        security_classification = data.get('security_classification') or 'Medium'
        cell_error = InmateService.validate_cell_assignment(
            data.get('cell_block'), security_classification
        )
        if cell_error:
            return None, cell_error

        inmate = Inmate(
            inmate_number=InmateService.generate_inmate_number(),
            full_name=data['full_name'].strip(),
            date_of_birth=dob,
            gender=data['gender'],
            nationality=data['nationality'].strip(),
            tribe=data.get('tribe'),
            religion=data.get('religion'),
            national_id_number=data.get('national_id_number'),
            next_of_kin_name=data.get('next_of_kin_name'),
            next_of_kin_relationship=data.get('next_of_kin_relationship'),
            next_of_kin_phone=data.get('next_of_kin_phone'),
            next_of_kin_phone_2=data.get('next_of_kin_phone_2'),
            next_of_kin_address=data.get('next_of_kin_address'),
            photo_path=data.get('photo_path'),
            height_cm=_to_int(data.get('height_cm')),
            weight_kg=_to_int(data.get('weight_kg')),
            overall_description=data.get('overall_description'),
            education=data.get('education'),
            arrested_from=data.get('arrested_from'),
            crime_category=data.get('crime_category'),
            crime_description=data.get('crime_description'),
            court_case_number=data.get('court_case_number'),
            sentence_type=data.get('sentence_type'),
            sentence_duration=data.get('sentence_duration'),
            cell_block=data.get('cell_block'),
            cell_number=data.get('cell_number'),
            security_classification=security_classification,
            has_medical_condition=_to_bool(data.get('has_medical_condition')),
            medical_alert=data.get('medical_alert'),
            status='Active',
            current_admission_date=date.today(),
            total_admissions=1,
            created_by=actor.user_id,
        )

        if data.get('expected_release_date'):
            try:
                inmate.expected_release_date = datetime.strptime(
                    data['expected_release_date'], '%Y-%m-%d'
                ).date()
            except ValueError:
                pass
        InmateService._apply_sentence(inmate, data)

        if fingerprint_template:
            try:
                inmate.fingerprint_template = _to_bytes(fingerprint_template)
                inmate.biometric_enrolled = True
                inmate.biometric_enrollment_date = datetime.now(timezone.utc).replace(tzinfo=None)
                inmate.biometric_quality_score = fingerprint_quality or 0
            except Exception as e:
                return None, f'Invalid fingerprint template: {e}'

        db.session.add(inmate)
        db.session.flush()

        episode = AdmissionEpisode(
            inmate_id=inmate.inmate_id,
            admission_date=date.today(),
            admission_type='New',
            admission_reason=data.get('admission_reason', 'Initial admission'),
            receiving_officer_id=actor.user_id,
            is_current=True,
        )
        db.session.add(episode)
        MedicalRecordService.add_prior_records(
            actor,
            inmate,
            summary=data.get('prior_medical_summary'),
            attachment_path=data.get('prior_medical_document_path'),
            attachment_name=data.get('prior_medical_document_name'),
        )
        db.session.commit()

        InmateService._audit(
            actor, 'Create',
            f'Registered new inmate {inmate.inmate_number} ({inmate.full_name})',
            inmate
        )
        return inmate, None

    # ---------- Re-admit existing inmate ----------
    @staticmethod
    def readmit_inmate(actor, inmate_id, data: dict, fingerprint_template=None,
                       fingerprint_quality=None):
        inmate = Inmate.query.get(inmate_id)
        if not inmate:
            return None, 'Inmate not found.'

        legal_error = InmateService.validate_legal_status(data)
        if legal_error:
            return None, legal_error

        if fingerprint_template:
            try:
                enrolled_template = _to_bytes(fingerprint_template)
            except (TypeError, ValueError) as error:
                return None, f'Invalid fingerprint template: {error}'

        security_classification = (
            data.get('security_classification')
            or inmate.security_classification
            or 'Medium'
        )
        cell_name = data.get('cell_block', inmate.cell_block) or None
        cell_error = InmateService.validate_cell_assignment(
            cell_name,
            security_classification,
            medical_isolation_required=inmate.medical_isolation_required,
            exclude_inmate_id=inmate.inmate_id,
        )
        if cell_error:
            return None, cell_error

        current = inmate.admission_episodes.filter_by(is_current=True).first()
        if current:
            current.is_current = False

        editable = [
            'crime_category', 'crime_description', 'court_case_number',
            'sentence_type', 'sentence_duration', 'cell_number',
            'education', 'arrested_from', 'overall_description',
            'tribe', 'religion',
            'security_classification', 'next_of_kin_name',
            'next_of_kin_relationship', 'next_of_kin_phone', 'next_of_kin_phone_2',
            'next_of_kin_address', 'medical_alert', 'photo_path',
        ]
        changes = []
        if 'cell_block' in data:
            new_cell_block = data.get('cell_block') or None
            if inmate.cell_block != new_cell_block:
                changes.append(
                    f'cell_block: "{inmate.cell_block}" -> "{new_cell_block}"'
                )
                inmate.cell_block = new_cell_block

        for f in editable:
            if f in data and data[f] not in (None, ''):
                old = getattr(inmate, f)
                new = data[f]
                if str(old or '') != str(new):
                    changes.append(f'{f}: "{old}" -> "{new}"')
                    setattr(inmate, f, new)

        if enrolled_template:
            inmate.fingerprint_template = enrolled_template
            inmate.biometric_enrolled = True
            inmate.biometric_enrollment_date = datetime.now(timezone.utc).replace(tzinfo=None)
            inmate.biometric_quality_score = fingerprint_quality or 0
            changes.append('fingerprint: enrolled')

        if data.get('expected_release_date'):
            try:
                inmate.expected_release_date = datetime.strptime(
                    data['expected_release_date'], '%Y-%m-%d'
                ).date()
            except ValueError:
                pass
        InmateService._apply_sentence(inmate, data)

        episode = AdmissionEpisode(
            inmate_id=inmate.inmate_id,
            admission_date=date.today(),
            admission_type='Re-admission',
            admission_reason=data.get('admission_reason', 'Re-admission'),
            receiving_officer_id=actor.user_id,
            is_current=True,
        )
        db.session.add(episode)
        MedicalRecordService.add_prior_records(
            actor,
            inmate,
            summary=data.get('prior_medical_summary'),
            attachment_path=data.get('prior_medical_document_path'),
            attachment_name=data.get('prior_medical_document_name'),
        )

        inmate.status = 'Active'
        inmate.current_admission_date = date.today()
        inmate.actual_release_date = None
        inmate.total_admissions = (inmate.total_admissions or 0) + 1
        db.session.commit()

        InmateService._audit(
            actor, 'Readmit',
            f'Re-admitted inmate {inmate.inmate_number} '
            f'(admission #{inmate.total_admissions})'
            + (f' — changes: {"; ".join(changes)}' if changes else ''),
            inmate
        )
        return inmate, None

    # ---------- Internal ----------
    @staticmethod
    def _audit(actor, event_type, description, inmate):
        AuditEvent.log_event(
            event_category='Inmate',
            event_type=event_type,
            event_description=description,
            entity_type='Inmate',
            entity_id=inmate.inmate_id,
            user_id=actor.user_id,
            username=actor.username,
            user_role=actor.role_name,
            success=True,
        )
        db.session.commit()


# ---------- Helpers ----------
def _to_int(v):
    if v in (None, ''):
        return None
    try:
        return int(v)
    except (ValueError, TypeError):
        return None


def _to_bool(v):
    return str(v).lower() in ('on', 'true', '1', 'yes')


def _to_bytes(v):
    if isinstance(v, bytes):
        return v
    if isinstance(v, str):
        return base64.b64decode(v)
    raise ValueError('Unsupported template type')