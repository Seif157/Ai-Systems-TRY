"""Safe failures for the direct OpenAI production boundary."""


class OpenAIProviderUnavailable(RuntimeError):
    """Constant provider failure without request, response, or credential detail."""

    def __init__(self) -> None:
        super().__init__("OpenAI provider is unavailable")


class OpenAIPrivacyDenied(RuntimeError):
    """Constant pre-network privacy-policy denial."""

    def __init__(self) -> None:
        super().__init__("OpenAI provider privacy policy denied the request")
