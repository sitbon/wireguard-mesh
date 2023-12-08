import binascii
import os

__all__ = "random_id",


def random_id() -> str:
    return binascii.b2a_hex(os.urandom(16)).decode("utf-8")
