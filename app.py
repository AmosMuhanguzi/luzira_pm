import os
import importlib
from flask import Flask, app
from extensions import db  # or wherever your db instance is defined
from flask_migrate import Migrate
from flask import Flask, jsonify
from config import config
from extensions import db, login_manager, migrate, csrf, jwt


def create_app(config_name=None):
    config_name = config_name or os.environ.get('FLASK_ENV', 'development')

    app = Flask(__name__, instance_relative_config=True)
    app.config.from_object(config[config_name])

    os.makedirs(app.instance_path, exist_ok=True)

    migrate = Migrate(app, db)

    # ---- Extensions ----
    db.init_app(app)
    migrate.init_app(app)
    login_manager.init_app(app)
    jwt.init_app(app)
    csrf.init_app(app)

    # ---- Import models so SQLAlchemy registers them ----
    with app.app_context():
        from models import (  # noqa: F401
            Role, UserAccount, Inmate, AdmissionEpisode,
            Visitor, VisitLog, MedicalRecord, DisciplinaryLog,
            AIAnalysisLog, VisitorPattern, PopulationForecast,
            AuditEvent, Notification, SystemSetting,
        )

    # ---- AI scheduler ----
    from services.ai_scheduler import init_scheduler
    init_scheduler(app)

    # ---- Flask-Login user loader ----
    from models.user import UserAccount

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(UserAccount, int(user_id))

    # ---- Register blueprints ----
    from routes.auth import auth_bp
    app.register_blueprint(auth_bp)

    from routes.admin import admin_bp          
    app.register_blueprint(admin_bp) 

    from routes.inmate import inmate_bp          
    app.register_blueprint(inmate_bp)  

    from routes.medical_records import medical_records_bp
    app.register_blueprint(medical_records_bp)

    from routes.edit_requests import edit_bp        
    app.register_blueprint(edit_bp) 

    from routes.visitor import visitor_bp       
    app.register_blueprint(visitor_bp)  

    from routes.exports import exports_bp
    app.register_blueprint(exports_bp)

    from routes.ai import ai_bp                    
    app.register_blueprint(ai_bp)


    from routes.api import api_bp
    # FIX: Add url_prefix='/api' here
    app.register_blueprint(api_bp, url_prefix='/api')

    # Additional required blueprints based on proposal scope
    try:
        receptionist_module = importlib.import_module('routes.receptionist')
        receptionist_bp = receptionist_module.receptionist_bp
        app.register_blueprint(receptionist_bp)
    except ImportError:
        pass

    try:
        from api_routes import api_bp
        app.register_blueprint(api_bp)
    except ImportError:
        pass

    # ---- Jinja helpers ----
    from services.rbac import has_permission, Permissions
    from services.edit_request_service import EditRequestService
    from services.medical_record_service import MedicalRecordService

    app.jinja_env.globals['has_permission'] = has_permission
    app.jinja_env.globals['Permissions'] = Permissions
    app.jinja_env.globals['pending_edit_count'] = EditRequestService.pending_count
    app.jinja_env.globals['pending_medical_record_count'] = MedicalRecordService.pending_count

    # ---- Health check ----
    @app.route('/health')
    def health():
        return jsonify({'status': 'ok', 'facility': app.config.get('FACILITY_NAME', 'Luzira Prison')})

    return app


if __name__ == '__main__':
    app = create_app()
    app.run(debug=True, host='127.0.0.1', port=5000)