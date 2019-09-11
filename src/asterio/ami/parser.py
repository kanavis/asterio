"""
Asterisk AIO interface: protocol parser
"""
import logging
from typing import Tuple, Optional, Dict, Union

from asterio.ami.action import Response
from asterio.ami.errors import ProtocolError, InternalError, RunError
from asterio.ami.event import Event
from asterio.ami.events import EVENT_CLASS_MAP
from asterio.ami.packet import Packet

log = logging.getLogger("asterio.ami.parser")

SIMPLE_HINT_TYPES = (int, str, float, bool)


class Parser:
    """ Parser class """
    _nl: bytes = b'\r\n'

    @classmethod
    def parse_server_signature(
            cls, content: bytes) -> Tuple[str, str, Optional[str]]:
        """ Parse server signature """
        rows = content.strip().split(cls._nl)
        if len(rows) != 1 or len(rows[0]) > 200:
            raise ProtocolError("Wrong server signature format",
                                content.decode())
        remote_signature = rows[0].decode()
        parts = remote_signature.split("/", 1)
        if len(parts) < 2:
            remote_name = parts[0]
            remote_version = None
        else:
            remote_name = parts[0]
            remote_version = parts[1]

        return remote_signature, remote_name, remote_version

    @classmethod
    def parse_incoming_packet(
            cls, content: bytes, debug: bool,
            event_empty_str: bool) -> Union[Event, Response]:
        """ Parse incoming packet """
        # Parse packet into data dict
        data: Dict[str, str] = {}
        for line in content.strip().split(cls._nl):
            parts = line.split(b':', 1)
            if len(parts) != 2:
                if debug:
                    log.error("Protocol error: "
                              f"unparsable line: \"{line.decode()}\" "
                              f"in \"{content.decode()}\"")
                else:
                    log.error("Protocol error: "
                              f"unparsable line: \"{line.decode()}\"")
                continue
            data[parts[0].decode().strip()] = parts[1].decode().strip()

        if not data:
            if debug:
                log.error(f"Got unparsable packet \"{content.decode()}\"")
            else:
                log.error(f"Got unparsable packet "
                          f"\"{content.decode()[:20]}...")

        # Parse main packet header
        packet_type: str = next(iter(data))
        packet_value: str = data[packet_type]
        del data[packet_type]
        packet_type = packet_type.lower()

        # Create corresponding packet instance
        if packet_type == "response":
            return Response(response=packet_value, data=data)
        elif packet_type == "event":
            return cls.parse_event(event_name=packet_value, data=data,
                                   empty_str=event_empty_str)
        else:
            raise ProtocolError(
                f"Unsupported incoming packet type {packet_type}")

    @classmethod
    def _data_hint_none(cls, hint) -> bool:
        """ Check if data hint allows None """
        return hint is None or (getattr(hint, "__origin__", None) is Union
                                and None.__class__ in hint.__args__)

    @classmethod
    def _process_data_hint(cls, hint, data: str):
        """ Process data hint """
        # Get non-None hint from Union
        if getattr(hint, "__origin__", None) is Union:
            t = list(filter(lambda x: x is not None.__class__, hint.__args__))
            if len(t) != 1:
                raise InternalError(f"Unsupported type hint {hint}")
            hint = t[0]

        # Check type hint
        if not isinstance(hint, SIMPLE_HINT_TYPES):
            raise InternalError(f"Unsupported type hint {hint}")

        if not callable(hint):
            raise InternalError(f"Unsupported type hint {hint}")

        # Return data converted with hint
        return hint(data)

    @classmethod
    def parse_event(cls, event_name: str, data: Dict[str, str],
                    empty_str: bool) -> Event:
        """ Parse event """
        # Create event instance
        event_key = event_name.lower()
        if event_key in EVENT_CLASS_MAP:
            event_cls = EVENT_CLASS_MAP[event_key]
        else:
            event_cls = Event
        event = event_cls(event_name, data)

        # Set event attributes
        for attr_name, attr_hint in event.__annotations__.items():
            data_key = attr_name.lower()
            if data_key in event:
                # Got attr data in event. Process data hint
                try:
                    setattr(event, attr_name, cls._process_data_hint(
                        attr_hint, event[data_key]))
                except RunError as err:
                    raise err.__class__(
                        f"Event {event_name} attr {attr_name}: {err}")
            else:
                # No data in event.
                if cls._data_hint_none(attr_hint):
                    # Data hint allows None. Set placeholder
                    setattr(event, attr_name, "" if empty_str else None)
                else:
                    # Data hint doesn't allow None. Raise an error
                    raise ProtocolError(
                        f"Event {event_name}: missing required field "
                        f"{attr_name}")

        return event

    @staticmethod
    def _header_key_normalize(key: str) -> str:
        """ Normalize header key """
        return key.lower().capitalize()

    @classmethod
    def serialize_outgoing_packet(cls, packet: Packet) -> bytes:
        """ Serialize outgoing packet """
        return cls._nl.join(
            f"{cls._header_key_normalize(k)}: {v}".encode()
            for k, v in packet.items())
