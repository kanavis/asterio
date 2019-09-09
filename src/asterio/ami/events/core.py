"""
Asterisk AIO interface: core events
"""
from typing import Optional

from asterio.ami.event import Event


class AuthDetail(Event):
    """
    Provide details about an authentication section
    """

    ObjectType: Optional[str]
    ObjectName: Optional[str]
    Username: Optional[str]
    Password: Optional[str]
    Md5Cred: Optional[str]
    Realm: Optional[str]
    NonceLifetime: Optional[str]
    AuthType: Optional[str]
    EndpointName: Optional[str]
