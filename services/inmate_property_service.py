"""Register of items/property an inmate was arrested with."""
from datetime import datetime, timezone

from extensions import db
from models.inmate import InmateProperty

MAX_ITEMS = 50
NO_PROPERTY_TEXT = 'None'


class InmatePropertyService:
    @staticmethod
    def parse_form_items(form):
        """Pair the repeated item/description inputs of an admission form."""
        names = form.getlist('property_item')
        descriptions = form.getlist('property_description')
        items = []
        for index, name in enumerate(names):
            name = (name or '').strip()
            description = (descriptions[index] if index < len(descriptions) else '')
            description = (description or '').strip()
            if name or description:
                items.append({'item_name': name, 'description': description})
        return items

    @staticmethod
    def validate_items(items):
        if len(items) > MAX_ITEMS:
            return f'Record no more than {MAX_ITEMS} property items at a time.'
        for item in items:
            if not item.get('item_name'):
                return 'Enter the item name for every property description.'
            if len(item['item_name']) > 150:
                return 'Property item names must be 150 characters or fewer.'
            if len(item.get('description') or '') > 2000:
                return 'Property descriptions must be 2000 characters or fewer.'
        return None

    @staticmethod
    def add_items(inmate_id, items, actor, episode_id=None):
        """Stage property rows; the caller commits."""
        for item in items or []:
            db.session.add(InmateProperty(
                inmate_id=inmate_id,
                episode_id=episode_id,
                item_name=item['item_name'],
                description=item.get('description') or None,
                status=InmateProperty.STATUS_IN_CUSTODY,
                recorded_by=actor.user_id,
            ))

    @staticmethod
    def in_custody(inmate_id):
        return (
            InmateProperty.query
            .filter_by(inmate_id=inmate_id, status=InmateProperty.STATUS_IN_CUSTODY)
            .order_by(InmateProperty.property_id)
            .all()
        )

    @staticmethod
    def claims_text(inmate_id):
        items = InmatePropertyService.in_custody(inmate_id)
        if not items:
            return NO_PROPERTY_TEXT
        return '\n'.join(
            f'{number}. {item.item_name}'
            + (f' - {item.description}' if item.description else '')
            for number, item in enumerate(items, start=1)
        )

    @staticmethod
    def hand_over(actor, property_id, inmate_id, recipient, relationship):
        item = InmateProperty.query.filter_by(
            property_id=property_id,
            inmate_id=inmate_id,
            status=InmateProperty.STATUS_IN_CUSTODY,
        ).first()
        if not item:
            return None, 'This item is no longer held in custody.'
        recipient = (recipient or '').strip()
        relationship = (relationship or '').strip()
        if not recipient or len(recipient) > 150:
            return None, 'Enter the name of the person receiving the item.'
        if len(relationship) > 80:
            return None, 'Relationship must be 80 characters or fewer.'
        item.status = InmateProperty.STATUS_HANDED_OVER
        item.handed_to_name = recipient
        item.handed_to_relationship = relationship or None
        item.handed_over_at = datetime.now(timezone.utc).replace(tzinfo=None)
        item.handed_over_by = actor.user_id
        return item, None

    @staticmethod
    def mark_returned_on_release(inmate_id, actor):
        """Items still held at discharge leave the register; the caller commits."""
        now = datetime.now(timezone.utc).replace(tzinfo=None)
        for item in InmatePropertyService.in_custody(inmate_id):
            item.status = InmateProperty.STATUS_RETURNED
            item.handed_over_at = now
            item.handed_over_by = actor.user_id
