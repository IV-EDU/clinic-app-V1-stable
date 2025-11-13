from .routes import bp  # re-export for registration
from .multi_doctor import bp as multi_doctor_bp

__all__ = ["bp", "multi_doctor_bp"]
