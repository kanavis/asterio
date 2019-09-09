"""
Asterisk AIO interface: event handler class
"""
import inspect
from asyncio import AbstractEventLoop
from typing import Callable, List, TypeVar, Awaitable, \
    Optional, Union, NamedTuple

from asterio.ami.errors import ProgrammingError
from asterio.ami.event import Event
from asterio.ami.filter import Filter

TEvent = TypeVar("TEvent", bound=Event)
TEventHandler = Callable[[TEvent], Awaitable[None]]


class BoundCallback(NamedTuple):
    """ Bound event class """
    filter: Optional[Filter]
    callback: TEventHandler


class EventHandler:
    """
    Event handler.
    Used for callback-style events handlers.

    First you need to bind event handlers.
    Filter argument is optional.

    You may use decorator style:

    .. code-block:: python
        handler = EventHandler()
        filter_dial_begin = Filter(C(events.DialBegin))

        @handler.bind(filter_dial_begin)
        def handle_dial_begin(event: events.DialBegin):

            ...

    or bind method:

    .. code-block:: python
        handler = EventHandler(client=client)
        filter_dial_begin = Filter(C(events.DialBegin))

        def handle_dial_begin(event: events.DialBegin):
            ...

    Then you need to start handling, using client's event loop:

     .. code-block:: python
        loop.run_until_complete(client.event_loop(handler1, ...))

     or using add_handler, and then any other packet handling method:

     .. code-block:: python
        client.add_handler(handler)
        while True:
            event = client.get_event()
    """

    _bound_callbacks: List[BoundCallback]

    def __init__(self):
        """ Constructor """
        self._bound_callbacks = []

    def _bind_callback(self, cb: TEventHandler, fil: Optional[Filter]):
        """ Bind callback """
        if not inspect.iscoroutinefunction(cb):
            raise ProgrammingError("Event callback must be awaitable")
        self._bound_callbacks.append(BoundCallback(filter=fil, callback=cb))

    def handle(self, event: Event, loop: AbstractEventLoop):
        """
        Handle an event

        :param event: event object
        :type event: Event
        :param loop: loop object
        :type loop: AbstractEventLoop
        """
        for bound_callback in self._bound_callbacks:
            # Test filter
            if bound_callback.filter is not None:
                if not bound_callback.filter.check(event):
                    continue
            # Run callback
            loop.create_task(bound_callback.callback(event))

    def bind(
            self,
            arg1: Optional[Union[TEventHandler, Filter]] = None,
            arg2: Optional[Filter] = None
    ) -> Optional[Callable[[TEventHandler], TEventHandler]]:
        """
        Bind event callback.

        May be used as a decorator:

        .. code-block:: python
            @handler.bind(filter)
            def handle_event(event: Event):
                ...

        Or as a bind method
        .. code-block:: python
            def handle_event(event: Event):
                ...

            handler.bind(handle_event, filter)

        Filter argument is optional
        """
        if arg1 is None or isinstance(arg1, Filter):
            # Decorator-style usage

            def decorate(outer: TEventHandler) -> TEventHandler:
                self._bind_callback(outer, arg1)
                return outer

            return decorate
        elif callable(arg1):
            # Bind-method style usage
            self._bind_callback(arg1, arg2)
