from datetime import date
from pathlib import Path

from flask import (
    Blueprint, abort, current_app, flash, redirect, render_template,
    request, send_from_directory, url_for,
)
from flask_login import current_user, login_required

from extensions import csrf
from services.medical_record_service import MedicalRecordService
from services.rbac import Permissions, has_permission, require_permission


medical_records_bp = Blueprint('medical_records', __name__, url_prefix='/medical-records')
csrf.exempt(medical_records_bp)


@medical_records_bp.route('/inmate/<int:inmate_id>/new', methods=['GET', 'POST'])
@login_required
@require_permission(Permissions.MEDICAL_RECORD_CREATE)
def new_for_inmate(inmate_id):
    from models.inmate import Inmate

    inmate = Inmate.query.get_or_404(inmate_id)
    data = request.form.to_dict() if request.method == 'POST' else {}
    if request.method == 'POST':
        uploads = request.files.getlist('attachments')
        if not uploads:
            uploads = [request.files.get('attachment')]
        attachments, upload_error = MedicalRecordService.save_documents(
            uploads, inmate_id=inmate_id
        )
        if upload_error:
            flash(upload_error, 'danger')
            return render_template(
                'inmate/medical.html', inmate=inmate, data=data,
                record_date=date.today().isoformat(),
            )

        record, error = MedicalRecordService.submit_record(
            current_user,
            inmate_id,
            data,
            attachments=attachments,
        )
        if error:
            for path, _ in attachments:
                MedicalRecordService.delete_document(path)
            flash(error, 'danger')
            return render_template(
                'inmate/medical.html', inmate=inmate, data=data,
                record_date=date.today().isoformat(),
            )

        flash('Medical record submitted for administrator approval.', 'success')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    return render_template(
        'inmate/medical.html', inmate=inmate, data={},
        record_date=date.today().isoformat(),
    )


@medical_records_bp.route('/inmate/<int:inmate_id>/<int:record_id>/file')
@login_required
@require_permission(Permissions.MEDICAL_RECORD_VIEW)
def download(inmate_id, record_id):
    from models.medical import MedicalRecord

    record = MedicalRecord.query.filter_by(
        record_id=record_id, inmate_id=inmate_id
    ).first_or_404()
    if not record.attachment_path:
        abort(404)
    if (
        record.approval_status != 'Approved'
        and record.recorded_by != current_user.user_id
        and not has_permission(Permissions.MEDICAL_RECORD_APPROVE)
    ):
        abort(404)

    storage_root = (Path(current_app.instance_path) / 'medical_records').resolve()
    path = (storage_root / record.attachment_path).resolve()
    if storage_root not in path.parents or not path.is_file():
        abort(404)
    response = send_from_directory(
        str(path.parent),
        path.name,
        as_attachment=False,
        download_name=record.attachment_name or path.name,
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response


@medical_records_bp.route(
    '/inmate/<int:inmate_id>/<int:record_id>/files/<int:attachment_id>'
)
@login_required
@require_permission(Permissions.MEDICAL_RECORD_VIEW)
def download_attachment(inmate_id, record_id, attachment_id):
    from models.medical import MedicalRecord, MedicalRecordAttachment

    record = MedicalRecord.query.filter_by(
        record_id=record_id, inmate_id=inmate_id
    ).first_or_404()
    attachment = MedicalRecordAttachment.query.filter_by(
        attachment_id=attachment_id,
        medical_record_id=record_id,
    ).first_or_404()
    if (
        record.approval_status != 'Approved'
        and record.recorded_by != current_user.user_id
        and not has_permission(Permissions.MEDICAL_RECORD_APPROVE)
    ):
        abort(404)

    storage_root = (Path(current_app.instance_path) / 'medical_records').resolve()
    path = (storage_root / attachment.file_path).resolve()
    if storage_root not in path.parents or not path.is_file():
        abort(404)
    response = send_from_directory(
        str(path.parent),
        path.name,
        as_attachment=False,
        download_name=attachment.original_name,
    )
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Content-Security-Policy'] = "sandbox; default-src 'none'"
    return response


@medical_records_bp.route('/inmate/<int:inmate_id>/<int:record_id>/add-attachments', methods=['POST'])
@login_required
@require_permission(Permissions.MEDICAL_RECORD_CREATE)
def add_attachments(inmate_id, record_id):
    from models.medical import MedicalRecord

    record = MedicalRecord.query.filter_by(
        record_id=record_id, inmate_id=inmate_id
    ).first_or_404()
    # Only the original recorder or an approver may add attachments here
    if record.recorded_by != current_user.user_id and not has_permission(Permissions.MEDICAL_RECORD_APPROVE):
        abort(403)

    uploads = request.files.getlist('attachments')
    if not uploads or not any(f and f.filename for f in uploads):
        flash('No files selected for upload.', 'warning')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    attachments, upload_error = MedicalRecordService.save_documents(uploads, inmate_id=inmate_id)
    if upload_error:
        flash(upload_error, 'danger')
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    ok, error = MedicalRecordService.add_attachments(current_user, record_id, attachments)
    if not ok:
        for path, _ in attachments:
            MedicalRecordService.delete_document(path)
        flash(error or 'Unable to attach files.', 'danger')
    else:
        flash('Attachments added to medical record.', 'success')

    return redirect(url_for('inmate.detail', inmate_id=inmate_id))


@medical_records_bp.route('/pending')
@login_required
@require_permission(Permissions.MEDICAL_RECORD_APPROVE)
def pending():
    page = request.args.get('page', 1, type=int)
    pagination = MedicalRecordService.pending_records(page=page, per_page=20)
    return render_template(
        'medical_records/pending.html',
        pagination=pagination,
        records=pagination.items,
    )


@medical_records_bp.route('/<int:record_id>/approve', methods=['POST'])
@login_required
@require_permission(Permissions.MEDICAL_RECORD_APPROVE)
def approve(record_id):
    ok, error = MedicalRecordService.review(
        current_user, record_id, approved=True,
        notes=request.form.get('notes'),
    )
    if ok:
        flash(f'Medical record #{record_id} approved.', 'success')
    else:
        flash(error, 'danger')
    return redirect(url_for('medical_records.pending'))


@medical_records_bp.route('/<int:record_id>/reject', methods=['POST'])
@login_required
@require_permission(Permissions.MEDICAL_RECORD_APPROVE)
def reject(record_id):
    notes = (request.form.get('notes') or '').strip()
    if not notes:
        flash('A reason is required when rejecting a medical record.', 'warning')
        return redirect(url_for('medical_records.pending'))
    ok, error = MedicalRecordService.review(
        current_user, record_id, approved=False, notes=notes,
    )
    if ok:
        flash(f'Medical record #{record_id} rejected.', 'info')
    else:
        flash(error, 'danger')
    return redirect(url_for('medical_records.pending'))
