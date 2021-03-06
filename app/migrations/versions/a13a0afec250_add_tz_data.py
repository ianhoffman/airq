"""Add tz data

Revision ID: a13a0afec250
Revises: c3dfa49541af
Create Date: 2020-09-14 00:30:02.507570

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "a13a0afec250"
down_revision = "c3dfa49541af"
branch_labels = None
depends_on = None


def upgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.add_column("zipcodes", sa.Column("timezone", sa.String(), nullable=True))
    # ### end Alembic commands ###


def downgrade():
    # ### commands auto generated by Alembic - please adjust! ###
    op.drop_column("zipcodes", "timezone")
    # ### end Alembic commands ###
