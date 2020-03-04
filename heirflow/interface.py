# interface.py
"""module docstring"""

# want to be able to get status if interface is restarted
# should probably query db for this (rare event, so minimal load)

# absorb ip type into library files

import configparser
from os import system
import pickle
import threading
from typing import Any, Dict, List, Union

from hfshared import Credentials, Message, QueueHost, StatusUpdate


News = Union[StatusUpdate, str]


class ReportedScheduler:
    """docstring"""

    def __init__(self, key: int,
                 ip: str,
                 cluster,
                 news: News) -> None:
        self.key = key
        self.ip = ip
        self.cluster = cluster
        self.available = False
        self.leading = False
        self.leader: str = None
        self.update(news)

    def update(self, news):
        """docstring"""
        if news == StatusUpdate.AVAILABLE:
            self.available = True
        if news == StatusUpdate.UNAVAILABLE:
            self.available = False
            self.leading = False
            self.leader = None
        if news == StatusUpdate.LEADER:
            self.leading = True
        if isinstance(news, str):
            self.leader = news

    def report(self) -> str:
        """docstring"""
        head = f"Scheduler {self.key} ({self.ip}) is "
        if self.leading:
            tail = "leading."
            style = "\033[35;1;48m"
        elif self.available:
            tail = "available"
            if self.leader:
                leader_key = self.cluster.dict[self.leader].key
                tail += " and following "
                tail += "\033[35;1;48m" + f"Scheduler {leader_key}."
            else:
                tail += "."
            style = "\033[32;1;48m"
        else:
            tail = "unavailable."
            style = "\033[31;1;48m"
        return style + head + tail + "\033[0m"

    def update_key(self, key: int) -> None:
        """docstring"""
        self.key = key


class SchedulerCluster:
    """docstring"""

    def __init__(self) -> None:
        self.dict: Dict[str, ReportedScheduler] = dict()
        self.list: List[ReportedScheduler] = []

    def consume(self, message: Message):
        """docstring"""
        recipients: List[str] = [message.subject]
        news: List[News] = [message.status]
        if message.status == StatusUpdate.LEADER:
            recipients.append(message.sender)
            news.append(message.subject)
        for recipient, news in zip(recipients, news):
            if recipient not in self.dict:
                new_rs = ReportedScheduler(key=len(self.list) + 1,
                                           ip=recipient,
                                           cluster=self,
                                           news=news)
                self.dict[recipient] = new_rs
                self.list.append(new_rs)
            else:
                self.dict[recipient].update(news)

    def report(self) -> None:
        """docstring"""
        system('clear')
        for scheduler in self.list:
            print(scheduler.report())

    def is_valid_key(self, wannakey: Any) -> bool:
        """docstring"""
        try:
            integrated = int(wannakey)
            return 0 < integrated <= len(self.list)
        except BaseException:
            return False

    def key_to_ip(self, str_key: str) -> str:
        """docstring"""
        return self.list[int(str_key) - 1].ip

    def remove(self, str_key: str) -> None:
        """docstring"""
        del self.dict[self.key_to_ip(str_key)]
        del self.list[int(str_key) - 1]
        self.update_keys()

    def update_keys(self) -> None:
        """docstring"""
        for index, scheduler in enumerate(self.list):
            scheduler.update_key(index + 1)


class CommandPrompt():
    """docstring"""
    def __init__(self, schedulers: SchedulerCluster, ssh_key: str) -> None:
        self.schedulers = schedulers
        self.listening = True
        self.ssh_key = ssh_key
        system('clear')
        while self.listening:
            self.process(input())

    def process(self, cmd: str) -> None:
        """docstring"""
        parsed = cmd.split()

        if cmd in {'exit', 'quit', 'quit()'}:
            print("Goodbye!")
            self.listening = False

        elif cmd == 'report':
            self.schedulers.report()

        elif cmd == 'update':
            print("Stay tuned: this functionality is coming soon!")

        elif len(parsed) == 2 and self.schedulers.is_valid_key(parsed[1]):
            action, key = parsed
            if action in {'start', 'stop'}:
                ip = self.schedulers.key_to_ip(key)
                service = "airflow-multischeduler"
                remote_cmd = f"sudo systemctl {action} {service}"
                local_cmd = "ssh -o ConnectTimeout=5"
                local_cmd += " -o StrictHostKeyChecking=no"
                local_cmd += f" -i {self.ssh_key} ubuntu@{ip} {remote_cmd}"
                system(local_cmd)
                self.schedulers.report()
                print(f"...attempted to {action} Scheduler {key}...")

            elif action in {'delete', 'remove'}:
                self.schedulers.remove(key)
                self.schedulers.report()

            elif action == 'block':
                print("Stay tuned: this functionality is coming soon!")

        else:
            print("...command not understood...")


class MessageConsumer:
    """docstring"""
    def __init__(self,
                 q: QueueHost,
                 credentials: Credentials,
                 cluster: SchedulerCluster):
        self.cluster = cluster
        q.connect(credentials)
        q.channel.queue_declare(queue='news')
        q.channel.basic_consume(queue='news',
                                on_message_callback=self.callback,
                                auto_ack=True)
        self.thread = threading.Thread(target=q.channel.start_consuming)
        self.thread.daemon = True
        self.thread.start()

    def callback(self, ch, method, properties, body) -> None:
        """docstring"""
        self.cluster.consume(pickle.loads(body))
        self.cluster.report()


def main() -> None:
    """docstring"""
    config = configparser.ConfigParser(inline_comment_prefixes='#')
    config.read('interface.ini')
    q = config['Q']
    ssh_key = config['SSH']['ssh_key']

    q_cred = Credentials(user=q['q_user'], password=q['q_pwd'])
    qvh = QueueHost(host_ip=q['q_public_ip'], vhost=q['q_vhost'])

    schedulers = SchedulerCluster()

    MessageConsumer(qvh, q_cred, schedulers)

    CommandPrompt(schedulers, ssh_key)


if __name__ == '__main__':
    main()
