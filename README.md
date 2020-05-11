# Heirflow

## Overview
[Apache Airflow](https://airflow.apache.org/) is an extremely popular
and effective tool for workflow orchestration.
Airflow consists of the following components.
The workflows themselves (also called DAGs, for directed acyclic graphs)
are expressed as pure Python code.
The state of all DAGs and their constituent tasks
(for example whether they've run successfully, are ready to be run, and so on)
is stored in a metadata database.
A process called the scheduler inspects the DAG code
and database and decides which tasks are ready to be executed.
Each such task is then sent to a queue,
from which it is picked up and executed by a worker.

In the simplest Airflow setup all these pieces reside
on a single machine.
While this configuration suffices for many use cases,
there are of course a couple reasons why one might wish to scale out.
First, having multiple worker nodes in place allows for
parallel execution of independent tasks.
Second (and perhaps the more generally compelling motivation),
redundancy in each component improves the availability of the system,
meaning less downtime and fewer interrupted DAGs.

Heirflow is an Airflow deployment delivering redundancy in each component.
The metadata store consists of a two-node synchronized master-standby
[Postgres](http://www.postgresql.org) cluster,
equipped with a floating IP and custom automatic failover.
The DAGs sit on an
[Amazon Elastic File System](https://aws.amazon.com/efs/)
drive,
with high availability guaranteed by AWS.
The worker cluster
(having four nodes in the example below,
 though the number is both arbitrary and dynamic)
is marshalled by Airflow's Celery executor,
using the well-known
[Celery](http://www.celeryproject.org) task queue,
which in our Heirflow architecture is itself built
atop [RabbitMQ](http://www.rabbitmq.com) message broker.
Our RabbitMQ queues are mirrored over a multi-node cluster
(of three servers in the below example),
with built-in promotion of a new master as needed.
(The included demo DAG, running simple linear regression with feature selection,
 additionally takes advantage of a
 [Riak](http://www.riak.com) in-memory key-value store
 distributed over the worker cluster.)
		  
Achieving scheduler redundancy is a slightly more delicate challenge,
since (at least at time of writing) simply running multiple schedulers
simultaneously introduces the danger of scheduling a single task more than once,
which, at worst (if the tasks are not idempotent) can lead to incorrect
results and at best wastes resources. To address this difficulty
Heirflow takes advantage of the metadata store already present
in every Airflow deployment. It introduces a new table to serve
as a single source of truth for all schedulers in the mix.
Each scheduler is itself wrapped in a Python script which periodically
checks in with the database table to report its status and review
that of its neighbors. At a given time only one scheduler is actively
scheduling tasks; should it go down, the other schedulers learn of its
demise through the database, and the "oldest" (that is first to register
with the database) available scheduler is universally recognized as the
"heir" and will seamlessly take over scheduling.
In this scheme, if desired, schedulers can be added or removed
on the fly, without requiring any configuration
or interrupting workflows.

Of course many teams have devised their own highly available
Airflow implementations.
For interesting alternative approaches to the scheduler problem
in particular
check out
[this repository](https://github.com/dragonfeifei/the-walking-dead)
as well as
[this solution](https://github.com/teamclairvoyant/airflow-scheduler-failover-controller)
from [Clairvoyant](http://www.clairvoyantsoft.com).


## Installation

### Preliminaries

Heirflow is designed to run in AWS on EC2 instances running Ubuntu 18.04,
though it should be straightforward to port it to other operating systems
and cloud platforms. In testing all instances were m4large.

The example setup presented below will use 12 EC2 instances,
but it should be clear how to modify the instructions
to use either more or fewer
instances (and you can certainly install multiple components on a single
	   shared instance without necessarily introducing a single point
	   of failure).

The various services we'll install must be able to communicate with one another,
so for simplicity you could attach a single
[security group](https://docs.aws.amazon.com/vpc/latest/userguide/VPC_SecurityGroups.html)
to all the
instances allowing all traffic from other instances in the same group.
This security group should also permit SSH access from the machine
that will run the Heirflow installation scripts.
To use the Airflow web UI from your local machine
you'll also want to allow http access on port 8080.
 To use the Heirflow multischeduler interface locally
 you should further allow TCP traffic on ports 5432
(default for Postgres) and 5672 (default for RabbitMQ).
To use the Celery Flower web interface
you'll need to allow traffic on port 5555.
Of course any of these default ports can be changed,
and more restrictive security settings can be enforced
if desired.

You will need an [EFS](https://aws.amazon.com/efs/)
accessible by all instances.

Unless you wish to run a single-node database,
the instance running the standby node
should be bestowed an
[IAM role](https://docs.aws.amazon.com/IAM/latest/UserGuide/id_roles.html)
allowing it to assign and unassign
private IP addresses to itself and to the database master node.

The Heirflow installation scripts should be run from a Linux terminal
with Bash and SSH installed. All instances should be launched under
a common SSH key pair, with the private key accessible on the machine
running the Heirflow installation scripts.

### Instructions

We'll now launch an Heirflow deployment consisting of
a two-node Postgres cluster,
a three-node RabbitMQ cluster,
a two-node scheduler cluster,
a four-node worker cluster,
and a single Airflow UI webserver.
It shouldn't be hard to adapt these instructions to play with these
numbers, with the only firm design restriction being that,
at present, the database cluster must consist of either one or two nodes.

The setup procedure is significantly streamlined by Bash scripts
in the config directory.
A future version may take advantage of more sophisticated
tools for provisioning and configuration
(and possibly incorporate steps that must now be carried out separately
 via the AWS Console or CLI),
but the existing scripts have the advantage of easily providing
detailed documentation of the setup procedure.
Of course you should review these scripts before running them on your system
and your instances!

#### Initial settings in `provision.config`

To start we need to set some fields in the `config/provision.config` file.

- `AWS_SSH_KEY` should point to the private SSH key to access all EC2 instances.
- `EFS_IP` should point to your EFS drive.
- `EFS_PATH` will be the EFS mount location on each instance.
           It's up to you; I like `/mnt/efs/`.
- `ERLANG_COOKIE_PATH` should point to the directory on the first queue node
                     where RabbitMQ stores the `.erlang.cookie` file.
                     At time of writing, for Ubuntu installations,
                     it's `/var/lib/rabbitmq/.erlang.cookie`.
- `DATABASE` is whatever you'd like to name the database that will store
             Airflow metadata, as well as tables utilized by the
             Heirflow schedulers and database failover monitor.
- `DB_USER` names a user permitted to access `$DATABASE`, and
- `DB_PWD` is their password.
- `REP_USER` names a user with replication permission having
- `REP_PWD` as password.
- `DB_ARCHIVE` is the path to the database archive directory,
               which should be accessible by the standby node:
               for example `$EFS_PATH/pg_archive`.
- `DB_STANDBY_NAME` is a name, such as `standby_node`, for the database
                    standby (for purposes of Postgres configuration solely).
- `QUEUE_HOST` is whatever you'd like to call the RabbitMQ virtual host
               for the Airflow task queue.
- `QUEUE_USER` names a user permitted to access `$QUEUE_HOST`, and
- `QUEUE_PWD` is their password.
- `NEWS_QUEUE_VHOST` names the RabbitMQ virtual host for the message queue
                     updating the (optionally used) Heirflow interface
                     on the status of each scheduler.
- `NEWS_QUEUE_USER` is a user entitled to access `$NEWS_QUEUE_VHOST` with
- `NEWS_QUEUE_PWD` as password.
- `NETPLAN_YAML` is the name of the netplan yaml template file in the config
                 directory, by default `60-secondary.yaml`. If this field
                 is altered, that template file must also be renamed
                 (and vice-versa) to match.

The remaining fields will be set automatically
by the installation scripts we will run.

#### Database cluster
(For the instructions in this and all subsequent subsections
bear in mind the assumptions made in the Preliminaries subsection.)

1. Launch an EC2 instance.
2. In the config directory run `./provision_db_first DB1_PUBLIC_IP`,
   where `DB1_PUBLIC_IP` is the public IP address of the instance
   in Step 1.
3. Launch another EC2 instance, but attach to this one a role
   that permits it to assign and unassign private IP addresses
   (for failover purposes) to itself and to the instance in Step 1.
4. Run `./provision_db_later DB2_PUBLIC_IP`,
   where `DB2_PUBLIC_IP` is the public IP address of the instance
   in Step 3.

Note that if DB1's public IP address has changed before Step 4,
then the `DB_PUBLIC` field in `provision.config` must be updated first.

#### Queue cluster
(These steps are independent of Steps 1-4, so could be performed
 at the same time or earlier.)

5. Launch an EC2 instance.
6. Run `./provision_q_first Q1_PUBLIC_IP`,
   where `Q1_PUBLIC_IP` is the public IP address of the instance in Step 5.
7. Launch another two EC2 instances.
8. Run `./provision_q_later Q2_PUBLIC_IP` for either one of the instances
   in Step 7.
9. Run `./provision_q_later Q3_PUBLIC_IP` for the other instance in Step 7.

#### Scheduler cluster
(These steps cannot be completed until `DB_IP` and `MQ_IP` have
 been set in `provision.config`, as they are by the preceding steps.)

10. Launch two EC2 instances.
11. Run `./provision_multischeduler  S_PUBLIC_IP`
    for the public IP `S_PUBLIC_IP` of each instance
    in Step 10. (These can safely run simultaneously.)

#### Worker cluster
(These steps cannot be completed until `DB_IP` and `MQ_IP` have
 been set in `provision.config`, as they are by Steps 1-9,
 but they may be run before or at the same time as Steps 10-11.)

12. Launch an EC2 instance.
13. Run `./provision_worker_first W1_PUBLIC_IP` for the instance in 12.
14. Launch three more instances.
15. Run `./provision_worker_first W_PUBLIC_IP` successively 
    for each of the three instances in Step 12.

(These commands should be run one after the other; starting any two
 simultaneously could interfere with proper formation of the Riak cluster,
 which is not essential for Heirflow's core functionality,
 but is used in the included demo DAG.)

#### Webserver
(These steps can be completed at any point after Steps 1-9.)

16. Launch an EC2 instance.
17. Run `./provision_webserver WEB_PUBLIC_IP` for the instance in 16.

(Webserver failure will not disrupt DAG execution,
 so we're foregoing a backup in this example,
 but to make this Airflow UI highly available too
 one can simply provision a second webserver
 and optionally place a load balancer in front of both.)
                    

#### Demo DAG
(These steps can be completed at any time.)

18. Launch an EC2 instance.
19. Run `./demo ANY_PUBLIC_IP` for any instance above.


To see Heirflow in action you can just point your browser to
`WEB_PUBLIC_IP:8080`
(`WEB_PUBLIC_IP`, again, being the current public IP address
 of the instance running the Airflow webserver)
and unpause the `model_select` DAG.
You can play around with stopping or terminating various instances while
the DAGs run.
You can also observe scheduler succession with the scheduler interface
`heirflow/interface.py`, whose source code contains instructions for use.
