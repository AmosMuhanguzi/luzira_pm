# =====================================================
# api_routes.py - Complete API Endpoint Reference
# =====================================================

"""
AUTHENTICATION ENDPOINTS
========================
POST   /api/auth/login              - User login
POST   /api/auth/logout             - User logout
POST   /api/auth/refresh            - Refresh JWT token
POST   /api/auth/change-password    - Change password
GET    /api/auth/me                 - Get current user info

INMATE ENDPOINTS
================
GET    /api/inmates                 - List all inmates (paginated)
POST   /api/inmates                 - Create new inmate
GET    /api/inmates/<id>            - Get inmate details
PUT    /api/inmates/<id>            - Update inmate
DELETE /api/inmates/<id>            - Delete inmate (admin only)
GET    /api/inmates/<id>/episodes   - Get admission history
POST   /api/inmates/<id>/episodes   - Create new admission episode
GET    /api/inmates/<id>/medical    - Get medical records
POST   /api/inmates/<id>/medical    - Add medical record
GET    /api/inmates/<id>/disciplinary - Get disciplinary logs
POST   /api/inmates/<id>/disciplinary - Add disciplinary log
GET    /api/inmates/search          - Search inmates
GET    /api/inmates/<id>/risk       - Get risk assessment

BIOMETRIC ENDPOINTS
===================
POST   /api/biometric/identify      - 1:N identification (inmate/visitor)
POST   /api/biometric/verify        - 1:1 verification
POST   /api/biometric/enroll/inmate/<id>  - Enroll inmate fingerprint
POST   /api/biometric/enroll/visitor/<id> - Enroll visitor fingerprint
GET    /api/biometric/status        - Get scanner status

VISITOR ENDPOINTS
=================
GET    /api/visitors                - List all visitors
POST   /api/visitors                - Register new visitor
GET    /api/visitors/<id>           - Get visitor details
PUT    /api/visitors/<id>           - Update visitor
GET    /api/visitors/<id>/history   - Get visit history
POST   /api/visitors/<id>/blacklist - Blacklist visitor
DELETE /api/visitors/<id>/blacklist - Remove from blacklist
GET    /api/visitors/search         - Search visitors

VISIT ENDPOINTS
===============
GET    /api/visits                  - List all visits
POST   /api/visits                  - Create visit log
GET    /api/visits/<id>             - Get visit details
PUT    /api/visits/<id>             - Update visit
POST   /api/visits/<id>/checkout    - Check out visitor
GET    /api/visits/today            - Today's visits
GET    /api/visits/pending          - Pending visits

AI ENDPOINTS
============
GET    /api/ai/alerts               - Get AI alerts
POST   /api/ai/alerts/<id>/review   - Mark alert as reviewed
POST   /api/ai/analyze/visitor/<id> - Analyze specific visitor
POST   /api/ai/analyze/all          - Run full analysis
GET    /api/ai/forecast             - Get population forecast
POST   /api/ai/train                - Retrain AI model
GET    /api/ai/risk/<inmate_id>     - Get inmate risk profile

REPORT ENDPOINTS
================
GET    /api/reports/population      - Population report
GET    /api/reports/visitors        - Visitor report
GET    /api/reports/incidents       - Incident report
GET    /api/reports/admissions      - Admissions report
GET    /api/reports/export/pdf      - Export report as PDF
GET    /api/reports/export/excel    - Export report as Excel

ADMIN ENDPOINTS
===============
GET    /api/admin/users             - List all users
POST   /api/admin/users             - Create user
PUT    /api/admin/users/<id>        - Update user
DELETE /api/admin/users/<id>        - Delete user
POST   /api/admin/users/<id>/reset-password - Reset password
GET    /api/admin/audit             - Get audit log
GET    /api/admin/settings          - Get system settings
PUT    /api/admin/settings          - Update settings
POST   /api/admin/backup            - Create backup
GET    /api/admin/stats             - System statistics
"""