class TranscriptionError(Exception):
    """Base error for speech-to-text."""


class ModelNotAvailableError(TranscriptionError):
    """faster-whisper is not installed or model failed to load."""
