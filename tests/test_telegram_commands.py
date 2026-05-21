from __future__ import annotations

from unittest.mock import MagicMock

from telegram.ext import CommandHandler

from app.telegram import messages as M
from app.telegram.handlers import register_handlers


def test_status_command_not_registered() -> None:
    app = MagicMock()
    app.add_handler = MagicMock()
    register_handlers(app)
    callbacks = [
        call.args[0].callback.__name__
        for call in app.add_handler.call_args_list
        if call.args and isinstance(call.args[0], CommandHandler)
    ]
    assert "cmd_status" not in callbacks
    assert "cmd_start" in callbacks
    assert "cmd_help" in callbacks
    assert "cmd_cancel" in callbacks


def test_user_messages_do_not_mention_status_command() -> None:
    for text in (
        M.START,
        M.HELP,
        M.BUSY,
        M.QUEUE_POSITION.format(position=1, processing_hint=""),
        M.TRANSCRIPT_SEND_FAILED,
    ):
        assert "/status" not in text
