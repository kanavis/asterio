"""
Asterisk AIO interface: event filtering classes
"""

import re
from abc import ABC, abstractmethod
from typing import Any

from asterio.ami.errors import ProgrammingError
from asterio.ami.event import Event


class Break(Exception):
    """
    Exception to break condition test.
    Used when field doesn't exist
    """


class ICheck(ABC):
    """
    Filter checks abstract class
    """

    def __repr__(self):
        """ Representation """
        return "<{} {}>".format(self.__class__.__name__, self.__repr_in__())

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


class F(IField):
    """
    Event field representation for filters.
    If field doesn't exist, whole filter fails
    if reached condition containing this field.
    To prevent it, precede check with
    "E(name) &"
    """

    def __init__(self, name: str):
        """
        Constructor

        :param name: Field name
        :type name: str
        """
        self.name = name.lower()

    def val(self, event: Event) -> Any:
        """ Return value from event """
        try:
            return event[self.name]
        except KeyError:
            raise Break

    def __repr_in__(self):
        """ Object representation to inherit """
        return "`{}`".format(self.name)

    def __repr__(self):
        """ Object representation """
        return "<{}.{} {}>".format(self.__class__.__name__, self.__module__,
                                   self.name)


class Pipe(IField):
    """
    Basic field pipe class
    """

    def __init__(self, field: IField):
        self.field = field
        self.name = field.name

    def val(self, event: Event):
        raise NotImplementedError("Cannot use Pipe superclass")

    def __signature__(self) -> str:
        """ Object signature for representation """
        return self.__class__.__name__

    def __repr_in__(self) -> str:
        """ Object representation to inherit """
        return "{} | {}".format(
            self.field.__repr_in__(), self.__signature__())


class Int(Pipe):
    """
    Event field representation pipe
    converting field value to integer.
    If field is not convertible to integer,
    whole filter fails if reached condition
    containing this field.
    """

    def val(self, event: Event):
        """ Return value """
        try:
            return int(self.field.val(event))
        except ValueError:
            raise Break()


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
            self.__class__.__name__, self.__module__, self.__repr_in__())

    def __str__(self):
        """ String representation """
        return object.__repr__(self)


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
        return self.checker.check(self.field.val(event))

    def __repr_in__(self):
        """ Object representation to inherit """
        return "{} {}".format(self.field.name, self.checker.__repr_in__())


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

    def __repr_in__(self):
        """ Object representation to inherit """
        return "({}) {} ({})".format(
            self.c1.__repr_in__(), self.MAP_BOOL_METHOD[self.method_name],
            self.c2.__repr_in__())


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
        return "`{}` exists".format(self.name)


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
        return object.__repr__(self)

    def __repr__(self):
        """ Object representation """
        return "<{}.{} {}>".format(
            self.__class__.__name__, self.__module__,
            self.condition.__repr_in__())
