# =====================================================
# visitor_inmate_link.py - Managing Visitor-Inmate Relationships
# =====================================================

class VisitorInmateLinkService:
    """
    Service for managing and validating visitor-inmate relationships
    """
    
    @staticmethod
    def get_authorized_visitors(inmate_id):
        """
        Get all visitors authorized to visit a specific inmate
        """
        # Get distinct visitors who have visited this inmate
        visitor_ids = db.session.query(VisitLog.visitor_id)\
            .filter_by(inmate_id=inmate_id)\
            .distinct()\
            .all()
        
        visitors = Visitor.query.filter(
            Visitor.visitor_id.in_([v[0] for v in visitor_ids]),
            Visitor.is_blacklisted == False
        ).all()
        
        return visitors
    
    @staticmethod
    def validate_visitor_inmate_relationship(visitor_id, inmate_id):
        """
        Validate that a visitor is allowed to visit an inmate
        """
        visitor = Visitor.query.get(visitor_id)
        inmate = Inmate.query.get(inmate_id)
        
        if not visitor or not inmate:
            return {'valid': False, 'reason': 'Visitor or inmate not found'}
        
        # Check if visitor is blacklisted
        if visitor.is_blacklisted:
            return {
                'valid': False,
                'reason': f'Visitor is blacklisted: {visitor.blacklist_reason}'
            }
        
        # Check if inmate is available for visits
        if inmate.status != 'Active':
            return {
                'valid': False,
                'reason': f'Inmate is not available for visits (Status: {inmate.status})'
            }
        
        # Check relationship (for high-security inmates, only certain relationships allowed)
        if inmate.security_classification == 'Maximum':
            allowed_relationships = ['Lawyer', 'Spouse', 'Parent', 'Sibling']
            if visitor.relationship_to_inmate not in allowed_relationships:
                return {
                    'valid': False,
                    'reason': f'Maximum security inmates can only receive visits from: {", ".join(allowed_relationships)}'
                }
        
        # Check visit frequency limits
        today = date.today()
        recent_visits = VisitLog.query.filter(
            VisitLog.visitor_id == visitor_id,
            VisitLog.inmate_id == inmate_id,
            VisitLog.visit_date >= today - timedelta(days=7)
        ).count()
        
        if recent_visits >= 3:
            return {
                'valid': False,
                'reason': 'Visit limit reached (maximum 3 visits per week)'
            }
        
        return {'valid': True, 'reason': None}
    
    @staticmethod
    def get_visit_statistics(inmate_id, days=30):
        """
        Get visit statistics for an inmate
        """
        start_date = date.today() - timedelta(days=days)
        
        visits = VisitLog.query.filter(
            VisitLog.inmate_id == inmate_id,
            VisitLog.visit_date >= start_date
        ).all()
        
        return {
            'total_visits': len(visits),
            'unique_visitors': len(set(v.visitor_id for v in visits)),
            'avg_duration': sum(v.visit_duration_minutes or 0 for v in visits) / len(visits) if visits else 0,
            'anomaly_count': sum(1 for v in visits if v.anomaly_flagged),
            'visits_by_type': {
                'Regular': sum(1 for v in visits if v.visit_type == 'Regular'),
                'Legal': sum(1 for v in visits if v.visit_type == 'Legal'),
                'Emergency': sum(1 for v in visits if v.visit_type == 'Emergency'),
            }
        }