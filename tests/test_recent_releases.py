import unittest
from datetime import date, datetime

from flask import Flask

from extensions import db
from models import Inmate, Role, UserAccount
from models.inmate import AdmissionEpisode
from services.inmate_service import InmateService


class RecentReleasesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask(__name__)
        cls.app.config.update(
            SECRET_KEY='test-secret',
            SQLALCHEMY_DATABASE_URI='sqlite://',
            SQLALCHEMY_TRACK_MODIFICATIONS=False,
        )
        db.init_app(cls.app)
        with cls.app.app_context():
            import models  # noqa: F401
            db.create_all()

    @classmethod
    def tearDownClass(cls):
        with cls.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def setUp(self):
        self.context = self.app.app_context()
        self.context.push()
        db.drop_all()
        db.create_all()

        role = Role(role_name='System Administrator')
        db.session.add(role)
        db.session.flush()
        self.officer = UserAccount(
            username='officer-1',
            email='officer-1@example.invalid',
            password_hash='test',
            full_name='Officer One',
            role_id=role.role_id,
        )
        db.session.add(self.officer)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        self.context.pop()

    def _make_released_inmate(self, name, release_date, released_at, is_current=False):
        inmate = Inmate(
            inmate_number=f'IN-{name}',
            full_name=name,
            date_of_birth=date(1990, 1, 1),
            gender='Male',
            nationality='Ugandan',
            status='Released',
            actual_release_date=release_date,
        )
        db.session.add(inmate)
        db.session.flush()
        episode = AdmissionEpisode(
            inmate_id=inmate.inmate_id,
            admission_date=date(2020, 1, 1),
            admission_type='New',
            release_date=release_date,
            release_type='Completed Sentence',
            released_at=released_at,
            releasing_officer_id=self.officer.user_id,
            is_current=is_current,
        )
        db.session.add(episode)
        db.session.commit()
        return inmate, episode

    def test_recent_releases_returns_most_recent_first_limited(self):
        for i in range(7):
            self._make_released_inmate(
                f'Inmate{i}',
                date(2024, 1, i + 1),
                datetime(2024, 1, i + 1, 10, 0, 0),
            )

        results = InmateService.recent_releases(limit=5)
        self.assertEqual(len(results), 5)
        release_dates = [r.release_date for r in results]
        self.assertEqual(release_dates, sorted(release_dates, reverse=True))
        self.assertEqual(results[0].release_date, date(2024, 1, 7))

    def test_recent_releases_excludes_current_episodes(self):
        self._make_released_inmate(
            'Active', date(2024, 1, 1), datetime(2024, 1, 1, 9, 0, 0), is_current=True
        )
        self._make_released_inmate(
            'Released', date(2024, 1, 2), datetime(2024, 1, 2, 9, 0, 0), is_current=False
        )

        results = InmateService.recent_releases(limit=5)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].inmate.full_name, 'Released')


if __name__ == '__main__':
    unittest.main()
