#!/usr/bin/env python
"""
Asterio: AMI dump
"""

import argparse
import asyncio
import getpass
import configparser
import os
import sys

from asterio.ami.client import ManagerClient
from asterio.ami.filter import Filter

CONFIG_FILENAME=".amidump"


class FinalError(Exception): ...


class FilterError(Exception):
    def __init__(self, msg, pos):
        Exception.__init__(self, msg)
        self.pos = pos


def program():
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
    parser.add_argument("-P", dest="port", type=int, default=5038,
                        help="AMI server port")
    parser.add_argument("-u", dest="username", type=str, help="AMI username")
    parser.add_argument("-p", dest="password", type=str, nargs='?', const=True,
                        help="AMI password (request from CLI if no value)")
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
            raise FinalError("No server port provided in config or args")
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

    print(server, port, username, password)

    """ Parse filters """
    filter_str = " ".join(args.filter)
    filter = Filter(parse_filter(filter_str))
    print(filter)


def left_strip(string, pos):
    """ Left strip string """
    while string and string[0] == " ":
        string = string[1:]
        pos += 1
    return string, pos


def next_token(string, pos):
    """ Get filter token, rest string and position """

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
    return sub_ex, string, sub_ex_pos, pos


def next_expression(string, pos):
    """ Parse next expression """
    token = next_token()

    return string, pos


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
        else:
            # Next token is expression
            cond, string, pos = next_expression(string, pos)
        if final_cond is not None:
            # Not a first token, apply operator
            assert operator is not None
            assert operator_pos is not None
            if operator.lower() == "and":
                final_cond = final_cond & operator
            elif operator.lower() == "or":
                final_cond = final_cond | operator
            else:
                raise FilterError("Unexpected expression (logical operator "
                                  "expected)", operator_pos)
        else:
            # This was the first token
            assert operator is None
            final_cond = cond

    return final_cond


def main():
    """ Wrap program """
    try:
        program()
    except FinalError as err:
        print(err, file=sys.stderr)
        sys.exit(255)


main()
