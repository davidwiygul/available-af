# multischeduler.py

"""Script to coordinate Airflow schedulers via a database.

Intended to be run as a daemon, this script controls an Airflow scheduler
process on the same machine on which it is run, determining when to activate
(or in rare cases deactivate) the scheduler for which it's responsible by
coordinating via a database with identical scripts managing Airflow schedulers
on other machines.

The script assumes a Postgres database (though CockroachDB may be supported in
a future release) containing a table
Schedulers(ip varchar(15), birth timestamp, latest timestamp),
and the script will interact with no other tables. For proper functioning this
database should also house the Airflow metadata store.

Secondarily the script sends updates on the status of schedulers to the message
queue (assumed RabbitMQ and on the same server as the task queue) to be picked
up by the monitoring script interface.py.

Database and message queue connection data, along with certain tunable timing
parameters, are imported from multischeduler.ini.
"""

import configparser
import pickle
import signal
import subprocess
import time
import urllib.request
from datetime import datetime, timedelta
from typing import Dict

import psycopg2
from psycopg2 import sql

import pika

from hfshared import (Credentials,
                      Database,
                      Message,
                      QueueHost,
                      Services,
                      StatusUpdate)


class Multischeduler:
    """Multischeduler class docstring"""

    AWS_MD_URL = 'http://169.254.169.254/latest/meta-data/public-ipv4'

    def __init__(self,
                 services: Services,
                 credentials: Dict[str, Credentials],
                 timing: Dict[str, timedelta]) -> None:
        self.services = services
        self.credentials = credentials
        self.timing = timing
        self.ip: str = None
        self.birth: datetime = None
        self.leader: str = None
        self.active = {self.ip}
        self.process: subprocess.Popen = None

        self.set_public_ip()
        self.reset()

    def set_public_ip(self) -> None:
        """docstring"""
        self.ip = urllib.request.urlopen(self.AWS_MD_URL).read().decode('utf8')

    def reset(self) -> None:
        """docstring"""
        self.leader = None
        self.active = {self.ip}
        self.process = None
        self.db_connect()
        self.q_connect()
        self.services.q.channel.queue_declare('news')
        self.register_birth()
        self.services.q.disconnect()
        self.services.db.disconnect()
        self.loop()

    def db_connect(self) -> None:
        """docstring"""
        try:
            self.services.db.connect(self.credentials['db'])
        except psycopg2.OperationalError:
            self.report(subject=self.ip, status=StatusUpdate.UNAVAILABLE)
            self.on_connection_failure()

    def q_connect(self):
        """docstring"""
        try:
            self.services.q.connect(self.credentials['q'])
        except pika.exceptions.AMQPConnectionError:
            self.on_connection_failure()

    def on_connection_failure(self):
        """docstring"""
        if self.is_leader():
            self.relinquish_leadership()
        self.report(subject=self.ip, status=StatusUpdate.UNAVAILABLE)
        time.sleep(30)
        self.reset()

    def register_birth(self) -> None:
        """docstring"""
        insert = (f"INSERT INTO schedulers (ip, birth, latest)\n"
                  f"VALUES (\'{self.ip}\', "
                  f"CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)\n"
                  f"RETURNING birth")
        self.services.db.cur.execute(sql.SQL(insert))
        self.birth = self.services.db.cur.fetchone()[0]
        self.services.db.conn.commit()
        self.report(subject=self.ip, status=StatusUpdate.AVAILABLE)

    def loop(self):
        """docstring"""
        while True:
            time.sleep(self.timing['time_between_checkins'].total_seconds())
            self.db_connect()
            self.q_connect()
            self.toss_stale()
            self.send_news()
            self.fall_in_line()
            self.take_stock()
            if self.is_leader() and self.process.returncode:
                self.relinquish_leadership()
            self.services.db.disconnect()
            self.services.q.disconnect()

    def toss_stale(self) -> None:
        """docstring"""
        wait = self.timing['grace_period']
        delete = (f"DELETE FROM schedulers WHERE "
                  f"latest<(CURRENT_TIMESTAMP-'{wait}'::interval)")
        self.services.db.cur.execute(sql.SQL(delete))
        self.services.db.conn.commit()

    def send_news(self) -> None:
        """docstring"""
        insert = (f"INSERT INTO schedulers (ip, birth, latest)\n"
                  f"VALUES (\'{self.ip}\', '{self.birth}', CURRENT_TIMESTAMP)")
        self.services.db.cur.execute(sql.SQL(insert))
        self.services.db.conn.commit()

    def fall_in_line(self) -> None:
        """docstring"""
        old_leader = self.leader
        was_leader = self.is_leader()
        self.update_leader()
        if self.leader != old_leader:
            if was_leader and not self.is_leader():
                self.relinquish_leadership()
            elif self.is_leader() and not was_leader:
                self.accept_leadership()
            if old_leader:
                self.report(subject=old_leader,
                            status=StatusUpdate.UNAVAILABLE)
            self.report(subject=self.leader, status=StatusUpdate.LEADER)

    def take_stock(self) -> None:
        """docstring"""
        formerly_active = self.active
        self.update_active()
        if self.ip not in self.active:
            if self.is_leader():
                self.relinquish_leadership()
            self.reset()
        retired = formerly_active - self.active
        for scheduler in retired:
            self.report(subject=scheduler, status=StatusUpdate.UNAVAILABLE)

    def update_leader(self) -> None:
        """docstring"""
        select = ("SELECT x.ip FROM schedulers x\n"
                  "WHERE x.birth=\n"
                  "(SELECT MIN(y.birth) FROM schedulers y)")
        self.services.db.cur.execute(sql.SQL(select))
        self.leader = self.services.db.cur.fetchone()[0]
        self.services.db.conn.commit()

    def update_active(self) -> None:
        """docstring"""
        select = f"SELECT DISTINCT ip from schedulers"
        self.services.db.cur.execute(sql.SQL(select))
        self.active = {record[0] for record
                       in self.services.db.cur.fetchall()}

    def accept_leadership(self) -> None:
        """docstring"""
        time.sleep(self.timing['patience'])
        self.process = subprocess.Popen(['airflow', 'scheduler'],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL)
        self.send_news()

    def relinquish_leadership(self) -> None:
        """docstring"""
        self.process.send_signal(signal.SIGINT)
        self.reset()

    def is_leader(self) -> bool:
        """docstring"""
        return self.leader and self.leader == self.ip

    def report(self, subject, status: StatusUpdate) -> None:
        """docstring"""
        message = Message(sender=self.ip, subject=subject, status=status)
        self.services.q.channel.basic_publish(exchange='',
                                              routing_key='news',
                                              body=pickle.dumps(message))
        print(message)


def main() -> None:
    """docstring"""
    # read timing specs and database login info from ini file
    config = configparser.ConfigParser(inline_comment_prefixes='#')
    config.read('multischeduler.ini')
    db = config['DB']
    q = config['Q']
    timing = {key: timedelta(seconds=float(value))
              for key, value in config['TIMING'].items()}

    db_cred = Credentials(user=db['db_user'], password=db['db_pwd'])
    q_cred = Credentials(user=q['q_user'], password=q['q_pwd'])
    pgdb = Database(host_ip=db['db_ip'], name=db['database'])
    qvh = QueueHost(host_ip=q['q_ip'], vhost=q['q_vhost'])
    servs = Services(pgdb, qvh)
    creds = {'db': db_cred, 'q': q_cred}
    times = {'grace_period': timing['grace_period'],
             'time_between_checkins': timing['time_between_checkins'],
             'patience': timing['patience'].total_seconds()}
    Multischeduler(servs, creds, times)


if __name__ == '__main__':
    main()
