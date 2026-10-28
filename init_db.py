"""Initial schema bootstrap for beta. For future schema changes use Flask-Migrate."""
from app import app, db
with app.app_context():
    db.create_all()
print('SiteForge database schema ready')
