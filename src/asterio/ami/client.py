"""
Asterisk AIO interface: main manager class
"""
import logging

import asyncio
import socket
from asyncio import StreamReader, StreamWriter, Task, Future
from typing import Optional, Union, Dict, List

from asterio.ami.action import Response, Action
from asterio.ami.actions.login_action import LoginAction
from asterio.ami.errors import ProgrammingError, ProtocolError, \
    AuthenticationError, ConnectError, InternalError
from asterio.ami.event import Event
from asterio.ami.event_handler import EventHandler
from asterio.ami.packet import Packet
from asterio.ami.parser import Parser

log = logging.getLogger("asterio.ami.client")


class ManagerClient:
    """
    Asterisk manager client class

    Run connect() after construction.

    Use get_event() for event reading inside loop or bind event handler with
    handle_event() decorator/bind and then make a task packet_loop() to use
    handler-based event processing
    """
    debug_payload_out: bool = False  # Shall out packet payload be debugged
    debug_payload_in: bool = False  # Shall in packet payload be debugged

    loop: asyncio.AbstractEventLoop
    connected: bool = False
    remote_signature: Optional[str] = None
    remote_name: Optional[str] = None
    remote_version: Optional[str] = None

    _host: str
    _port: int
    _username: str
    _secret: str
    _connection_timeout: int
    _reader: StreamReader
    _writer: StreamWriter
    _buffer: bytes
    _read_task: Optional[Task]
    _pending_actions: Dict[str, Action]
    _event_handlers: List[EventHandler]

    _BSIZE = 1000
    _terminator: bytes = b'\r\n\r\n'

    def __init__(
            self,
            loop: asyncio.AbstractEventLoop,
    ):
        """
        Constructor

        :param loop: event loop
        :type loop: asyncio.AbstractEventLoop
        """
        self.parser = Parser()
        self.loop = loop
        self._buffer = b''
        self._pending_actions = {}
        self._event_handlers = []
        self._read_task = None

    @property
    def _remote_sig(self) -> str:
        """ Return nice remote signature """
        if self.remote_name and self.remote_version:
            return f"{self.remote_name} v{self.remote_version}"
        else:
            assert self.remote_signature is not None
            return f"{self.remote_signature}"

    @property
    def _host_port(self) -> str:
        """ Return host:port """
        return f"{self._host}:{self._port}"

    async def _handle_disconnect(self):
        """ Handle server disconnect """
        log.error("Remote server closed connection")
        self._reset()
        self._writer.close()
        await getattr(self._writer, "wait_close")()

    def _stop_reading(self):
        """ Stop reading task """
        self._read_task.cancel()
        self._read_task = None

    def _reset(self):
        """ Reset object to pre-connected state """
        self._buffer = b''
        self._pending_actions = {}
        if self._read_task is not None and not self._read_task.cancelled():
            self._stop_reading()

    async def _connection(self):
        """ Open connection """
        log.debug(f"Connecting to {self._host}:{self._port} "
                  f"timeout={self._connection_timeout}")
        # Create connection future
        con = asyncio.open_connection(
            host=self._host, port=self._port, loop=self.loop,
            limit=self._BSIZE)

        # Replace future with a timeout if needed
        if self._connection_timeout > 0:
            con = asyncio.wait_for(
                con, timeout=self._connection_timeout)

        # Await connection future catching a timeout
        try:
            self._reader, self._writer = await con
        except asyncio.TimeoutError:
            # Raise timeout error
            raise TimeoutError("Timeout reached during connection")

        log.debug(f"Opened socket connection with {self._host_port}")

    async def _read_remote_signature(self):
        """ Read remote server signature """
        # Read signature
        received = await self._reader.read(self._BSIZE)
        if not received:
            raise ProtocolError("Server closed connection immediately")
        if self.debug_payload_in:
            log.debug(f"Got data {received}")

        # Parse signature
        self.remote_signature, self.remote_name, self.remote_version = \
            self.parser.parse_server_signature(received)

    async def _send_packet(self, packet: Packet):
        """ Send action """
        # Send packet
        if self.debug_payload_out:
            log.debug(f"Sending packet {packet}")
        else:
            log.debug(f"Sending packet {packet.signature}")
        data = self.parser.serialize_outgoing_packet(packet)
        self._writer.write(data)

        # Send terminator
        self._writer.write(self._terminator)

    def _try_action_response(self, packet: Union[Event, Response]):
        """ Try action response """
        if packet.action_id is not None:
            if packet.action_id in self._pending_actions:
                action = self._pending_actions[packet.action_id]
                if isinstance(packet, Response):
                    action.process_response(packet)
                elif isinstance(packet, Event):
                    action.process_event(packet)

    def _try_event_handler(self, event: Event):
        """ Try event handler """
        for handler in self._event_handlers:
            handler.handle(event, self.loop)

    def _process_packet(self, content: bytes) -> Union[Event, Response]:
        """ Process received packet """
        try:
            if self.debug_payload_in:
                log.debug(f"Got payload: {content}")

            # Parse packet
            packet = self.parser.parse_incoming_packet(
                content, debug=self.debug_payload_in)

            # Debug
            if self.debug_payload_in:
                log.debug(f"Got packet {packet}")
            else:
                log.debug(f"Got packet {packet.signature}")

            # Try action response
            self._try_action_response(packet)

            if isinstance(packet, Event):
                self._try_event_handler(packet)

            # Return
            return packet

        except Exception:
            log.exception("Exception in packet processor")
            raise

    def _get_buffered_packet(self) -> Optional[bytes]:
        """ Shift packet from buffer """
        if self._terminator in self._buffer:
            # Shift packet
            parts = self._buffer.split(self._terminator, 1)
            if len(parts) == 1:
                packet = parts[0]
                self._buffer = b''
            elif len(parts) == 2:
                packet = parts[0]
                self._buffer = parts[1]
            else:
                raise InternalError("Wrong buffer content",
                                    str(self._buffer))
            return packet
        else:
            # No packet in buffer
            return None

    async def read_packet(self) -> Union[Event, Response]:
        """ Packet reader """
        try:
            while True:
                # Try getting whole packet from buffer
                packet = self._get_buffered_packet()
                if packet is not None:
                    return self._process_packet(packet)

                # Read
                read = await self._reader.read(self._BSIZE)
                if not read:
                    await self._handle_disconnect()
                    raise
                self._buffer += read

        except Exception:
            log.exception("Exception in receiver")
            raise

    async def get_event(self, *args: EventHandler) -> Event:
        """
        Events generating coroutine

        May process event handlers as positional args
        """
        while True:
            packet = await self.read_packet()

            if isinstance(packet, Event):
                for handler in args:
                    handler.handle(packet, self.loop)
                return packet

    async def event_loop(self, *args: EventHandler):
        """
        Run event loop, throwing all processing exceptions

        May process event handlers as positional args
        """
        while True:
            await self.get_event(*args)

    async def action(self, action: Action) -> "Future[bool]":
        """
        Send action

        :param action:
        :type action:
        :return: future getting a result when action is complete, returning
            bool if result is True
        :rtype: Future[bool]
        """
        action_id = action.action_id
        if action_id is None:
            raise ProgrammingError("Cannot send action without action id")
        if action_id in self._pending_actions:
            raise ProgrammingError("Action with this ID is already pending",
                                   action_id)
        self._pending_actions[action_id] = action
        action.bind_loop(self.loop)
        await self._send_packet(action)
        return action.complete_future

    async def _auth(self):
        """ Authenticate client """
        action = LoginAction(self._username, self._secret)
        await self.action(action)
        while True:
            packet = await self.read_packet()
            if (isinstance(packet, Response) and
                    packet.action_id == action.action_id):
                break
        await action.complete_future
        if not action.ok:
            raise AuthenticationError("Authentication error",
                                      action.response.message)
        log.debug(f"Client authenticated, message={action.response.message}")

    async def connect(
            self,
            host: str,
            port: int,
            username: str,
            secret: str,
            timeout: int = -1
    ):
        """
        Connect to AMI server

        :param host: manager server host
        :type host: str
        :param port: manager server port
        :type port: int
        :param username: manager username
        :type username: str
        :param secret: manager secret
        :type secret: str
        :param timeout: connection timeout in seconds, if < 0 - use default
            timeout. def=-1
        :type timeout: int
        """
        if self.connected:
            raise ProgrammingError("Trying to connect on connected client")

        # Set attributes
        self._reset()
        self._host = host
        self._port = port
        self._connection_timeout = timeout
        self._username = username
        self._secret = secret

        # Open socket
        try:
            await self._connection()
        except TimeoutError:
            raise ConnectError(f"Connection failed: timeout", host, str(port))
        except (ConnectionRefusedError, socket.error) as err:
            print(err.__class__.__name__)
            raise ConnectError(f"Connection failed: {err}", host, str(port))
        # Read remote server signature
        await self._read_remote_signature()
        # Authenticate
        await self._auth()

        log.info(f"Connected via AMI to \"{self._remote_sig}\" "
                 f"at {self._host_port}")
        self.connected = True
