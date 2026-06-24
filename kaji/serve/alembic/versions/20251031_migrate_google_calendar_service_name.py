"""migrate google_calendar to googleCalendar

Revision ID: 20251031_migrate_gc
Revises: 825310236a51
Create Date: 2025-10-31

"""

from alembic import op


# revision identifiers, used by Alembic.
revision = "20251031_migrate_gc"
down_revision = "825310236a51"
branch_labels = None
depends_on = None


def upgrade():
    """Migrate google_calendar service name to googleCalendar for consistency."""
    # Update existing records from google_calendar to googleCalendar
    op.execute(
        """
        UPDATE integrations 
        SET service = 'googleCalendar' 
        WHERE service = 'google_calendar'
        """
    )


def downgrade():
    """Revert googleCalendar service name back to google_calendar."""
    # Revert records from googleCalendar to google_calendar
    op.execute(
        """
        UPDATE integrations 
        SET service = 'google_calendar' 
        WHERE service = 'googleCalendar'
        """
    )
