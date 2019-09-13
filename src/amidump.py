#!/usr/bin/env python
"""
Asterio: AMI dump
"""

import argparse
import logging.config
import asyncio
import getpass
import configparser
import os
import re
import sys

from asterio.ami.client import ManagerClient
from asterio.ami.errors import ConnectError
from asterio.ami.filter import Filter, E, C, F, Int

CONFIG_FILENAME = ".amidump"

RE_FIELD_NAME = re.compile(r"^\w+$")
RE_EVENT_NAME = re.compile(r"^\w+$")
loop = asyncio.get_event_loop()


# Windows Ctrl+C asyncio fix
if os.name == 'nt':
    def wakeup():
        # Call again
        loop.call_later(0.1, wakeup)
    wakeup()


class FinalError(Exception): ...


class FilterError(Exception):
    def __init__(self, msg, pos):
        Exception.__init__(self, msg)
        self.pos = pos


async def program():
    """ Main function """
    """ Parse arguments"""
    parser = argparse.ArgumentParser(
        description="Asterisk manager events dumper\n"
                    "Connect with a -s 1.2.3.4 -P 5050 -u user -p [password]\n"
                    f"or with ~/{CONFIG_FILENAME} (section [amidump], \n"
                    "options: server, port, username and password",
        formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-s", dest="server", type=str,
                        help="AMI server address")
    parser.add_argument("-P", dest="port", type=int, help="AMI server port")
    parser.add_argument("-u", dest="username", type=str, help="AMI username")
    parser.add_argument("-p", dest="password", type=str, nargs='?', const=True,
                        help="AMI password (request from CLI if no value)")
    parser.add_argument("-d", "--debug", action="store_true",
                        help="enable debug")
    parser.add_argument("-D", "--debug-full", action="store_true",
                        help="enable debug with packet content")
    parser.add_argument("--debug-filter", action="store_true",
                        help="debug filter expression and exit")
    parser.add_argument("-l", "--line", action="store_true",
                        help="Inline event display")
    parser.add_argument("-f", "--fields", nargs="+",
                        help="Show only this fields")
    parser.add_argument('filter', nargs='*')

    args = parser.parse_args()

    """ Parse config """
    config = None
    if os.environ["HOME"]:
        config_file = os.path.join(os.environ["HOME"], CONFIG_FILENAME)
        if os.path.isfile(config_file):
            # Parse file
            config = {}
            cfg_parser = configparser.ConfigParser()
            try:
                cfg_parser.read(config_file)
            except configparser.Error as err:
                raise FinalError(f"Config file: "
                                 f"{err.__class__.__name__}: {err}")

            if "amidump" not in cfg_parser:
                raise FinalError("No amidump section in config file "
                                 f"{config_file}")

            # Extract values
            cfg_dict = {k: v for k, v in cfg_parser["amidump"].items()}
            for key in ("server", "port", "username", "password"):
                if key in cfg_dict:
                    config[key] = cfg_dict[key]
                    del cfg_dict[key]

            # Raise excess values
            if cfg_dict:
                raise FinalError(f"Wrong field {next(iter(cfg_dict))} in "
                                 f"config file {config_file}")

            # Raise wrong format
            if "port" in config:
                try:
                    config["port"] = int(config["port"])
                except ValueError:
                    raise FinalError(f"Invalid port value {config['port']} in "
                                     f"config file {config_file}")

    """ Make final values """
    if args.server is not None:
        server = args.server
    else:
        if config is None or "server" not in config:
            raise FinalError("No server address provided in config or args")
        server = config["server"]
    if args.port is not None:
        port = args.port
    else:
        if config is None or "port" not in config:
            port = 5038
        else:
            port = config["port"]
    if args.username is not None:
        username = args.username
    else:
        if config is None or "username" not in config:
            raise FinalError("No username provided in config or args")
        username = config["username"]
    if args.password is not None:
        if args.password is True:
            # Request password
            password = getpass.getpass()
        else:
            password = args.password
    else:
        if config is None or "password" not in config:
            raise FinalError("No password provided in config or args")
        password = config["password"]

    # Enable debug
    if args.debug or args.debug_full or args.debug_filter:
        logging.config.dictConfig({
            'version': 1,
            'formatters': {
                'standard': {
                    'format': '[DEBUG] %(message)s'
                },
            },
            'handlers': {
                'default': {
                    'level': 'DEBUG',
                    'formatter': 'standard',
                    'class': 'logging.StreamHandler',
                    'stream': 'ext://sys.stdout',
                },
            },
            'loggers': {
                'asterio': {
                    'handlers': ['default'],
                    'level': 'DEBUG'
                },
            }
        })

    """ Parse filters """
    filter_str = " ".join(args.filter)
    try:
        filter_cond = parse_filter(filter_str)
        if args.debug or args.debug_filter:
            print("[DEBUG] Filter: {}".format(filter_cond))
            if args.debug_filter:
                sys.exit(0)

    except FilterError as err:
        if err.pos > 18:
            prefix = "..." + filter_str[err.pos-15:err.pos]
        else:
            prefix = filter_str[:err.pos]
        err_str = prefix + ">here>" + filter_str[err.pos:]
        raise FinalError(f"Error parsing filter.\n{err} at:\n{err_str}")

    if filter_cond is None:
        filter_obj = None
    else:
        filter_obj = Filter(filter_cond)

    """ Connect to server """
    client = ManagerClient(loop)
    try:
        await client.connect(server, port, username, password)
    except ConnectError as err:
        raise FinalError(f"Couldn't connect to AMI server: {err}")

    """ Listen to the events """
    while True:
        # Get event
        event = await client.get_event()

        # Apply filter
        if filter_obj is not None:
            if not filter_obj.check(event):
                continue

        # Show event
        print(f">> EVENT {event.value}", end="")
        if args.line:
            print(" ", end="")
        else:
            print()
        for k, v in event.items():
            if k.lower() == "event":
                continue
            if args.fields:
                if not k.lower() in args.fields:
                    continue
            if args.line:
                print(f"{k}: {v}; ", end="")
            else:
                print(f"   {k}: {v}")
        if args.line:
            print()


def left_strip(string, pos):
    """ Left strip string """
    while string and string[0] == " ":
        string = string[1:]
        pos += 1
    return string, pos


def next_token(string, pos):
    """ Get filter token, rest string and position """
    if string == "":
        raise FilterError("Unexpected end of expression", pos)
    if string[0] in ('"', "'"):
        # Quotes, return value inside quotes
        quote = string[0]
        val = quote
        string = string[1:]
        pos += 1
        parts = string.split(val, 1)
        if len(parts) != 2:
            raise FilterError("Unclosed quotation", pos)
        val += parts[0]
        val += quote
        string = parts[1]
        pos += len(parts[0]) + 1
    else:
        # Get value until nearest space
        parts = string.split(" ", 1)
        val = parts[0]
        pos += len(val)
        pos += 1
        if len(parts) == 1:
            string = ""
        else:
            string = parts[1]

    string, pos = left_strip(string, pos)
    return val, string, pos


def next_subexpression(string, pos):
    """ Get next subexpression """
    assert string[0] == "("
    idx = string.rfind(")")
    if idx == -1:
        raise FilterError("Unclosed quote", pos)
    sub_ex = string[1:idx]
    string = string[idx+1:]
    sub_ex_pos = pos + 1
    pos += len(sub_ex) + 2
    sub_ex, sub_ex_pos = left_strip(sub_ex, sub_ex_pos)
    sub_ex.strip()
    if not sub_ex:
        raise FilterError("Empty subexpression", sub_ex_pos)
    string, pos = left_strip(string, pos)
    return sub_ex, string, sub_ex_pos, pos


def parse_field(string, pos):
    """ Parse field expression """
    if not string.startswith("event."):
        raise FilterError("event.field expression expected", pos)
    string = string[6:]
    if not RE_FIELD_NAME.match(string):
        raise FilterError(f"Wrong field name format ({string})", pos + 6)
    return F(string)


def unquote(string):
    """ Unquote string """
    if ((string[0] == '"' and string[-1] == '"') or
            (string[0] == "'" and string[-1] == "'")):
        return string[1:-1]
    else:
        return string


def expect_int_expr(string, pos):
    """ Expect integer expression """
    if isinstance(string, F):
        raise FilterError("Integer expression expected", pos)
    try:
        return int(string)
    except ValueError:
        raise FilterError("Integer expression expected", pos)


def next_expression(string, pos):
    """ Parse next expression """
    # Get left part
    left_pos = pos
    left, string, pos = next_token(string, pos)
    assert left[0] != "("

    if left.lower() == "exists":
        # Exists expression, next part must be a column
        right_pos = pos
        right, string, pos = next_token(string, pos)
        if right.startswith("event."):
            right = right[6:]
            if not right:
                raise FilterError("Wrong syntax", right_pos)
        else:
            right = unquote(right)

        if not RE_FIELD_NAME.match(right):
            raise FilterError(f"Wrong field name format ({right})",
                              right_pos)

        # Return exists cond
        cond = E(right)
    elif left.lower() == "event":
        # Event name expression
        # Check == operator
        operator_pos = pos
        operator, string, pos = next_token(string, pos)
        if operator != '=' and operator != '==':
            raise FilterError("== operator expected", operator_pos)

        # Get right
        right_pos = pos
        right, string, pos = next_token(string, pos)
        right = unquote(right)
        if not RE_EVENT_NAME.match(right):
            raise FilterError("Wrong event name format", right_pos)

        cond = C(right)

    else:
        # Three tokens expression
        left_expr = parse_field(left, left_pos)
        operator_pos = pos
        operator, string, pos = next_token(string, pos)
        right_pos = pos
        right, string, pos = next_token(string, pos)

        # Parse right side
        if right.startswith("event."):
            right_expr = parse_field(right, right_pos)
        else:
            right_expr = unquote(right)

        # Parse operator
        if operator == "=" or operator == "==":
            cond = (left_expr == right_expr)
        elif operator == "!=":
            cond = (Int(left_expr) != right_expr)
        elif operator == ">":
            cond = (Int(left_expr) > expect_int_expr(right_expr, right_pos))
        elif operator == ">=":
            cond = (Int(left_expr) >= expect_int_expr(right_expr, right_pos))
        elif operator == "<":
            cond = (Int(left_expr) < expect_int_expr(right_expr, right_pos))
        elif operator == "<=":
            cond = (Int(left_expr) <= expect_int_expr(right_expr, right_pos))
        else:
            raise FilterError("Conditional operator (==,<,!= etc.) expected",
                              operator_pos)

    return cond, string, pos


def parse_filter(f_str, pos=0):
    """ Parse filter str """
    string = f_str

    # Left strip
    string, pos = left_strip(string, pos)

    # Parse string into expressions
    final_cond = None
    while string:
        if final_cond is not None:
            # Not a first token, operator needed
            operator_pos = pos
            operator, string, pos = next_token(string, pos)
            if not string:
                raise FilterError("Unexpected end of expression", pos)
        else:
            operator = None
            operator_pos = None

        # Parse next condition
        if string[0] == "(":
            # Next token is subexpression
            sub_ex, string, sub_ex_pos, pos = next_subexpression(string, pos)
            cond = parse_filter(sub_ex, sub_ex_pos)
            print(string)
        else:
            # Next token is expression
            cond, string, pos = next_expression(string, pos)
        if final_cond is not None:
            # Not a first token, apply operator
            assert operator is not None
            assert operator_pos is not None
            if operator.lower() == "and":
                final_cond = final_cond & cond
            elif operator.lower() == "or":
                final_cond = final_cond | cond
            else:
                raise FilterError("Unexpected expression (logical operator "
                                  "expected)", operator_pos)
        else:
            # This was the first token
            assert operator is None
            final_cond = cond

    return final_cond


async def main():
    """ Wrap program """
    try:
        await program()
    except FinalError as err:
        print(err, file=sys.stderr)
        sys.exit(255)


""" Run in event loop """
try:
    loop.run_until_complete(main())
except KeyboardInterrupt:
    print("Keyboard interrupt", file=sys.stderr)
    sys.exit(0)
