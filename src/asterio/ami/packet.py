"""
Asterisk AIO interface: packet class
"""
from typing import Dict, Optional, ItemsView, KeysView, ValuesView

from asterio.ami.errors import InternalError


class Packet:
    """
    Basic packet class.
    Keys are case-insensitive and are stored in lowercase.
    """
    type: str
    _data: Dict[str, str]

    def __init__(self, packet_type: str, value: str, data: Dict[str, str]):
        """
        Constructor

        :param packet_type: packet type name
        :type packet_type: str
        :param value: packet main header (packet_type-like) value
        :type value: str
        :param data: raw packet data dictionary
        :type data: Dict[str, str]
        """
        if len(data) == 0:
            raise InternalError("Cannot create empty packet")
        self.type = packet_type.lower()
        self._data = {packet_type: value}
        for k, v in data.items():
            k = k.lower()
            if k == self.type:
                raise InternalError("Cannot instantiate Packet with a dict "
                                    "containing packet_type-like key")
            self._data[k] = v

    def __setitem__(self, key: str, value):
        """ Setitem """
        self._data[key.lower()] = str(value)

    def __contains__(self, item: str) -> bool:
        """
        Check if item in packet

        :param item: key value
        :type item: str
        :return: contains or not
        :rtype: bool
        """
        return item in self._data

    def __getitem__(self, item: str) -> str:
        """
        Get item.

        :return: key value
        :rtype: str
        :raises: KeyError if item doesn't exist
        """
        if not isinstance(item, str):
            raise ValueError("Packet key may be only string")
        return self._data[item.lower()]

    def __delitem__(self, key: str):
        """ Delete item """
        if self.type == key:
            raise InternalError("Cannot delete main packet header", key)
        del self.data[key]

    def items(self) -> ItemsView[str, str]:
        """ Get data dict set(key, value) iterator """
        return self._data.items()

    def keys(self) -> KeysView[str]:
        """ Get data dict key iterator """
        return self._data.keys()

    def values(self) -> ValuesView[str]:
        """ Get data dict values iterator """
        return self._data.values()

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """
        Get key value using default placeholder

        :param key: key name
        :type key: str
        :param default: default value, optional, def=None
        :type default: Optional[str]
        :return: key value or <default> (default=None) if key doesn't exist
        :rtype: Optional[str]
        """
        try:
            return self._data[key.lower()]
        except KeyError:
            return default

    @property
    def data(self) -> Dict[str, str]:
        """ Get data dict """
        return self._data

    @property
    def value(self) -> str:
        """ Get main header value (action name for Action etc) """
        return self.data[self.type]

    @property
    def action_id(self) -> Optional[str]:
        """ Get action id """
        return self.get("actionid")

    @property
    def signature(self) -> str:
        """ Get packet signature, e.g. "Action: Login (some_action_id)" """
        aid = self.action_id
        signature = f"{self.type.capitalize()}: {self.value}"
        if aid is not None:
            return f"{signature} ({aid})"
        else:
            return signature

    def __str__(self) -> str:
        """ String representation """
        return "\n".join(f"{k.capitalize()}: {v}" for k, v in self.items())

    def __repr__(self) -> str:
        """ Short representation """
        return f"<{self.__module__}.{self.__class__} {self.signature}>"
