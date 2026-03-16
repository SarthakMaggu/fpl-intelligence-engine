class FPLAPIError(Exception):
    """Raised when the FPL API returns an unexpected response."""


class PipelineRunningError(Exception):
    """Raised when a data pipeline job is already running."""


class OptimizationError(Exception):
    """Raised when the ILP optimizer fails to find a feasible solution."""


class ModelNotTrainedError(Exception):
    """Raised when an ML model is called before it has been trained."""


class PlayerNotFoundError(Exception):
    """Raised when a player ID is not found in the database."""


class InvalidChipError(Exception):
    """Raised when a chip action violates game rules."""
