"""AML Shield - AI помощник по крипто-безопасности."""

from .service import AMLService, AML_ENCYCLOPEDIA, SYSTEM_PROMPT
from .handlers import register_aml_handlers, init_aml_handlers

__all__ = [
    'AMLService',
    'AML_ENCYCLOPEDIA',
    'SYSTEM_PROMPT',
    'register_aml_handlers',
    'init_aml_handlers',
]
