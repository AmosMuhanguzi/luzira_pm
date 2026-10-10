import unittest
from datetime import date, datetime, time, timedelta
from pathlib import Path
from flask import Flask
from flask_login import LoginManager, UserMixin
from types import SimpleNamespace
from unittest.mock import patch

from extensions import db
from services.report_service import (
    month_segments, period_bounds, summarize_period, undated_death_count,
)


class ReportTestUser(UserMixin):
    def __init__(self, role_name):
        self.user_id = role_name
        self.role_name = role_name
        self.role = SimpleNamespace(role_name=role_name)

    def get_id(self):
        return self.user_id


class ReportServiceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template_folder = Path(__file__).resolve().parent.parent / 'templates'
        cls.app = Flask(__name__, template_folder=str(template_folder))
        cls.app.config['SECRET_KEY'] = 'test-secret'
        cls.app.config.update(
            SQLALCHEMY_DATABASE_URI='sqlite://',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        with cls.app.app_context():
            from models import (  # noqa: F401
                AdmissionEpisode, AuditEvent, Inmate, VisitLog, Visitor,
            )
            from models.visitor import VisitorBlacklistEvent  # noqa: F401

            db.create_all()
        cls.login_manager = LoginManager()
        cls.login_manager.login_view = '/login'
        cls.login_manager.user_loader(lambda user_id: ReportTestUser(user_id))
        cls.login_manager.init_app(cls.app)
        from routes.report import reports_bp

        cls.app.register_blueprint(reports_bp)

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def test_month_segments_cover_calendar_weeks(self):
        segments = month_segments(2026, 2)

        self.assertEqual(segments[0][0], date(2026, 2, 1))
        self.assertEqual(segments[-1][1], date(2026, 2, 28))
        self.assertTrue(all(
            segments[index][1] + timedelta(days=1) == segments[index + 1][0]
            for index in range(len(segments) - 1)
        ))
        self.assertTrue(all(
            segment_end.weekday() == 6 for _, segment_end in segments[:-1]
        ))

    def test_period_bounds_handles_leap_month(self):
        self.assertEqual(
            period_bounds(2024, 2),
            (date(2024, 2, 1), date(2024, 2, 29)),
        )

    def test_reports_template_compiles(self):
        with self.app.app_context():
            self.app.jinja_env.get_template('admin/reports.html')

    def test_summary_counts_events_inclusive_of_end_date(self):
        start = date(2026, 3, 2)
        end = date(2026, 3, 8)
        with self.app.app_context():
            from models import AdmissionEpisode, AuditEvent, Inmate, VisitLog, Visitor
            from models.visitor import VisitorBlacklistEvent

            db.drop_all()
            db.create_all()
            inmate = Inmate(
                inmate_number='LZR-REPORT-1',
                full_name='Report Test Inmate',
                date_of_birth=date(1990, 1, 1),
                gender='Male',
                nationality='Ugandan',
                current_admission_date=start,
            )
            visitor = Visitor(full_name='Report Test Visitor', phone_number='0700000000')
            db.session.add_all([inmate, visitor])
            db.session.flush()
            db.session.add(AdmissionEpisode(
                inmate_id=inmate.inmate_id,
                admission_date=start,
                admission_type='New',
                release_date=end,
                release_type='Transfer',
                is_current=False,
            ))
            db.session.add(VisitLog(
                visitor_id=visitor.visitor_id,
                inmate_id=inmate.inmate_id,
                check_in_time=datetime.combine(end, time(23, 59)),
                anomaly_flag=True,
            ))
            db.session.add(VisitorBlacklistEvent(
                visitor_id=visitor.visitor_id,
                action='Blocked',
                reason='Test event',
                event_at=datetime.combine(end, time(23, 59)),
            ))
            db.session.add(AuditEvent(
                event_category='Inmate',
                event_type='Death',
                event_description='Inmate death recorded',
                entity_type='Inmate',
                entity_id=inmate.inmate_id,
                new_values='{"status": "Deceased"}',
                event_timestamp=datetime.combine(end, time(23, 59)),
            ))
            db.session.add(AuditEvent(
                event_category='Inmate',
                event_type='Death',
                event_description='Duplicate status event',
                entity_type='Inmate',
                entity_id=inmate.inmate_id,
                new_values='{"status": "Deceased"}',
                event_timestamp=datetime.combine(end + timedelta(days=1), time.min),
            ))
            db.session.commit()

            summary = summarize_period(start, end)
            values = {metric['label']: metric['value'] for metric in summary['metrics']}

            self.assertEqual(values['Inmate intakes'], 1)
            self.assertEqual(values['Inmate deaths recorded'], 1)
            self.assertEqual(values['Visits'], 1)
            self.assertEqual(values['Unique visitors'], 1)
            self.assertEqual(values['Inmates visited'], 1)
            self.assertEqual(values['Flagged visits'], 1)
            self.assertEqual(values['Blocked visitors'], 1)
            self.assertEqual(values['Total inmate transfers'], 1)
            self.assertEqual(summary['total_audit_events'], 1)

    def test_deaths_use_recorded_date_of_death(self):
        with self.app.app_context():
            from models import Inmate

            db.drop_all()
            db.create_all()
            for number, died in (('D-1', date(2026, 3, 5)), ('D-2', date(2026, 4, 1)), ('D-3', None)):
                db.session.add(Inmate(
                    inmate_number=number,
                    full_name=number,
                    date_of_birth=date(1990, 1, 1),
                    gender='Male',
                    nationality='Ugandan',
                    status='Deceased',
                    date_of_death=died,
                ))
            db.session.commit()

            march = summarize_period(date(2026, 3, 1), date(2026, 3, 31))
            values = {m['label']: m['value'] for m in march['metrics']}
            self.assertEqual(values['Inmate deaths recorded'], 1)
            self.assertEqual(undated_death_count(), 1)

    def test_reports_require_system_administrator_role(self):
        from flask import Response

        client = self.app.test_client()
        with client.session_transaction() as session:
            session['_user_id'] = 'Warden'
            session['_fresh'] = True
        self.assertEqual(client.get('/admin/reports/').status_code, 403)

        admin_client = self.app.test_client()
        with admin_client.session_transaction() as session:
            session['_user_id'] = 'System Administrator'
            session['_fresh'] = True
        with patch('routes.report.render_template', return_value=Response('ok')):
            self.assertEqual(admin_client.get('/admin/reports/').status_code, 200)


if __name__ == '__main__':
    unittest.main()
