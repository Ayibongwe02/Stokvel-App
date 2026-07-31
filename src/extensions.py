"""Shared extension instances, initialised in app.py's create_app()."""

from flask_login import LoginManager
from flask_wtf import CSRFProtect

login_manager = LoginManager()
login_manager.login_view = "auth.login"
login_manager.login_message_category = "error"

csrf = CSRFProtect()
