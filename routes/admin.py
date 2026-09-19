# routes/admin.py
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, current_app)
from flask_login import login_required, current_user
from flask_wtf import FlaskForm
from wtforms import (StringField, PasswordField, SelectField,
                     BooleanField, SubmitField)
from wtforms.validators import DataRequired, Length, Email, Optional

from extensions import csrf
from services.user_service import UserService
from services.rbac import require_role


admin_bp = Blueprint('admin', __name__, url_prefix='/admin')
csrf.exempt(admin_bp)   # JSON not used here, but safe for consistency


# ---------- Forms ----------
class UserCreateForm(FlaskForm):
    full_name    = StringField('Full name', validators=[DataRequired(), Length(3, 150)])
    username     = StringField('Username', validators=[DataRequired(), Length(3, 80)])
    email        = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    phone_number = StringField('Phone number', validators=[Optional(), Length(max=20)])
    role_id      = SelectField('Role', coerce=int, validators=[DataRequired()])
    password     = PasswordField('Temporary password',
                                 validators=[DataRequired(), Length(min=8, max=128)])
    is_active    = BooleanField('Active', default=True)
    submit       = SubmitField('Create user')


class UserEditForm(FlaskForm):
    full_name    = StringField('Full name', validators=[DataRequired(), Length(3, 150)])
    email        = StringField('Email', validators=[DataRequired(), Email(), Length(max=120)])
    phone_number = StringField('Phone number', validators=[Optional(), Length(max=20)])
    role_id      = SelectField('Role', coerce=int, validators=[DataRequired()])
    is_active    = BooleanField('Active')
    submit       = SubmitField('Save changes')


class ResetPasswordForm(FlaskForm):
    new_password     = PasswordField('New temporary password',
                                     validators=[DataRequired(), Length(min=8, max=128)])
    confirm_password = PasswordField('Confirm password',
                                     validators=[DataRequired()])
    submit           = SubmitField('Reset password')


def _populate_roles(form):
    form.role_id.choices = [
        (r.role_id, r.role_name) for r in UserService.list_roles()
    ]


# ---------- List ----------
@admin_bp.route('/')
@login_required
@require_role('System Administrator')
def index():
    """Bare /admin → users list."""
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users')
@login_required
@require_role('System Administrator')
def users_list():
    search  = request.args.get('q', '').strip()
    role_id = request.args.get('role_id', type=int)
    page    = request.args.get('page', 1, type=int)

    pagination = UserService.list_users(
        search=search, role_id=role_id, page=page, per_page=15
    )

    return render_template(
        'admin/users_list.html',
        pagination=pagination,
        users=pagination.items,
        search=search,
        role_id=role_id,
        roles=UserService.list_roles(),
    )


# ---------- Create ----------
@admin_bp.route('/users/new', methods=['GET', 'POST'])
@login_required
@require_role('System Administrator')
def user_new():
    form = UserCreateForm()
    _populate_roles(form)

    if form.validate_on_submit():
        user, error = UserService.create_user(
            actor=current_user,
            username=form.username.data,
            email=form.email.data,
            full_name=form.full_name.data,
            role_id=form.role_id.data,
            password=form.password.data,
            phone_number=form.phone_number.data,
            is_active=form.is_active.data,
        )
        if error:
            flash(error, 'danger')
        else:
            flash(
                f'User "{user.username}" created. '
                f'They will enrol a fingerprint on first login.',
                'success'
            )
            return redirect(url_for('admin.users_list'))

    return render_template('admin/user_form.html', form=form, mode='create')


# ---------- Edit ----------
@admin_bp.route('/users/<int:user_id>/edit', methods=['GET', 'POST'])
@login_required
@require_role('System Administrator')
def user_edit(user_id):
    user = UserService.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.users_list'))

    form = UserEditForm(obj=user)
    _populate_roles(form)

    if request.method == 'GET':
        form.role_id.data = user.role_id
        form.is_active.data = user.is_active

    if form.validate_on_submit():
        _, error = UserService.update_user(
            actor=current_user,
            user_id=user_id,
            full_name=form.full_name.data,
            email=form.email.data,
            phone_number=form.phone_number.data,
            role_id=form.role_id.data,
            is_active=form.is_active.data,
        )
        if error:
            flash(error, 'danger')
        else:
            flash(f'Updated user "{user.username}".', 'success')
            return redirect(url_for('admin.users_list'))

    return render_template('admin/user_form.html', form=form, mode='edit', user=user)


# ---------- Reset password ----------
@admin_bp.route('/users/<int:user_id>/reset-password', methods=['GET', 'POST'])
@login_required
@require_role('System Administrator')
def user_reset_password(user_id):
    user = UserService.get(user_id)
    if not user:
        flash('User not found.', 'danger')
        return redirect(url_for('admin.users_list'))

    form = ResetPasswordForm()
    if form.validate_on_submit():
        if form.new_password.data != form.confirm_password.data:
            flash('Passwords do not match.', 'danger')
        else:
            ok, error = UserService.admin_reset_password(
                actor=current_user,
                user_id=user_id,
                new_password=form.new_password.data,
            )
            if error:
                flash(error, 'danger')
            else:
                flash(f'Password reset for "{user.username}".', 'success')
                return redirect(url_for('admin.users_list'))

    return render_template('admin/reset_password.html', form=form, user=user)


# ---------- Actions (POST-only, redirect back) ----------
@admin_bp.route('/users/<int:user_id>/unlock', methods=['POST'])
@login_required
@require_role('System Administrator')
def user_unlock(user_id):
    ok, error = UserService.unlock_account(current_user, user_id)
    flash(error or 'Account unlocked.', 'danger' if error else 'success')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/toggle-active', methods=['POST'])
@login_required
@require_role('System Administrator')
def user_toggle_active(user_id):
    ok, error = UserService.toggle_active(
        actor=current_user, user_id=user_id, actor_id=current_user.user_id
    )
    flash(error or 'User status updated.', 'danger' if error else 'success')
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/reset-biometric', methods=['POST'])
@login_required
@require_role('System Administrator')
def user_reset_biometric(user_id):
    ok, error = UserService.reset_biometric(current_user, user_id)
    flash(
        error or 'Fingerprint reset. User will re-enrol on next login.',
        'danger' if error else 'success'
    )
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@require_role('System Administrator')
def user_delete(user_id):
    ok, error = UserService.delete_user(
        actor=current_user, user_id=user_id, actor_id=current_user.user_id
    )
    flash(error or 'User deleted.', 'danger' if error else 'success')
    return redirect(url_for('admin.users_list'))