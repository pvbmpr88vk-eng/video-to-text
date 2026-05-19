class AudioExtractionError(Exception):
    """Base error for audio extraction."""


class FFmpegNotFoundError(AudioExtractionError):
    """ffmpeg or ffprobe is not available in PATH."""


class NoAudioStreamError(AudioExtractionError):
    """Input file has no audio stream at the requested index."""


class FFmpegError(AudioExtractionError):
    def __init__(self, message: str, *, stderr: str = "") -> None:
        super().__init__(message)
        self.stderr = stderr
