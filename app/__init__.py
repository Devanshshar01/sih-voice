"""SatyaVoice backend package.

This module is imported before any ``app.*`` submodule, including
``app.api.v1.stream`` — which constructs the inference provider at import time
and therefore emits the ZeroGPU startup diagnostic during that import. The
logging bootstrap must live here so it is in force *before* that happens.

WHY THIS BOOTSTRAP EXISTS
    uvicorn's default logging configuration (``uvicorn.config.LOGGING_CONFIG``)
    defines handlers for the ``uvicorn*`` loggers only and provides **no
    ``root`` entry**. The root logger therefore keeps no handlers, so Python
    falls back to ``logging.lastResort``, which emits WARNING and above only.
    Every application INFO diagnostic — provider initialisation (gradio_client
    version, auth kwarg, token_configured), detector mode, Space configuration
    — was discarded before it could reach the Render log, which made a provider
    that had genuinely initialised look as though it never ran.

SCOPE AND SAFETY
    - Only the application's own ``satyavoice`` namespace is levelled. Third-
      party loggers (SQLAlchemy, httpx, gradio, urllib3) are deliberately left
      alone, so the deployment stays lightweight and no new log volume appears.
    - A handler is attached ONLY when the host has not configured root logging
      itself, so output is never duplicated and test capture (pytest's caplog /
      root handlers) keeps working unchanged.
    - ``propagate`` is never modified.
    - No secret is read, logged, or exposed here.
"""
from __future__ import annotations

import logging

_APP_LOGGER_NAME = "satyavoice"

# Terse format, consistent with the deployment's existing log lines.
_LOG_FORMAT = "%(levelname)s:%(name)s:%(message)s"


def configure_app_logging(level: int = logging.INFO) -> logging.Logger:
    """Make application diagnostics emittable; safe to call repeatedly.

    Returns the configured ``satyavoice`` logger. Records below ``level``
    (INFO by default) are not emitted; WARNING and above already reached hosts
    via ``logging.lastResort`` and continue to do so.
    """
    app_logger = logging.getLogger(_APP_LOGGER_NAME)
    app_logger.setLevel(level)
    # A suite-wide or third-party ``dictConfig(disable_existing_loggers=True)``
    # (or ``logging.disable(...)``) can hard-disable already-created loggers.
    # Re-enable our own namespace so operational diagnostics cannot vanish
    # silently — the exact failure mode this bootstrap exists to fix.
    app_logger.disabled = False

    root = logging.getLogger()
    if not app_logger.handlers and not root.handlers:
        # No host configuration present: provide stderr output ourselves.
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        app_logger.addHandler(handler)

    return app_logger


configure_app_logging()

