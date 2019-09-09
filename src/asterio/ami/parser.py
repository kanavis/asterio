"""
Asterisk AIO interface: protocol parser
"""
import logging
from typing import Tuple, Optional, Dict, Union

from asterio.ami.action import Response
from asterio.ami.errors import ProtocolError
from asterio.ami.event import Event
from asterio.ami.packet import Packet

log = logging.getLogger("asterio.ami.parser")


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
            cls, content: bytes, debug: bool) -> Union[Event, Response]:
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
            return Event(event=packet_value, data=data)
        else:
            raise ProtocolError(
                f"Unsupported incoming packet type {packet_type}")

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
