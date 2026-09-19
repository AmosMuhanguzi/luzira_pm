# =====================================================
# biometric_service.py - Flask Backend Biometric Service
# =====================================================

import base64
import hashlib
import logging
from datetime import datetime
from models import db, Inmate, Visitor, AuditEvent, BiometricEnrollment

class BiometricMatcher:
    """
    1:N fingerprint matching service
    """
    
    MATCH_THRESHOLD = 75  # Configurable confidence threshold
    
    @staticmethod
    def compare_templates(template1, template2):
        """
        Compare two fingerprint templates
        Returns: similarity score (0-100)
        
        In production: Use SDK comparison function
        For prototype: Implement basic comparison
        """
        # Decode base64 if needed
        if isinstance(template1, str):
            template1 = base64.b64decode(template1)
        if isinstance(template2, str):
            template2 = base64.b64decode(template2)
        
        # Production implementation would use:
        # - pyfingerprint sensor.compareCharacteristics()
        # - DigitalPersona SDK comparison
        # - python-fingerprint-recognition library
        
        # Simplified comparison for prototype
        # Compare byte patterns (NOT production-grade)
        if len(template1) != len(template2):
            return 0
        
        matching_bytes = sum(1 for a, b in zip(template1, template2) if a == b)
        similarity = (matching_bytes / len(template1)) * 100
        
        return similarity
    
    @staticmethod
    def identify_inmate(probe_template, threshold=None):
        """
        1:N identification against all enrolled inmates
        
        Args:
            probe_template: Fingerprint template to identify
            threshold: Minimum confidence score (default: MATCH_THRESHOLD)
        
        Returns:
            dict: {
                'match': bool,
                'inmate_id': int or None,
                'inmate': Inmate object or None,
                'score': float,
                'candidates': list of top matches
            }
        """
        if threshold is None:
            threshold = BiometricMatcher.MATCH_THRESHOLD
        
        # Get all enrolled inmates
        enrolled_inmates = Inmate.query.filter_by(
            biometric_enrolled=True,
            status='Active'
        ).all()
        
        if not enrolled_inmates:
            return {
                'match': False,
                'inmate_id': None,
                'inmate': None,
                'score': 0,
                'candidates': []
            }
        
        results = []
        
        for inmate in enrolled_inmates:
            if inmate.fingerprint_template:
                score = BiometricMatcher.compare_templates(
                    probe_template,
                    inmate.fingerprint_template
                )
                results.append({
                    'inmate_id': inmate.inmate_id,
                    'inmate': inmate,
                    'score': score
                })
        
        # Sort by score descending
        results.sort(key=lambda x: x['score'], reverse=True)
        
        # Get top candidates (for manual review if needed)
        top_candidates = results[:5]
        
        # Check if best match exceeds threshold
        if results and results[0]['score'] >= threshold:
            best_match = results[0]
            return {
                'match': True,
                'inmate_id': best_match['inmate_id'],
                'inmate': best_match['inmate'],
                'score': best_match['score'],
                'candidates': top_candidates
            }
        else:
            return {
                'match': False,
                'inmate_id': None,
                'inmate': None,
                'score': results[0]['score'] if results else 0,
                'candidates': top_candidates
            }
    
    @staticmethod
    def identify_visitor(probe_template, threshold=None):
        """
        1:N identification against all enrolled visitors
        """
        if threshold is None:
            threshold = BiometricMatcher.MATCH_THRESHOLD
        
        enrolled_visitors = Visitor.query.filter_by(
            biometric_enrolled=True,
            is_blacklisted=False
        ).all()
        
        if not enrolled_visitors:
            return {
                'match': False,
                'visitor_id': None,
                'visitor': None,
                'score': 0
            }
        
        results = []
        
        for visitor in enrolled_visitors:
            if visitor.fingerprint_template:
                score = BiometricMatcher.compare_templates(
                    probe_template,
                    visitor.fingerprint_template
                )
                results.append({
                    'visitor_id': visitor.visitor_id,
                    'visitor': visitor,
                    'score': score
                })
        
        results.sort(key=lambda x: x['score'], reverse=True)
        
        if results and results[0]['score'] >= threshold:
            best_match = results[0]
            return {
                'match': True,
                'visitor_id': best_match['visitor_id'],
                'visitor': best_match['visitor'],
                'score': best_match['score']
            }
        else:
            return {
                'match': False,
                'visitor_id': None,
                'visitor': None,
                'score': results[0]['score'] if results else 0
            }


class BiometricEnrollmentService:
    """
    Service for enrolling new biometric templates
    """
    
    @staticmethod
    def enroll_inmate(inmate_id, template, quality_score, officer_id):
        """
        Enroll inmate fingerprint template
        """
        inmate = Inmate.query.get(inmate_id)
        if not inmate:
            raise ValueError(f"Inmate {inmate_id} not found")
        
        # Decode template if base64
        if isinstance(template, str):
            template = base64.b64decode(template)
        
        # Store template
        inmate.fingerprint_template = template
        inmate.biometric_enrolled = True
        inmate.biometric_enrollment_date = datetime.utcnow()
        inmate.biometric_quality_score = quality_score
        
        db.session.commit()
        
        # Audit log
        AuditEvent.log_event(
            event_category='Biometric',
            event_type='Enroll',
            event_description=f'Fingerprint enrolled for inmate {inmate.inmate_number}',
            entity_type='Inmate',
            entity_id=inmate_id,
            user_id=officer_id,
            success=True
        )
        
        return inmate
    
    @staticmethod
    def enroll_visitor(visitor_id, template, quality_score, officer_id):
        """
        Enroll visitor fingerprint template
        """
        visitor = Visitor.query.get(visitor_id)
        if not visitor:
            raise ValueError(f"Visitor {visitor_id} not found")
        
        # Decode template if base64
        if isinstance(template, str):
            template = base64.b64decode(template)
        
        # Store template
        visitor.fingerprint_template = template
        visitor.biometric_enrolled = True
        visitor.biometric_enrollment_date = datetime.utcnow()
        visitor.biometric_quality_score = quality_score
        
        db.session.commit()
        
        # Audit log
        AuditEvent.log_event(
            event_category='Biometric',
            event_type='Enroll',
            event_description=f'Fingerprint enrolled for visitor {visitor.visitor_number}',
            entity_type='Visitor',
            entity_id=visitor_id,
            user_id=officer_id,
            success=True
        )
        
        return visitor