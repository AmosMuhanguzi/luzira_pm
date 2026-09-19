# routes/edit_requests.py
from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user

from extensions import csrf
from services.rbac import require_permission, Permissions
from services.inmate_service import InmateService
from services.edit_request_service import EditRequestService
from models.inmate import Inmate
from models.edit_request import EditRequest


edit_bp = Blueprint('edit_requests', __name__)
csrf.exempt(edit_bp)


# ---------- Requester: edit form for an inmate ----------
@edit_bp.route('/inmate/<int:inmate_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission(Permissions.INMATE_EDIT_REQUEST)
def inmate_edit(inmate_id):
    inmate = InmateService.get(inmate_id)
    if not inmate:
        flash('Inmate not found.', 'danger')
        return redirect(url_for('inmate.list_inmates'))

    if request.method == 'POST':
        data = request.form.to_dict()
        reason = data.pop('request_reason', None)

        # Admin bypasses the queue
        from services.rbac import has_permission
        if has_permission(Permissions.INMATE_EDIT_APPROVE):
            req, error = EditRequestService.submit_inmate_edit(
                actor=current_user, inmate_id=inmate_id,
                form_data=data, reason=reason,
            )
            if error:
                flash(error, 'danger')
                return render_template('inmate/edit_form.html',
                                       inmate=inmate, data=data)
            # Admin submitted → approve immediately
            ok, err = EditRequestService.approve(current_user, req.request_id,
                                                 notes='Auto-approved (admin direct edit)')
            if not ok:
                flash(err, 'danger')
            else:
                flash(f'Changes applied to {inmate.inmate_number}.', 'success')
            return redirect(url_for('inmate.detail', inmate_id=inmate_id))

        # Everyone else → queue for approval
        req, error = EditRequestService.submit_inmate_edit(
            actor=current_user, inmate_id=inmate_id,
            form_data=data, reason=reason,
        )
        if error:
            flash(error, 'danger')
            return render_template('inmate/edit_form.html',
                                   inmate=inmate, data=data)

        flash(
            f'Edit request #{req.request_id} submitted. '
            f'Waiting for administrator approval.',
            'info'
        )
        return redirect(url_for('inmate.detail', inmate_id=inmate_id))

    return render_template('inmate/edit_form.html', inmate=inmate, data={})


# ---------- Admin: list all requests ----------
@edit_bp.route('/admin/edit-requests')
@login_required
@require_permission(Permissions.INMATE_EDIT_APPROVE)
def list_requests():
    status = request.args.get('status', 'Pending').strip() or 'Pending'
    page   = request.args.get('page', 1, type=int)

    pagination = EditRequestService.list_requests(
        status=status, page=page, per_page=15
    )
    return render_template(
        'admin/edit_requests.html',
        pagination=pagination, requests=pagination.items, status=status,
    )


# ---------- Admin: view one request ----------
@edit_bp.route('/admin/edit-requests/<int:request_id>')
@login_required
@require_permission(Permissions.INMATE_EDIT_APPROVE)
def view_request(request_id):
    req = EditRequest.query.get(request_id)
    if not req:
        flash('Request not found.', 'danger')
        return redirect(url_for('edit_requests.list_requests'))

    inmate = None
    if req.target_type == 'Inmate':
        inmate = Inmate.query.get(req.target_id)

    return render_template(
        'admin/edit_request_detail.html',
        req=req, inmate=inmate,
    )


# ---------- Admin: approve ----------
@edit_bp.route('/admin/edit-requests/<int:request_id>/approve', methods=['POST'])
@login_required
@require_permission(Permissions.INMATE_EDIT_APPROVE)
def approve(request_id):
    notes = request.form.get('notes')
    ok, err = EditRequestService.approve(current_user, request_id, notes=notes)
    if ok:
        flash(f'Request #{request_id} approved. Changes applied.', 'success')
    else:
        flash(err, 'danger')
    return redirect(url_for('edit_requests.list_requests'))


# ---------- Admin: reject ----------
@edit_bp.route('/admin/edit-requests/<int:request_id>/reject', methods=['POST'])
@login_required
@require_permission(Permissions.INMATE_EDIT_APPROVE)
def reject(request_id):
    notes = request.form.get('notes')
    if not notes:
        flash('A reason is required when rejecting.', 'warning')
        return redirect(url_for('edit_requests.view_request', request_id=request_id))

    ok, err = EditRequestService.reject(current_user, request_id, notes=notes)
    if ok:
        flash(f'Request #{request_id} rejected.', 'info')
    else:
        flash(err, 'danger')
    return redirect(url_for('edit_requests.list_requests'))

# ---------- Staff: view own submitted requests ----------
@edit_bp.route('/my/edit-requests')
@login_required
@require_permission(Permissions.INMATE_EDIT_REQUEST)
def my_requests():
    from models.edit_request import EditRequest
    page = request.args.get('page', 1, type=int)

    pagination = (
        EditRequest.query
        .filter_by(requested_by=current_user.user_id)
        .order_by(EditRequest.requested_at.desc())
        .paginate(page=page, per_page=15, error_out=False)
    )

    return render_template(
        'edit_requests/my_requests.html',
        pagination=pagination, requests=pagination.items,
    )