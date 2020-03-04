# hfshared.py

"""module docstring"""

from enum import Enum
from typing import NamedTuple

import psycopg2
import pika


class StatusUpdate(Enum):
    """docstring"""
    UNAVAILABLE = 'unavailable'
    AVAILABLE = 'available'
    LEADER = 'leader'


class Message(NamedTuple):
    """docstring"""
    sender: str
    subject: str
    status: StatusUpdate

    def __str__(self):
        return (f"sender={self.sender}, "
                f"self.subject={self.subject}, "
                f"status={str(self.status.value)}")

class Credentials(NamedTuple):
    """Simply stores login credentials."""
    user: str
    password: str


class Database:
    """Database class docstring"""

    def __init__(self, host_ip: str, name: str) -> None:
        self.host_ip = host_ip
        self.name = name
        self.conn = None
        self.cur = None

    def connect(self,
                credentials: Credentials) -> psycopg2.extensions.connection:
        """connect docstring"""

        self.conn = psycopg2.connect(host=self.host_ip,
                                     database=self.name,
                                     user=credentials.user,
                                     password=credentials.password)
        self.cur = self.conn.cursor()

    def disconnect(self) -> None:
        """disconnect docstring"""
        self.conn.close()
        self.conn = None
        self.cur = None


class QueueHost:
    """QueueHost docstring"""

    def __init__(self, host_ip, vhost):
        self.host_ip = host_ip
        self.vhost = vhost
        self.connection = None
        self.channel = None

    def connect(self, credentials: Credentials) -> None:
        """docstring"""
        cred = pika.PlainCredentials(credentials.user,
                                     credentials.password)
        parameters = pika.ConnectionParameters(host=self.host_ip,
                                               port=5672,
                                               virtual_host=self.vhost,
                                               credentials=cred)

        self.connection = pika.BlockingConnection(parameters)
        self.channel = self.connection.channel()

    def disconnect(self) -> None:
        """docstring"""
        self.channel.close()
        self.channel = None
        self.connection.close()
        self.connection = None


class Services(NamedTuple):
    """docstring"""
    db: Database
    q: QueueHost
