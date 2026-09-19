# seed.py
"""
Run once after creating the DB:
    python seed.py
"""
from app import create_app
from extensions import db
from models.user import Role, UserAccount
from models.notification import SystemSetting


def seed():
    app = create_app()

    with app.app_context():
        db.create_all()

        # ---- Roles ----
        roles_data = [
            ('System Administrator', 'Full system access and configuration'),
            ('Warden',               'Read-only + AI analytics dashboard + approvals'),
            ('Records Officer',      'Inmate records management'),
            ('Receptionist',         'Intake processing and visitor management'),
            ('Security Officer',     'Visitor verification and gate security'),
        ]
        roles = {}
        for name, desc in roles_data:
            role = Role.query.filter_by(role_name=name).first()
            if not role:
                role = Role(role_name=name, description=desc)
                db.session.add(role)
            roles[name] = role
        db.session.flush()


        # ---- Default admin ----

        if not UserAccount.query.filter_by(username='admin').first():
            admin = UserAccount(
                username='admin',
                email='admin@luzira.local',
                full_name='System Administrator',
                role_id=roles['System Administrator'].role_id,
                biometric_enrolled=False,     # force enrolment on first login
            )
            admin.set_password('Admin@2026')
            db.session.add(admin)
            print('Created admin user: admin / Admin@2026')
            print('   -> On first login you will be asked to enrol a fingerprint.')
        

        # ---- Facility settings ----
        defaults = [
            ('facility_name',          'Luzira Prison', 'string'),
            ('facility_capacity',      '3000',          'integer'),
            ('biometric_threshold',    '75',            'integer'),
            ('ai_anomaly_enabled',     'true',          'boolean'),
        ]
        for key, val, typ in defaults:
            if not SystemSetting.query.filter_by(setting_key=key).first():
                db.session.add(SystemSetting(
                    setting_key=key, setting_value=val, setting_type=typ
                ))

        db.session.commit()
        print('Database seeded successfully.')


if __name__ == '__main__':
    seed()