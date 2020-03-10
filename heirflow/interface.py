# interface.py

"""Simple monitoring tool for multischedulers.

This program's primary purpose is to receive messages sent by multischedulers
about multischedulers and to display the information so gleaned about each
multischeduler. The messages are exchanged via a message queue. Schedulers
are discovered when messages are sent about them. For each known sheduler
the program indicates whether or not it is available and, if it is available,
whether or not it is the leader (the scheduler currently active or on duty)
and, if it is available but not leading, what scheduler it is following
(that is acknowleding as the leader).
The program also supports the following commands.

    update
        queries database directly to determine and display available
        multischedulers and leader

    stop [number labeling scheduler, as displayed on terminal]
        sends command via ssh to stop systemd airflow-multischeduler service

    start [number labeling scheduler, as displayed on terminal]
        sends command via ssh to start systemd airflow-multischeduler service

    report
        clears screen and last known status of all known multischedulers

    remove [or] delete [number labeling scheduler]
        deletes a multischeduler from the reporting list
        (but does not actually shut down or sever from the cluster this
        multischeduler, which, if active, may continue to be the subject
        of reports and so may be added back to the reporting list)

    exit [or] quit [or] quit()
        exits the program

Connection data for the database and queue are imported from interface.ini.

It might also be useful to implement block and unblock commands, which could
modify ip tables on the database and queue, but such functionality is not yet
available (and would require knowledge of the affected multischeduler's
private IP address, perhaps most easily obtained via ssh using the public IP
address).
"""

import configparser
from os import system
import pickle
import threading
from typing import Any, Dict, List, Union

from hfshared import Credentials, Database, Message, QueueHost, StatusUpdate


News = Union[StatusUpdate, str]
"""Essential data obtained from a Message (see hfshared module),
   either a StatusUpdate (see hfshared) or a string representation of the
   public IP address of a scheduler reported as leader.
"""


class ReportedScheduler:
    """Representation of a multischeduler as reconstructed from reports.

    The fundamental information captured here is whether or not the scheduler
    is currently available and what scheduler it is following. This information
    is initially set and subsequently updated via the update method, based on
    given News. The report function returns a string summarizing the
    scheduler's status.

    Attributes:
        key: An integer to identify, concisely, the multischeduler.
        ip: A string representation of the multischeduler's public IP address.
        cluster: A SchedulerCluster (below), to which this scheduler belongs.
        available: A boolean indicating availability of this scheduler.
        leading: A boolean indicating whether or not this scheduler is leading.
    """

    def __init__(self, key: int,
                 ip: str,
                 cluster: 'SchedulerCluster',
                 news: News) -> None:
        """Initializes ReportedScheduler with given key, ip, and cluster,
           and calls update method on given News news.
        """
        self.key = key
        self.ip = ip
        self.cluster = cluster
        self.available = False
        self.leading = False
        self.leader: str = None
        self.update(news)

    def update(self, news) -> None:
        """Updates status based on given News news.

        The news is either a StatusUpdate or a string; if it is a string,
        then it is the public IP address of a scheduler reported as leader.
        """
        if news == StatusUpdate.AVAILABLE:
            self.available = True
        if news == StatusUpdate.UNAVAILABLE:
            self.available = False
            self.leading = False
            self.leader = None
        if news == StatusUpdate.LEADER:
            self.leading = True
        if isinstance(news, str):  # in this case the news is the leader's IP
            self.leader = news

    def report(self) -> str:
        """Returns a string summarizing the state of the ReportedScheduler."""
        head = f"Scheduler {self.key} ({self.ip}) is "
        if self.leading:
            tail = "leading."
            style = "\033[35;1;48m"  # bold purple with black background
        elif self.available:
            tail = "available"
            if self.leader:
                leader_key = self.cluster.dict[self.leader].key
                tail += " and following "
                tail += "\033[35;1;48m" + f"Scheduler {leader_key}."  # purple
            else:
                tail += "."
            style = "\033[32;1;48m"  # bold green with black background
        else:
            tail = "unavailable."
            style = "\033[31;1;48m"  # bold red with black background
        return style + head + tail + "\033[0m"  # revert to default style

    def update_key(self, key: int) -> None:
        """Replaces current key with given value."""
        self.key = key


class SchedulerCluster:
    """Abstraction of the cluster of schedulers as reported to the interface.

    Attributes:
        dict: A dictionary with keys the server public IP addresses (as strs)
              known to the interface and values the corresponding
              ReportedSchedulers.
        list: A list whose entries are the ReportedSchedulers in dict, in the
              order they are reported to the interface (with deletions
              supported).
    """

    def __init__(self) -> None:
        """Initializes SchedulerCluster with dict and list both empty."""
        self.dict: Dict[str, ReportedScheduler] = dict()
        self.list: List[ReportedScheduler] = []

    def consume(self, message: Message) -> None:
        """Updates SchedulerCluster in response to given Message.

        Extracts News from given Message and directs each such piece of News
        to the relevant Scheduler, adding the Scheduler to SchedulerCluster if
        not already present.
        """
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
        """Prints to screen a report on every Scheduler in SchedulerCluster."""
        system('clear')
        for scheduler in self.list:
            print(scheduler.report())

    def is_valid_key(self, wannakey: Any) -> bool:
        """Checks whether given input is a valid key for some scheduler.

        Here a key is a base-1 index for the list attribute.
        """
        try:
            integrated = int(wannakey)
            return 0 < integrated <= len(self.list)
        except BaseException:
            return False

    def key_to_ip(self, str_key: str) -> str:
        """Returns the public IP address of scheduler with given key.

           Here key has the same meaning as in the def of is_valid_key above.
        """
        return self.list[int(str_key) - 1].ip

    def remove(self, str_key: str) -> None:
        """Removes scheduler with given key SchedulerCluster.

        Appropriately updates dict and list attributes.
        """
        del self.dict[self.key_to_ip(str_key)]
        del self.list[int(str_key) - 1]
        self.update_keys()

    def update_keys(self) -> None:
        """Enforces definition of key.

        Specifically the key attribute of each scheduler in SchedulerCluster is
        updated to agree with the base-1 index of that scheduler in the list
        attribute of SchedulerCluster.
        """
        for index, scheduler in enumerate(self.list):
            scheduler.update_key(index + 1)


class CommandPrompt():
    """Prompt to listen for commands and execute them on given SchedulerCluster.

    The supported commands are described in the module docstring above.
    Attributes:
        schedulers: A SchedulerCluster
        listening: A boolean indicating whether or not the prompt is listening.
        ssh_key: A string representation of the path to an SSH key by which to
                 access all schedulers.
        db: A Database (class defined in hfshared.py)
        db_cred: Credentials (class defined in hfshared.py) to access db
    """

    def __init__(self,
                 schedulers: SchedulerCluster,
                 ssh_key: str,
                 database: Database,
                 db_cred: Credentials) -> None:
        """Initializes CommandPrompt() with given SchedulerCluster, ssh key,
           Database, and Credentials; calls update function; and initiates
           input loop."""
        self.schedulers = schedulers
        self.listening = True
        self.ssh_key = ssh_key
        self.db = database
        self.db_cred = db_cred
        self.update()
        while self.listening:
            self.process(input())

    def update(self) -> None:
        """Gets and displays current info on all schedulers by querying db."""
        self.db.connect(self.db_cred)
        query = ("SELECT DISTINCT \n"
                 + "\t ip, birth \n"
                 + "FROM \n"
                 + "\t schedulers\n"
                 + "ORDER BY \n"
                 + "\t birth \n"
                 + "ASC")
        self.db.cur.execute(query)
        ips_by_rank = [record[0] for record in self.db.cur.fetchall()]
        self.schedulers.consume(Message(sender=ips_by_rank[0],
                                        subject=ips_by_rank[0],
                                        status=StatusUpdate.LEADER))
        for ip in ips_by_rank[1:]:
            self.schedulers.consume(Message(sender=ip,
                                            subject=ip,
                                            status=StatusUpdate.AVAILABLE))
        self.schedulers.report()

    def process(self, cmd: str) -> None:
        """Parses and responds to text input."""
        parsed = cmd.split()

        if cmd in {'exit', 'quit', 'quit()'}:
            print("Goodbye!")
            self.listening = False

        elif cmd == 'report':
            self.schedulers.report()

        elif cmd == 'update':
            self.update()

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

        else:
            print("...command not understood...")


class MessageConsumer:
    """Consumer to receive messages from given queue, feed them to given
       SchedulerCluster, and call for SchedulerCluster report.

    Attributes:
        cluster: A SchedulerCluster
    """

    def __init__(self,
                 q: QueueHost,
                 credentials: Credentials,
                 cluster: SchedulerCluster):
        """Initializes MessageConsumer with given cluster; uses given
        Credentials (class defined in hfshared.py) to establish channel with
        given QueueHost (class defined in hfshared.py) and sets message
        consumption callback function to be MessageConsumer class function
        callback."""
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
        """Directs message body to SchedulerCluster cluster and reports."""
        self.cluster.consume(pickle.loads(body))
        self.cluster.report()


def main() -> None:
    """Starts a MessageConsumer and a CommandPrompt."""
    config = configparser.ConfigParser(inline_comment_prefixes='#')
    config.read('interface.ini')
    q = config['Q']
    db = config['DB']
    ssh_key = config['SSH']['ssh_key']

    q_cred = Credentials(user=q['q_user'], password=q['q_pwd'])
    qvh = QueueHost(host_ip=q['q_public_ip'], vhost=q['q_vhost'])

    database = Database(host_ip=db['db_public_ip'], name=db['database'])
    db_cred = Credentials(user=db['db_user'], password=db['db_pwd'])

    schedulers = SchedulerCluster()

    MessageConsumer(qvh, q_cred, schedulers)

    CommandPrompt(schedulers, ssh_key, database, db_cred)


if __name__ == '__main__':
    main()
