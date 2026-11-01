"""Допуск к индексу. Модуль не читает людей и не открывает каталог."""
import hashlib
import hmac
import secrets
from pathlib import Path

_SECRET = secrets.token_bytes(32)


def sign(kb_id, action, path):
    text = f"{kb_id}\n{action}\n{Path(path).resolve()}"
    return hmac.new(_SECRET, text.encode("utf-8"), hashlib.sha256).digest()


class Permit:
    def __init__(self, kb_id, action, chroma, inbox, signature, check):
        self.kb_id = kb_id
        self.action = action
        self.chroma = Path(chroma)
        self.inbox = Path(inbox)
        self._signature = signature
        self._check = check

    def confirm(self):
        expected = sign(self.kb_id, self.action, self.chroma)
        if not hmac.compare_digest(self._signature, expected):
            return False
        return bool(self._check())
