"""
Asterisk AIO interface: login action
"""
from asterio.ami.action import Action


class LoginAction(Action):
    ACTION = "login"

    def __init__(self, username: str, secret: str):
        """
        Constructor

        :param username: auth username
        :type username: str
        :param secret: auth secret
        :type secret: str
        """
        Action.__init__(self, self.ACTION, {
            "username": username,
            "secret": secret
        })
