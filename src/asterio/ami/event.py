"""
Asterisk AIO interface: event class
"""
from typing import Dict

from asterio.ami.packet import Packet


class Event(Packet):
    """ Basic event class """

    def __init__(self, event: str, data: Dict[str, str]):
        """
        Constructor
        :param event: event value
        :type event: str
        :param data: data dictionary
        :type data: Dict[str, str]
        """
        Packet.__init__(self, "event", event, data)
