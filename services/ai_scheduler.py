# services/ai_scheduler.py
"""
APScheduler jobs for nightly/weekly AI tasks.
Safe-guarded against duplicate start under Flask debug reloader.
"""
# services/ai_scheduler.py
import os
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

try:
    from apscheduler.schedulers.background import BackgroundScheduler
    from apscheduler.triggers.cron import CronTrigger
    HAS_SCHEDULER = True
except Exception as e:                       # pragma: no cover
    HAS_SCHEDULER = False
    logger.warning(f'[AI] APScheduler unavailable ({e}). Manual triggers only.')

_scheduler = None


def _run_visitor_analysis(app):
    with app.app_context():
        from services.ai_visitor import VisitorAnomalyDetector
        try:
            trained = VisitorAnomalyDetector.train_model()
            if trained.get('success'):
                r = VisitorAnomalyDetector.analyze_all()
                logger.info(f'[AI] visitor analysis: {r}')
            else:
                logger.info(f'[AI] visitor analysis skipped: {trained.get("error")}')
        except Exception as e:
            logger.exception(f'[AI] visitor analysis failed: {e}')


def _run_population_forecast(app):
    with app.app_context():
        from services.ai_population import PopulationForecaster
        try:
            r = PopulationForecaster.forecast(horizon_days=30)
            logger.info(f'[AI] population forecast: {r}')
        except Exception as e:
            logger.exception(f'[AI] population forecast failed: {e}')


def _run_inmate_risk(app):
    with app.app_context():
        from services.ai_inmate_risk import InmateRiskScorer
        try:
            r = InmateRiskScorer.score_all()
            logger.info(f'[AI] inmate risk: {r}')
        except Exception as e:
            logger.exception(f'[AI] inmate risk failed: {e}')


def _run_model_retrain(app):
    with app.app_context():
        from services.ai_visitor import VisitorAnomalyDetector
        try:
            r = VisitorAnomalyDetector.train_model()
            logger.info(f'[AI] model retrain: {r}')
        except Exception as e:
            logger.exception(f'[AI] model retrain failed: {e}')


def init_scheduler(app):
    global _scheduler
    if not HAS_SCHEDULER:
        logger.info('[AI] scheduler disabled — use manual triggers on /ai')
        return
    if app.debug and os.environ.get('WERKZEUG_RUN_MAIN') != 'true':
        logger.info('[AI] scheduler not started (debug parent process)')
        return
    if _scheduler and _scheduler.running:
        return

    sched = BackgroundScheduler(timezone='Africa/Kampala')
    sched.add_job(lambda: _run_visitor_analysis(app),  CronTrigger(hour=2, minute=0),
                  id='ai_visitor', replace_existing=True)
    sched.add_job(lambda: _run_population_forecast(app), CronTrigger(hour=6, minute=0),
                  id='ai_population', replace_existing=True)
    sched.add_job(lambda: _run_inmate_risk(app),        CronTrigger(day_of_week='sun', hour=3),
                  id='ai_inmate_risk', replace_existing=True)
    sched.add_job(lambda: _run_model_retrain(app),      CronTrigger(day=1, hour=4),
                  id='ai_retrain', replace_existing=True)
    sched.start()
    _scheduler = sched
    logger.info('[AI] scheduler started with 4 jobs')

