class ServiceError(RuntimeError):
    """Base error for service layer failures."""


class ConfigError(ValueError):
    """Raised when a config contract is invalid or missing."""


class DependencyError(RuntimeError):
    """Raised when a required dependency is missing."""
