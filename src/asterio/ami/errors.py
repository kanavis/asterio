"""
Asterisk AIO interface: error classes
"""
from typing import Tuple


class Error(Exception):
    """ Basic error class """
    data: Tuple[str]

    def __init__(self, message: str, *args: str):
        """ Constructore """
        Exception.__init__(self, message)
        self.data = args

    def _append_data(self) -> str:
        """ Append data with a space if it presents """
        if self.data:
            return f" {self.data}"
        else:
            return ""

    def __repr__(self) -> str:
        """ Representation """
        return f"{Exception.__repr__(self)}{self._append_data()}"

    def __str__(self) -> str:
        """ String """
        return f"{Exception.__str__(self)}{self._append_data()}"


class ProgrammingError(Error):
    """
    Basic programming error class.
    This is error contrasts with RunError
    and happens due to incorrect client usage
    """


class RunError(Error):
    """
    Basic run error class.
    This is error contrasts with ConfigError
    and happens during correct client usage
    """


class InternalError(RunError):
    """ Internal assertion failure """


class AuthenticationError(RunError):
    """ Authentication error """


class ConnectError(RunError, ConnectionError):
    """ Connection error """


class ProtocolError(RunError):
    """ Protocol error """
