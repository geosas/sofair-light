import hashlib
import secrets
from datetime import datetime, timedelta

from app import db

# Validity period of an invitation link
INVITATION_TTL = timedelta(hours=24)


class Invitation(db.Model):
    """Single-use invitation issued by an admin to create an account.
    """
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(50), nullable=False, default='metrologue')
    token_hash = db.Column(db.String(64), unique=True, nullable=False)
    invited_by = db.Column(db.String(80))
    created_at = db.Column(db.DateTime, nullable=False,
                           default=datetime.utcnow())
    expires_at = db.Column(db.DateTime, nullable=False)
    used_at = db.Column(db.DateTime)  # None => not consumed yet

    # Authentication method for the future account: 'local' (set-password link)
    # or 'orcid' (federated login). For ORCID, orcid_id is provided by the admin
    auth_provider = db.Column(db.String(20), nullable=False, default='local')
    orcid_id = db.Column(db.String(19), nullable=True)  # 0000-0000-0000-0000

    @staticmethod
    def hash_token(raw_token):
        """Hash token"""
        return hashlib.sha256(raw_token.encode("utf-8")).hexdigest()

    @classmethod
    def create(cls, email, role, invited_by=None, ttl=INVITATION_TTL,
               auth_provider="local", orcid_id=None):
        """Create an invitation
        The clear-text token is returned only here, 
        it can never be retrieved again (only its hash is stored). 
        """
        raw_token = secrets.token_urlsafe(32)
        now = datetime.utcnow()()
        invite = cls(
            email=email,
            role=role,
            token_hash=cls.hash_token(raw_token),
            invited_by=invited_by,
            created_at=now,
            expires_at=now + ttl,
            auth_provider=auth_provider,
            orcid_id=orcid_id,
        )
        return invite, raw_token

    @classmethod
    def find_valid_orcid(cls, orcid_id):
        """Return the valid ORCID invitation linked to this ORCID ID, otherwise None.
        an ORCID login only activates an account if it matches a valid invitation
        from admin  pre-filled the orcid_id
        """
        invite = cls.query.filter_by(
            auth_provider="orcid", orcid_id=orcid_id).first()
        if invite and invite.is_valid():
            return invite
        return None

    @classmethod
    def find_valid(cls, raw_token):
        """Return the valid invitation corresponding to the token, otherwise None.
        Valid = exists + not consumed + not expired.
        """
        invite = cls.query.filter_by(
            token_hash=cls.hash_token(raw_token)).first()
        if invite and invite.is_valid():
            return invite
        return None

    def is_valid(self):
        return self.used_at is None and self.expires_at > datetime.utcnow()()

    def mark_used(self):
        self.used_at = datetime.utcnow()()

    def __repr__(self):
        return f'<Invitation {self.email} ({self.role})>'
