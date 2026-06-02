from __future__ import annotations



import time

from collections import deque

from dataclasses import dataclass

from typing import Any





@dataclass

class ContextEntry:

    sender_display: str

    sender_id: str

    body: str

    channel: str

    contact: str

    contact_matched: bool

    at: float





class MessageContext:

    """Ring buffer of recent messages to correlate images with senders."""



    def __init__(self, window_seconds: float = 180, max_entries: int = 80) -> None:

        self.window_seconds = window_seconds

        self.max_entries = max_entries

        self._entries: deque[ContextEntry] = deque(maxlen=max_entries)



    def push(

        self,

        *,

        sender_display: str,

        sender_id: str,

        body: str,

        channel: str,

        contact: str,

        contact_matched: bool,

    ) -> None:

        self._entries.append(

            ContextEntry(

                sender_display=sender_display,

                sender_id=sender_id,

                body=body,

                channel=channel,

                contact=contact,

                contact_matched=contact_matched,

                at=time.time(),

            )

        )



    def best_match(

        self,

        *,

        sender_hint: str = "",

        prefer_matched: bool = True,

    ) -> ContextEntry | None:

        now = time.time()

        candidates = [

            e

            for e in self._entries

            if now - e.at <= self.window_seconds

        ]

        if not candidates:

            return None



        hint_id = ""

        if sender_hint:

            from telelink.classify import normalize_sender_id



            hint_id = normalize_sender_id(sender_hint)



        if hint_id:

            for e in reversed(candidates):

                if e.sender_id == hint_id:

                    return e



        if prefer_matched:

            for e in reversed(candidates):

                if e.contact_matched:

                    return e



        return candidates[-1]


