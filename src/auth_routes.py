"""
Authentication routes
======================
Signup / login / logout. Passwords are hashed with
werkzeug.security (PBKDF2) and never stored or logged in plaintext.
Sessions are handled by Flask-Login.
"""

from flask import Blueprint, flash, redirect, render_template, url_for
from flask_login import login_required, login_user, logout_user

from src.forms import LoginForm, SignupForm
from src.models import User, db

bp = Blueprint("auth", __name__, url_prefix="/auth")


@bp.route("/signup", methods=["GET", "POST"])
def signup():
    form = SignupForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        if User.query.filter_by(email=email).first():
            flash("An account with that email already exists.", "error")
            return render_template("auth/signup.html", form=form)

        user = User(email=email, name=form.name.data.strip())
        user.set_password(form.password.data)
        db.session.add(user)
        db.session.commit()

        login_user(user)
        flash("Welcome! Create a stokvel group or join one with an invite code to get started.", "success")
        return redirect(url_for("groups.index"))

    return render_template("auth/signup.html", form=form)


@bp.route("/login", methods=["GET", "POST"])
def login():
    form = LoginForm()
    if form.validate_on_submit():
        email = form.email.data.strip().lower()
        user = User.query.filter_by(email=email).first()
        if user is None or not user.check_password(form.password.data):
            flash("Incorrect email or password.", "error")
            return render_template("auth/login.html", form=form)

        login_user(user)
        flash(f"Welcome back, {user.name}.", "success")
        return redirect(url_for("overview"))

    return render_template("auth/login.html", form=form)


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("Logged out.", "success")
    return redirect(url_for("auth.login"))
