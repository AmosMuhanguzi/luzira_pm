# =====================================================
# scheduled_tasks.py - AI Scheduled Tasks
# =====================================================

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from datetime import datetime
import logging

from ai_service import VisitorAnomalyDetector, PopulationForecaster, InmateRiskProfiler
from models import db, Visitor, Inmate, Notification

logger = logging.getLogger(__name__)

scheduler = BackgroundScheduler()


def nightly_visitor_analysis():
    """
    Run nightly analysis of all visitors for anomalies
    """
    logger.info("Starting nightly visitor anomaly analysis")
    
    with scheduler.app.app_context():
        # Get all visitors with sufficient history
        visitors = Visitor.query.filter(
            Visitor.total_visits >= 3
        ).all()
        
        anomalies_detected = 0
        
        for visitor in visitors:
            try:
                result = VisitorAnomalyDetector.analyze_visitor(visitor.visitor_id)
                
                if result.get('is_anomaly'):
                    anomalies_detected += 1
                    
                    # Create notification for high/critical anomalies
                    if result['severity'] in ['High', 'Critical']:
                        Notification.create_ai_alert(
                            title=f"Visitor Anomaly: {visitor.full_name}",
                            message=result['reason'],
                            related_entity_type='Visitor',
                            related_entity_id=visitor.visitor_id,
                            severity=result['severity']
                        )
                        
            except Exception as e:
                logger.error(f"Error analyzing visitor {visitor.visitor_id}: {e}")
        
        logger.info(f"Completed visitor analysis. Anomalies detected: {anomalies_detected}")


def daily_population_forecast():
    """
    Generate daily population forecast
    """
    logger.info("Starting daily population forecast")
    
    with scheduler.app.app_context():
        try:
            result = PopulationForecaster.forecast_population(forecast_days=30)
            
            if result['overcrowding_risk'] in ['High', 'Critical']:
                Notification.create_ai_alert(
                    title="Population Alert",
                    message=f"Overcrowding risk: {result['overcrowding_risk']}. "
                            f"Predicted population: {result['predicted_population']}",
                    related_entity_type='Facility',
                    related_entity_id=None,
                    severity='High' if result['overcrowding_risk'] == 'High' else 'Critical'
                )
                
            logger.info(f"Population forecast: {result}")
            
        except Exception as e:
            logger.error(f"Error generating population forecast: {e}")


def weekly_risk_profiling():
    """
    Run weekly risk profiling for all active inmates
    """
    logger.info("Starting weekly inmate risk profiling")
    
    with scheduler.app.app_context():
        inmates = Inmate.query.filter_by(status='Active').all()
        
        for inmate in inmates:
            try:
                InmateRiskProfiler.calculate_risk_score(inmate.inmate_id)
            except Exception as e:
                logger.error(f"Error profiling inmate {inmate.inmate_id}: {e}")
        
        logger.info(f"Completed risk profiling for {len(inmates)} inmates")


def retrain_anomaly_model():
    """
    Retrain the anomaly detection model with latest data
    """
    logger.info("Starting model retraining")
    
    with scheduler.app.app_context():
        try:
            VisitorAnomalyDetector.train_model()
            logger.info("Model retrained successfully")
        except Exception as e:
            logger.error(f"Error retraining model: {e}")


def init_scheduler(app):
    """
    Initialize and start the scheduler
    """
    scheduler.app = app
    
    # Nightly visitor analysis at 2:00 AM
    scheduler.add_job(
        nightly_visitor_analysis,
        CronTrigger(hour=2, minute=0),
        id='nightly_visitor_analysis',
        replace_existing=True
    )
    
    # Daily population forecast at 6:00 AM
    scheduler.add_job(
        daily_population_forecast,
        CronTrigger(hour=6, minute=0),
        id='daily_population_forecast',
        replace_existing=True
    )
    
    # Weekly risk profiling on Sunday at 3:00 AM
    scheduler.add_job(
        weekly_risk_profiling,
        CronTrigger(day_of_week='sun', hour=3, minute=0),
        id='weekly_risk_profiling',
        replace_existing=True
    )
    
    # Monthly model retraining on 1st at 4:00 AM
    scheduler.add_job(
        retrain_anomaly_model,
        CronTrigger(day=1, hour=4, minute=0),
        id='monthly_model_retrain',
        replace_existing=True
    )
    
    scheduler.start()
    logger.info("Scheduler started with 4 jobs")