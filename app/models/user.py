from app import db
from werkzeug.security import generate_password_hash, check_password_hash


class User(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(120), unique=True, nullable=False)
    # Nullable: an ORCID SSO account has no local password.
    password_hash = db.Column(db.String(255), nullable=True)
    role = db.Column(db.String(50), nullable=False, default='metrologue')
    # Federated identity: 'local' (email+password) or 'orcid' (SSO)
    auth_provider = db.Column(db.String(20), nullable=False, default='local')
    orcid_id = db.Column(db.String(19), unique=True,
                         nullable=True)  # 0000-0000-0000-0000

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        # An ORCID account has no local hash: never crash, just refuse.
        if not self.password_hash:
            return False
        return check_password_hash(self.password_hash, password)

    def __repr__(self):
        return f'<User {self.username}>'
