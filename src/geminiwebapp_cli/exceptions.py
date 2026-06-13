class GeminiWebappCliError(Exception):
    """Base exception for expected CLI failures."""


class AuthenticationError(GeminiWebappCliError):
    """Gemini did not reach an authenticated page."""


class InteractiveAuthenticationRequired(AuthenticationError):
    """Gemini requires a human login in the opened browser."""


class ElementNotFoundError(GeminiWebappCliError):
    """A required Gemini UI element was not visible."""


class ResponseTimeoutError(GeminiWebappCliError):
    """Gemini did not finish responding before the timeout."""


class ChatNotFoundError(GeminiWebappCliError):
    """The requested Gemini chat could not be opened or found."""


class GeminiUnavailableError(GeminiWebappCliError):
    """Gemini showed an unavailable, unsupported, or blocking state."""


class ImageDownloadError(GeminiWebappCliError):
    """A generated image was visible but could not be downloaded."""


class VideoDownloadError(GeminiWebappCliError):
    """A generated video was visible but could not be downloaded."""


class MusicDownloadError(GeminiWebappCliError):
    """Generated music was visible but could not be downloaded."""
