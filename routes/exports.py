from io import BytesIO

from flask import Blueprint, abort, request, send_file
from flask_login import login_required
from sqlalchemy import or_

from models.inmate import Inmate
from models.visitor import Visitor
from services.record_export_service import (
    INMATE_EXPORT_FIELDS,
    VISITOR_EXPORT_FIELDS,
    build_export,
)
from services.rbac import require_role


exports_bp = Blueprint('exports', __name__, url_prefix='/exports')

EXPORT_ROLES = ('System Administrator', 'Warden')
EXPORT_FORMATS = ('csv', 'xlsx', 'pdf')


def _export_response(records, fields, file_format, name, title):
    if file_format not in EXPORT_FORMATS:
        abort(404)
    content, mimetype, extension = build_export(records, fields, file_format, title)
    response = send_file(
        BytesIO(content),
        mimetype=mimetype,
        as_attachment=True,
        download_name=f'{name}.{extension}',
    )
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@exports_bp.route('/inmates.<file_format>')
@login_required
@require_role(*EXPORT_ROLES)
def inmates(file_format):
    search = request.args.get('q', '').strip()
    status = request.args.get('status', '').strip() or None
    query = Inmate.query
    if search:
        like = f'%{search}%'
        query = query.filter(or_(
            Inmate.full_name.ilike(like),
            Inmate.inmate_number.ilike(like),
            Inmate.crime_category.ilike(like),
        ))
    if status:
        query = query.filter(Inmate.status == status)
    records = query.order_by(Inmate.inmate_id.desc()).all()
    return _export_response(
        records, INMATE_EXPORT_FIELDS, file_format, 'inmate_records',
        'Inmate Records',
    )


@exports_bp.route('/visitors.<file_format>')
@login_required
@require_role(*EXPORT_ROLES)
def visitors(file_format):
    search = request.args.get('q', '').strip()
    query = Visitor.query
    if search:
        like = f'%{search}%'
        query = query.filter(or_(
            Visitor.full_name.ilike(like),
            Visitor.phone_number.ilike(like),
            Visitor.visitor_number.ilike(like),
            Visitor.national_id_number.ilike(like),
            Visitor.passport_number.ilike(like),
        ))
    records = query.order_by(Visitor.visitor_id.desc()).all()
    return _export_response(
        records, VISITOR_EXPORT_FIELDS, file_format, 'visitor_records',
        'Visitor Records',
    )
