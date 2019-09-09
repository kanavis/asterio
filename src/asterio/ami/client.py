"""
Asterisk AIO interface: main manager class
"""
import inspect
import logging

import asyncio
import socket
from asyncio import StreamReader, StreamWriter, Task, Future
from typing import Optional, Union, Dict, TypeVar, Callable, Iterable, List, \
    Awaitable

from asterio.ami.action import Response, Action
from asterio.ami.actions.login_action import LoginAction
from asterio.ami.errors import ProgrammingError, ProtocolError, \
    AuthenticationError, ConnectError, InternalError
from asterio.ami.event import Event
from asterio.ami.packet import Packet
from asterio.ami.parser import Parser

log = logging.getLogger("asterio.ami.client")

TEvent = TypeVar("TEvent", bound=Event)
TEventHandler = Callable[[TEvent], Awaitable[None]]


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
    _generic_event_handlers: List[TEventHandler]
    _event_handlers: Dict[type, List[TEventHandler]]
    _named_event_handlers: Dict[str, List[TEventHandler]]

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
        self._generic_event_handlers = []
        self._event_handlers = {}
        self._named_event_handlers = {}
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
        # Try generic handlers
        for handler in self._generic_event_handlers:
            self.loop.create_task(handler(event))
        # Try class-based handler
        if event.__class__ in self._event_handlers:
            for handler in self._event_handlers[event.__class__]:
                self.loop.create_task(handler(event))
        # Try named handler
        if event.value.lower() in self._named_event_handlers:
            for handler in self._named_event_handlers[event.value.lower()]:
                self.loop.create_task(handler(event))

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

    async def get_event(self) -> Event:
        """ Events coroutine """
        while True:
            packet = await self.read_packet()

            if isinstance(packet, Event):
                return packet

    async def packet_loop(self):
        """ Run packet loop, throwing all processing exceptions """
        while True:
            await self.read_packet()

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

    def _bind_event_handler(
            self, event_classes: Iterable[TEvent], callback: TEventHandler):
        """ Bind event handler """
        # Check callback is an async task
        if not inspect.iscoroutinefunction(callback):
            raise ProgrammingError("Event handler must be an async coroutine")
        # Bind
        for event_class in event_classes:
            if event_class is Event:
                # Generic event handler
                self._generic_event_handlers.append(callback)
            elif isinstance(event_class, str):
                # Named event handler
                event_class = event_class.lower()
                if event_class not in self._named_event_handlers:
                    self._named_event_handlers[event_class] = []
                self._named_event_handlers[event_class].append(callback)
            else:
                # Class-based event handler
                if event_class not in self._event_handlers:
                    self._event_handlers[event_class] = []
                self._event_handlers[event_class].append(callback)

    def handle_event(
            self,
            event_class: Union[TEvent, str,
                               Iterable[TEvent], Iterable[str]] = Event,
            arg2: Optional[TEventHandler] = None
    ) -> Optional[Callable[[TEventHandler], TEventHandler]]:
        """
        Handle event.

        May be used as a decorator:

        .. code-block:: python
            @client.handle_event(asterio.ami.events.DialBegin)
            def handle_dial_begin(event: asterio.ami.events.DialBegin):
                ...

        Or as a bind method
        .. code-block:: python
            def handle_dial_begin(event: asterio.ami.events.DialBegin):
                ...

            client.handle_event(asterio.ami.events.DialBegin,
                                handle_dial_begin)

        :param event_class: if it's asterio.ami.event.Event (default),
            handler will be called for each event.
            If it's event name (case-insensitive) of event class from
            asterio.events, handler will be called only for this events.
        :type event_class: Union[TEvent, Iterable[TEvent]],
        :param arg2: callback (if not using as a decorator)
        """
        # Ensure first argument is iterable
        if issubclass(event_class, Event) or isinstance(event_class, str):
            event_class = (event_class,)

        if arg2 is None:
            # Using as a decorator
            def decorate(outer: TEventHandler) -> TEventHandler:
                self._bind_event_handler(event_class, outer)
                return outer
            return decorate
        else:
            # Using as a bind-method, not decorator
            self._bind_event_handler(event_class, arg2)
