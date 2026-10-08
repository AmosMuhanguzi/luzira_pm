import logging
from datetime import date, datetime
from pathlib import Path
from uuid import uuid4

from flask import current_app
from werkzeug.utils import secure_filename

from extensions import db
from models.audit import AuditEvent
from models.inmate import Inmate
from models.medical import MedicalRecord, MedicalRecordAttachment


logger = logging.getLogger(__name__)
MAX_DOCUMENT_BYTES = 10 * 1024 * 1024
MAX_DOCUMENTS_PER_RECORD = 10
ALLOWED_DOCUMENT_EXTENSIONS = {'.pdf', '.jpg', '.jpeg', '.png'}


class MedicalRecordService:
    @staticmethod
    def save_documents(uploads, inmate_id):
        selected_uploads = [upload for upload in uploads if upload and upload.filename]
        if len(selected_uploads) > MAX_DOCUMENTS_PER_RECORD:
            return [], (
                f'You can attach up to {MAX_DOCUMENTS_PER_RECORD} documents '
                'to one medical record.'
            )

        saved_documents = []
        for upload in selected_uploads:
            path, original_name, error = MedicalRecordService.save_document(
                upload, inmate_id
            )
            if error:
                for saved_path, _ in saved_documents:
                    MedicalRecordService.delete_document(saved_path)
                return [], error
            saved_documents.append((path, original_name))
        return saved_documents, None

    @staticmethod
    def save_document(upload, inmate_id):
        if not upload or not upload.filename:
            return None, None, None

        original_name = secure_filename(upload.filename)
        extension = Path(original_name).suffix.lower()
        if not original_name or extension not in ALLOWED_DOCUMENT_EXTENSIONS:
            return None, None, 'Upload a PDF, JPG, or PNG medical document.'

        content = upload.stream.read(MAX_DOCUMENT_BYTES + 1)
        if len(content) > MAX_DOCUMENT_BYTES:
            return None, None, 'Medical documents must be 10 MB or smaller.'
        if not content:
            return None, None, 'The selected medical document is empty.'
        valid_signature = (
            (extension == '.pdf' and content.startswith(b'%PDF-'))
            or (extension in {'.jpg', '.jpeg'} and content.startswith(b'\xff\xd8\xff'))
            or (extension == '.png' and content.startswith(b'\x89PNG\r\n\x1a\n'))
        )
        if not valid_signature:
            return None, None, 'The file contents do not match a supported medical document type.'

        owner_directory = str(inmate_id) if inmate_id else 'intake'
        relative_path = Path(owner_directory) / f'{uuid4().hex}{extension}'
        document_path = Path(current_app.instance_path) / 'medical_records' / relative_path
        try:
            document_path.parent.mkdir(parents=True, exist_ok=True)
            document_path.write_bytes(content)
        except OSError:
            logger.exception('Unable to save inmate medical document.')
            return None, None, 'The medical document could not be saved. Please try again.'

        return relative_path.as_posix(), original_name, None

    @staticmethod
    def delete_document(relative_path):
        if not relative_path:
            return
        storage_root = (Path(current_app.instance_path) / 'medical_records').resolve()
        document_path = (storage_root / relative_path).resolve()
        if storage_root not in document_path.parents:
            logger.error('Refusing to delete medical document outside storage root.')
            return
        try:
            document_path.unlink(missing_ok=True)
        except OSError:
            logger.exception('Unable to remove an unassociated medical document.')

    @staticmethod
    def add_prior_records(actor, inmate, summary=None, attachment_path=None,
                          attachment_name=None):
        summary = (summary or '').strip()
        if not summary and not attachment_path:
            return None

        record = MedicalRecord(
            inmate_id=inmate.inmate_id,
            record_date=date.today(),
            record_type='Prior medical records',
            notes=summary or None,
            recorded_by=actor.user_id,
            attachment_path=attachment_path,
            attachment_name=attachment_name,
            approval_status='Approved',
        )
        db.session.add(record)
        return record

    @staticmethod
    def submit_record(actor, inmate_id, data, attachment_path=None,
                      attachment_name=None, attachments=None):
        inmate = Inmate.query.get(inmate_id)
        if not inmate:
            return None, 'Inmate not found.'

        record_type = (data.get('record_type') or '').strip()
        hospital_name = (data.get('hospital_name') or '').strip()
        if len(record_type) > 50:
            return None, 'Record type must be 50 characters or fewer.'
        if len(hospital_name) > 150:
            return None, 'Hospital name must be 150 characters or fewer.'

        try:
            record_date = datetime.strptime(data.get('record_date', ''), '%Y-%m-%d').date()
        except (TypeError, ValueError):
            return None, 'Enter a valid medical record date.'

        has_content = any(
            (data.get(field) or '').strip()
            for field in (
                'complaint', 'diagnosis', 'treatment_prescribed',
                'medication_details', 'notes',
            )
        )
        if not has_content and not attachment_path and not attachments:
            return None, 'Enter medical details or attach a document.'

        record = MedicalRecord(
            inmate_id=inmate_id,
            record_date=record_date,
            record_type=record_type or 'Medical note',
            complaint=(data.get('complaint') or '').strip() or None,
            diagnosis=(data.get('diagnosis') or '').strip() or None,
            treatment_prescribed=(data.get('treatment_prescribed') or '').strip() or None,
            medication_details=(data.get('medication_details') or '').strip() or None,
            attending_medical_officer=actor.full_name,
            referred_to_hospital=data.get('referred_to_hospital') == 'on',
            hospital_name=hospital_name or None,
            notes=(data.get('notes') or '').strip() or None,
            recorded_by=actor.user_id,
            attachment_path=attachment_path,
            attachment_name=attachment_name,
            approval_status='Pending',
        )
        db.session.add(record)
        for file_path, original_name in attachments or []:
            record.attachments.append(MedicalRecordAttachment(
                file_path=file_path,
                original_name=original_name,
            ))
        db.session.commit()
        MedicalRecordService._audit(
            actor, 'Submit',
            f'Medical record for inmate {inmate.inmate_number} submitted for approval',
            record,
        )
        return record, None

    @staticmethod
    def add_attachments(actor, record_id, attachments):
        """Attach saved documents (list of (file_path, original_name)) to an existing record.
        Only the record owner or users with approval permission should call this route.
        """
        record = MedicalRecord.query.get(record_id)
        if not record:
            return False, 'Medical record not found.'

        for file_path, original_name in attachments:
            record.attachments.append(MedicalRecordAttachment(
                file_path=file_path,
                original_name=original_name,
            ))
        # If the record was previously approved, adding attachments requires re-review.
        if record.approval_status == 'Approved':
            record.approval_status = 'Pending'
            record.review_notes = None
        db.session.commit()
        MedicalRecordService._audit(
            actor, 'Attach',
            f'Added {len(attachments)} attachment(s) to medical record #{record.record_id}',
            record,
        )
        return True, None

    @staticmethod
    def pending_records(page=1, per_page=15):
        return (
            MedicalRecord.query.filter_by(approval_status='Pending')
            .order_by(MedicalRecord.created_at.desc())
            .paginate(page=page, per_page=per_page, error_out=False)
        )

    @staticmethod
    def pending_count():
        return MedicalRecord.query.filter_by(approval_status='Pending').count()

    @staticmethod
    def review(actor, record_id, approved, notes=None):
        record = MedicalRecord.query.get(record_id)
        if not record:
            return False, 'Medical record not found.'
        if record.approval_status != 'Pending':
            return False, f'Medical record is already {record.approval_status.lower()}.'

        record.approval_status = 'Approved' if approved else 'Rejected'
        record.reviewed_by = actor.user_id
        record.reviewed_at = datetime.utcnow()
        record.review_notes = (notes or '').strip() or None
        db.session.commit()

        inmate = record.inmate
        action = 'Approve' if approved else 'Reject'
        MedicalRecordService._audit(
            actor, action,
            f'Medical record #{record.record_id} {record.approval_status.lower()} '
            f'for inmate {inmate.inmate_number}',
            record,
        )
        return True, None

    @staticmethod
    def _audit(actor, action, description, record):
        AuditEvent.log_event(
            event_category='MedicalRecord',
            event_type=action,
            event_description=description,
            entity_type='MedicalRecord',
            entity_id=record.record_id,
            user_id=actor.user_id,
            username=actor.username,
            user_role=actor.role_name,
            success=True,
        )
        db.session.commit()
