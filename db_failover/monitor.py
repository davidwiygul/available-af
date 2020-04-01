# monitor.py

import subprocess
import time

from psycopg2 import sql
import psycopg2

from hfshared import Credentials, Database


cred = Credentials('DB_USER', 'DB_PWD')
partner_db = Database('PARTNER_IP', 'DB_NAME')
local_db = Database('localhost', 'DB_NAME')

running = True

while running:
    try:
        partner_db.connect(cred)
        select = ("SELECT * FROM db_failover_flag")
        partner_db.cur.execute(sql.SQL(select))
        running = not partner_db.cur.fetchone()[0]
        partner_db.disconnect()
    except psycopg2.OperationalError:
        subprocess.run(['/bin/bash', '/home/ubuntu/db_failover/failover'])
        local_db.connect(cred)
        update = ("UPDATE db_failover_flag SET flag = TRUE")
        local_db.cur.execute(sql.SQL(update))
        local_db.conn.commit()
        local_db.disconnect()
        running = False
    time.sleep(15)
