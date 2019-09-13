"""
Asterisk AIO interface: event filtering classes
"""

import re
from abc import ABC, abstractmethod
from typing import Any, TypeVar, Union

from asterio.ami.errors import ProgrammingError
from asterio.ami.event import Event

TEvent = TypeVar("TEvent", bound=Event)


class Break(Exception):
    """ Exception to break condition test. """


class Continue(Exception):
    """ Exception to return false from condition without breaking test """


class ICheck(ABC):
    """
    Filter checks abstract class
    """

    def __repr__(self):
        """ Representation """
        return "<{} {}>".format(self.__class__.__name__, self.__repr_in__())

    def __str__(self):
        """ String """
        return self.__repr_in__()

    @abstractmethod
    def check(self, value) -> bool:
        """ Abstract check method """

    @abstractmethod
    def __repr_in__(self):
        """ Abstract object representation to inherit """


class CheckMethod(ICheck):
    """
    Filter check: basic object methods based check (=, <, >, etc.)
    """

    MAP_COMP_METHOD = {
        "__eq__": "==",
        "__ne__": "!=",
        "__lt__": "<",
        "__gt__": ">",
        "__le__": "<=",
        "__ge__": ">="
    }

    def __init__(self, other_value: Any, method_name: str):
        """ Constructor """
        self.other_value = other_value
        self.method_name = method_name

    def check(self, value):
        """ Check value """
        method = getattr(value, self.method_name)
        return method(self.other_value)

    def __repr_in__(self):
        """ Object representation to inherit """
        if isinstance(self.other_value, str):
            vr = "\"{}\"".format(self.other_value)
        else:
            vr = self.other_value
        return "{} {}".format(self.MAP_COMP_METHOD[self.method_name], vr)


class CheckRe(ICheck):
    """
    Filter check: regex
    """

    def __init__(self, expression: str):
        """ Constructor """
        self.expression = expression
        self.re = re.compile(expression)

    def check(self, value) -> bool:
        """ Check value """
        if not isinstance(value, str):
            raise ProgrammingError("Regex check is only applicable to str")

        return bool(self.re.match(value))

    def __repr_in__(self):
        """ Object representation to inherit """
        return "~ {}".format(self.expression)


class IField(ABC):
    """
    Filter field abstract class
    """

    name: str

    @abstractmethod
    def val(self, event: Event) -> Any:
        """ Abstract value obtainer """

    @abstractmethod
    def __repr_in__(self) -> str:
        """ Abstract object representation to inherit """

    def __eq__(self, other):
        """ Equality check """
        return Cond(self, CheckMethod(other, "__eq__"))

    def __ne__(self, other):
        """ Non-equality check """
        return Cond(self, CheckMethod(other, "__ne__"))

    def __lt__(self, other):
        """ Less-than check """
        return Cond(self, CheckMethod(other, "__lt__"))

    def __le__(self, other):
        """ Less-than-or-equal check """
        return Cond(self, CheckMethod(other, "__le__"))

    def __gt__(self, other):
        """ Greater-than check """
        return Cond(self, CheckMethod(other, "__gt__"))

    def __ge__(self, other):
        """ Greater-than-or-equal check """
        return Cond(self, CheckMethod(other, "__ge__"))

    def match(self, expression: str):
        """ Regex match check """
        return Cond(self, CheckRe(expression))

    def __str__(self):
        """ String """
        return self.__repr_in__()

    def __repr__(self):
        """ Object representation """
        return "<{}.{} {}>".format(self.__class__.__name__, self.__module__,
                                   self.__repr_in__())


class F(IField):
    """
    Event field representation for filters.
    If field doesn't exist and strict filter enabled,
    whole filter fails if reached condition containing
    this field.
    """

    def __init__(self, name: str, strict: bool = False):
        """
        Constructor

        :param name: Field name
        :type name: str
        :param strict: strict mode, fail all filter if field doesn't exist,
            def=False
        :type strict: bool
        """
        self.name = name.lower()
        self.strict = strict

    def val(self, event: Event) -> Any:
        """ Return value from event """
        try:
            return event[self.name]
        except KeyError:
            if self.strict:
                raise Break()
            else:
                raise Continue()

    def __repr_in__(self):
        """ Object representation to inherit """
        return "`event.{}`".format(self.name)


class Pipe(IField):
    """
    Basic field pipe class
    """

    def __init__(self, field: IField):
        """
        Constructor

        :param field: field object
        :type field: IField
        """
        self.field = field
        self.name = field.name

    def val(self, event: Event):
        raise NotImplementedError("Cannot use Pipe superclass")

    def __signature__(self) -> str:
        """ Object signature for representation """
        return self.__class__.__name__

    def __repr_in__(self) -> str:
        """ Object representation to inherit """
        return "{}({})".format(
            self.__signature__(), self.field.__repr_in__())


class StrictPipe(Pipe):
    """
    Basic strict pipe class
    """
    def __init__(self, field: IField, strict: bool = False):
        """
        Constructor

        :param field: field object
        :type field: IField
        :param strict: strict mode, fail all filter if field isn't converible
            by the pipe, def=False
        :type strict: bool
        """
        Pipe.__init__(self, field)
        self.strict = strict

    def val(self, event: Event):
        raise NotImplementedError("Cannot use StrictPipe superclass")


class Int(StrictPipe):
    """
    Event field representation pipe
    converting field value to integer.
    If field is not convertible to integer
    and strict mode enabled, whole filter
    fails if reached condition containing
    this field.
    """

    def val(self, event: Event):
        """ Return value """
        try:
            return int(self.field.val(event))
        except ValueError:
            if self.strict:
                raise Break()
            else:
                raise Continue()


class Lower(Pipe):
    """
    Event field representation pipe
    making field value lowercase.
    """

    def val(self, event: Event):
        """ Return value """
        val = self.field.val(event)
        if isinstance(val, str):
            return val.lower()
        else:
            raise ProgrammingError


class ICond(ABC):
    """ Condition interface """

    @abstractmethod
    def check(self, event: Event) -> bool:
        """ Check method"""

    @abstractmethod
    def __repr_in__(self):
        """ Object representation to inherit"""

    def __or__(self, other) -> "CondGroup":
        """ Condition grouping with OR """
        return CondGroup(self, other, "__or__")

    def __and__(self, other) -> "CondGroup":
        """ Condition grouping with AND """
        return CondGroup(self, other, "__and__")

    def __repr__(self):
        """ Object representation """
        return "<{}.{} {}>".format(
            self.__module__, self.__class__.__name__, self.__repr_in__())

    def __str__(self):
        """ String representation """
        return self.__repr_in__()


class Cond(ICond):
    """
    Condition representation for filters
    """

    def __init__(self, field: IField, checker: ICheck):
        """ Constructor """
        self.field = field
        self.checker = checker

    def check(self, event: Event) -> bool:
        """ Check condition for event """
        try:
            return self.checker.check(self.field.val(event))
        except Continue:
            return False

    def __repr_in__(self):
        """ Object representation to inherit """
        return "{} {}".format(self.field.__repr_in__(),
                              self.checker.__repr_in__())


class CondGroup(ICond):
    """
    Condition group with logic operator
    representation
    """

    MAP_BOOL_METHOD = {
        "__and__": "and",
        "__or__": "or"
    }

    def __init__(self, c1: ICond, c2: ICond, method_name: str):
        """ Constructor """
        self.c1 = c1
        self.c2 = c2
        self.method_name = method_name

    def check(self, event: Event):
        """ Check condition group for event """
        r1 = self.c1.check(event)
        # Fail & conditions if first operand is False
        if not r1 and self.method_name == "__and__":
            return False
        # Succeed | conditions if first operand is True
        if r1 and self.method_name == "__or__":
            return True

        r2 = self.c2.check(event)

        method = getattr(r1, self.method_name)

        return method(r2)

    @staticmethod
    def _repr_c(c: ICond):
        """ Represent condition element """
        if isinstance(c, CondGroup):
            return "( {} )".format(c.__repr_in__())
        else:
            return c.__repr_in__()

    def __repr_in__(self):
        """ Object representation to inherit """
        return "{} {} {}".format(
            self._repr_c(self.c1),
            self.MAP_BOOL_METHOD[self.method_name],
            self._repr_c(self.c2))


class E(ICond):
    """
    Name exists check
    """
    def __init__(self, name: str):
        """
        Constructor

        :param name: Field name
        :type name: str
        """
        self.name = name.lower()

    def check(self, event: Event):
        """ Check condition """
        return self.name in event

    def __repr_in__(self):
        """ Object representation to inherit """
        return "exists(`event.{}`)".format(self.name)


class C(ICond):
    """
    Event class check
    """
    cls: Union[TEvent, str]
    invert: bool

    def __init__(self, cls: Union[TEvent, str], invert: bool = False):
        """
        Constructor

        :param cls: event class or event name
        :type cls: Union[Type[Event], str]
        :param invert: check if event is NOT of provided class, def=False
        :type invert: bool
        """
        self.cls = cls
        self.invert = invert

    def check(self, event: Event) -> bool:
        """ Check condition """
        if isinstance(self.cls, str):
            res = event.value.lower() == self.cls.lower()
        else:
            res = isinstance(event, self.cls)
        return not res if self.invert else res

    def __repr_in__(self):
        """ Object representation to inherit """
        if isinstance(self.cls, str):
            signature = '"{}"'.format(self.cls)
        else:
            signature = "<{}>".format(self.cls.__class__.__name__)
        return "event is {}".format(signature)


class Filter(object):
    """
    Filter class
    """

    def __init__(self, condition: ICond):
        """ Constructor """
        self.condition = condition

    def check(self, event: Event) -> bool:
        """ Check filter """
        try:
            return self.condition.check(event)
        except Break:
            return False

    def __str__(self):
        """ String representation """
        return "Filter({})".format(self.condition.__repr_in__())

    def __repr__(self):
        """ Object representation """
        return "<{}.{} {}>".format(
            self.__class__.__name__, self.__module__,
            self.condition.__repr_in__())
