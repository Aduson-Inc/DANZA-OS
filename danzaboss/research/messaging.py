"""Messaging port — the remote 'grill me' channel.

Sends a Proposal to you (Telegram/Discord/WhatsApp) and ingests your reply. The
channel is a swappable port; the Console adapter is used for tests/offline. Live
adapters (Telegram bot token, etc.) implement the same two methods and are the
documented integration surface.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from .proposal import Proposal, ProposalStatus


class MessagingChannel(Protocol):
    name: str
    def send(self, proposal: Proposal) -> None: ...


class ConsoleChannel:
    """Deterministic channel for tests/offline — captures what would be sent."""
    name = "console"
    def __init__(self):
        self.outbox: list[str] = []
    def send(self, proposal: Proposal) -> None:
        self.outbox.append(proposal.render_message())


class TelegramChannel:  # pragma: no cover - needs bot token/network
    """Reference live adapter. Requires a bot token + chat id (config, not code)."""
    name = "telegram"
    def __init__(self, bot=None, chat_id: str = ""):
        self.bot, self.chat_id = bot, chat_id
    def send(self, proposal: Proposal) -> None:
        if self.bot is None:
            raise RuntimeError("Telegram not configured (needs bot token + chat id).")
        self.bot.send_message(self.chat_id, proposal.render_message())


def parse_reply(text: str) -> tuple[str, str]:
    """Parse your remote reply: 'APPROVE prop_xxx' -> (status, id)."""
    parts = text.strip().split()
    if len(parts) < 2:
        return ("", "")
    verb, pid = parts[0].upper(), parts[1]
    mapping = {"APPROVE": ProposalStatus.APPROVED.value,
               "DENY": ProposalStatus.DENIED.value,
               "LATER": ProposalStatus.DEFERRED.value}
    return (mapping.get(verb, ""), pid)
