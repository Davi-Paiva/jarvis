from __future__ import annotations


class JarvisError(Exception):
    """Base class for backend domain errors."""


class InvalidRepositoryPathError(JarvisError):
    """Raised when the provided path does not point to a valid repository folder."""


class RepositoryPathNotAllowedError(JarvisError):
    """Raised when the repository path is outside the configured allowed roots."""

