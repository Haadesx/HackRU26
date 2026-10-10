class ChannelError(Exception):
    """Send failed; delivery is marked failed and may be retried."""


class InvalidRecipient(ChannelError):
    """Token/number is permanently invalid; do not retry."""
