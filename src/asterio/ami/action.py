"""
Asterisk AIO interface: action classes
"""
import asyncio
import uuid
from typing import Dict, Optional, List

from asterio.ami.errors import InternalError
from asterio.ami.event import Event
from asterio.ami.packet import Packet


class Response(Packet):
    """ Basic response class """
    def __init__(self, response: str, data: Dict[str, str]):
        """
        Constructor
        :param response: response value
        :type response: str
        :param data: data dictionary
        :type data: Dict[str, str]
        """
        Packet.__init__(self, "response", response, data)

    @property
    def is_success(self) -> bool:
        """ Is response successful """
        return self.value.lower() == "success"

    @property
    def is_error(self) -> bool:
        """ Is response erroneous """
        return self.value.lower() == "error"

    @property
    def is_follows(self) -> bool:
        """ Does response follow """
        return self.value.lower() == "follows"

    @property
    def message(self) -> str:
        """ Get action message or empty string if no message """
        return self.get("message", "")


class Action(Packet):
    """ Basic action class """

    got_response: bool = False
    is_complete: bool = False
    ok: bool = None
    response: Optional[Response] = None
    events: List[Event]

    loop: asyncio.AbstractEventLoop
    complete_future: Optional["asyncio.Future[bool]"] = None
    response_future: Optional["asyncio.Future[bool]"] = None

    def __init__(self, action: str, data: Dict[str, str]):
        """
        Constructor

        :param action: action name
        :type action: str
        :param data: action data
        :type data: Dict[str, str]
        """
        Packet.__init__(self, packet_type="action", value=action, data=data)
        self.events = []

        # Generate action id if it doesn't exist
        if "actionid" not in self:
            self["actionid"] = str(uuid.uuid4())

    def bind_loop(self, loop: asyncio.AbstractEventLoop):
        """ Bind loop """
        self.loop = loop
        self.complete_future = asyncio.Future(loop=loop)
        self.response_future = asyncio.Future(loop=loop)

    def process_event(self, event: Event):
        """ Process action event """
        self.events.append(event)
        self._on_event(event)

    def process_response(self, response: Response):
        """ Process action response """
        # Set response and success
        self.response = response
        self.ok = not response.is_error
        # Run response handler
        self._on_response()
        # Assert response_future is set
        if self.response_future is None:
            raise InternalError("Processing response for unbound event")
        # Complete action if response is not "Follows"
        if not response.is_follows:
            self._complete()
        # Generate response future result
        self.response_future.set_result(self.ok)

    def _complete(self):
        """ Internal call when event is complete """
        # Set complete attribute
        self.is_complete = True
        # Assert complete future is set
        if self.complete_future is None:
            raise InternalError("Processing complete for unbound event")
        # Assert response is set
        if self.response is None:
            raise InternalError("Completed event without response")
        # Assert result is set
        self.complete_future.set_result(not self.ok)

    def _on_response(self, ):
        """ Internal response handler """

    def _on_event(self, event: Event):
        """ Internal event handler """
