"""
Asterisk AIO interface: event classes
"""
from typing import Type, Dict

from asterio.ami.event import Event

# Event class map
EVENT_CLASS_MAP: Dict[str, Type[Event]] = {}


def register_class(cls: Type[Event], name: str):
    """ Register event class """
    EVENT_CLASS_MAP[name.lower()] = cls


def register_module(module):
    """ Register events module """
    for attr_name in dir(module):
        attr = getattr(module, attr_name)
        if issubclass(attr, Event):
            register_class(attr, attr.__name__)
