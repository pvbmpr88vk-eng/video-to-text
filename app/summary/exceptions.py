class SummaryError(Exception):
    """Base error for summary stage."""


class EmptyTranscriptError(SummaryError):
    pass


class SummaryConfigError(SummaryError):
    pass


class SummaryAPIError(SummaryError):
    pass
