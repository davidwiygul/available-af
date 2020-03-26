# hfshared.py

"""Basic shared HeirFlow datastructures and classes."""

from enum import Enum
import random
from typing import List, NamedTuple

import psycopg2
import pika


class StatusUpdate(Enum):
    """Update on the status of a multischeduler."""
    UNAVAILABLE = 'unavailable'
    AVAILABLE = 'available'
    LEADER = 'leader'


class Message(NamedTuple):
    """Message from a multischeduler reporting on a multischeduler.

    Attributes:
        sender: A string representation of the public IP address of the
                multischeduler issuing the message.
        subject: A string representation of the public IP address of the
                 multischeduler being reported on.
        status: A StatusUpdate indicating the reported status of the subject.
    """

    sender: str
    subject: str
    status: StatusUpdate

    def __str__(self):
        return (f"sender={self.sender}, "
                f"self.subject={self.subject}, "
                f"status={str(self.status.value)}")

class Credentials(NamedTuple):
    """Simply stores login credentials, a username and password, as strings."""

    user: str
    password: str


class Database:
    """Minimalist abstraction of a database connection.

    Presently only Postgres databases are supported, via psycopg2.

    Attributes:
        host_ip: A string representation of the database server's IP address.
        name: A string storing the database's name.
        conn: A psycopg2 connection object.
        cur: A psycopg2 cursor object.
    """

    def __init__(self, host_ip: str, name: str) -> None:
        """Initializes Database with given name and server IP address."""
        self.host_ip = host_ip
        self.name = name
        self.conn: psycopg2.extensions.connection = None
        self.cur: psycopg2.extensions.cursor = None

    def connect(self,
                credentials: Credentials) -> None:
        """Given Credentials, establishes a connection and cursor."""

        self.conn = psycopg2.connect(host=self.host_ip,
                                     database=self.name,
                                     user=credentials.user,
                                     password=credentials.password)
        self.cur = self.conn.cursor()

    def disconnect(self) -> None:
        """Closes connection, if it exists, and clears conn and cur."""
        if self.conn:
            self.conn.close()
            self.conn = None
            self.cur = None


class QueueHost:
    """Minimialist abstraction of a message queue connection.

    Presently only RabbitMQ queues are supported, via pika.

    Attributes:
        host_ips: A list of string representations of queue cluster members' IP
                  addresses.
        vhost: A string storing the name of the queue's virtual host.
        connection: A pika blocking connection object.
        channel: A pika channel.
    """

    def __init__(self, host_ips: List[str], vhost: str):
        """Initializes QueueHost with given vhost name and server IP address."""
        self.host_ips = host_ips
        self.vhost = vhost
        self.connection: pika.BlockingConnection = None
        self.channel: pika.channel = None

    def connect(self, credentials: Credentials) -> None:
        """Given Credentials, establishes a connection and cursor."""
        random.shuffle(self.host_ips)
        cred = pika.PlainCredentials(credentials.user,
                                     credentials.password)
        parameters_list = [pika.ConnectionParameters(host=host,
                                                     port=5672,
                                                     virtual_host=self.vhost,
                                                     credentials=cred)
                           for host in self.host_ips]

        self.connection = pika.BlockingConnection(parameters_list)
        self.channel = self.connection.channel()

    def disconnect(self) -> None:
        """Closes existing connection and clears connection and channel."""
        if self.connection:
            self.channel.close()
            self.channel = None
            self.connection.close()
            self.connection = None


class Services(NamedTuple):
    """Bundles Database and QueueHost services required by a Multischeduler."""
    db: Database
    q: QueueHost
