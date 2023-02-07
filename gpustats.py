#!/usr/bin/env python
import time
import psutil
import sqlite3
import argparse
import datetime
import subprocess
from pprint import pprint
from prettytable import PrettyTable
from pid.decorator import pidfile
from pid.base import PidFileAlreadyLockedError

DELAY=10 # seconds
WATCH_HISTORY=6 # How many entries show at once
DEBUG=False

def prepare_db(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS gpu
                    (timestamp INT, gpuid INT,
                    power_use INT, power_max INT,
                    mem_alloc INT, mem_total INT,
                    util INT, fan INT, temp INT, mode CHAR, interval INT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS proc
                    (timestamp INT, gpuid INT, pid INT,
                    mem_alloc INT, user CHAR, interval INT)""")
def store_gpu(gpu: list, timestamp: int, cur: any):
    cur.executemany(f"""INSERT INTO gpu VALUES({timestamp},
        :gpuid, :power_use, :power_max,
        :mem_alloc, :mem_total, :util, :fan, :temp, :mode, {DELAY})""", gpu)

def store_proc(proc: list, timestamp: int, cur: any):
    cur.executemany(f"""INSERT INTO proc VALUES({timestamp},
        :gpuid, :pid, :mem_alloc, :user, {DELAY})""", proc)

def gpustats():
    """Original idea https://github.com/serengil/gpuutils"""
    gpus = []
    processes = []
    try:
        result = subprocess.check_output(['nvidia-smi']) #result is bytes
        dashboard = result.decode("utf-8").split("=|")

        dashboard_proc = dashboard[2].split("\n")
        dashboard = dashboard[1].split("\n")

        for line in dashboard_proc:
            if "|" not in line:
                continue
            # GPUID GID CID PID Type Process MemUtil
            proc = [ c for c in line.split(' ') if c != '' ][1:-1]
            
            # "No running process found" in locale-independent way
            if not proc[0].isnumeric():
                continue

            owner = psutil.Process(int(proc[3])).username()
            item = {
                'gpuid': int(proc[0]),
                'pid': int(proc[3]),
                'user': owner,
                'name': proc[5],
                'mem_alloc': int(proc[6].replace('MiB', '')),
            }
            processes.append(item)

        gpu_idx = 0
        for line in dashboard:
            if "MiB" not in line:
                    continue

            power_info = [ c for c in line.split("|")[1].split(' ') if c != '' ]
            fan_info = int(power_info[0].replace('%', ''))
            temp_info = int(power_info[1].replace('C', ''))
            mode_info = power_info[2]
            power_usage = int(power_info[3].replace("W", ""))
            power_max = int(power_info[5].replace("W", ""))

            memory_info = line.split("|")[2].replace("MiB","").split("/")
            util_info = int(line.split("|")[3].split("%")[0])
            mem_alloc = int(memory_info[0])
            mem_total = int(memory_info[1])

            item = {
                'gpuid': gpu_idx,
                'mode': mode_info,
                'power_use': power_usage,
                'power_max': power_max,
                'mem_use_perc': round(100*mem_alloc/mem_total),
                'mem_alloc': mem_alloc,
                'mem_total': mem_total,
                'util': util_info,
                'fan': fan_info,
                'temp': temp_info,
            }

            gpus.append(item)
            gpu_idx = gpu_idx + 1
    except Exception as err:
        print("there are no GPUs on your system (", str(err), ")")
        if DEBUG:
            raise

    return (processes, gpus)

def watch_stats(args):
    def format_timestamp(f, v): return str(datetime.datetime.fromtimestamp(v))
    def format_temp(f, v): return f"{v} ˚C"
    def format_perc(f, v): return f"{v} %"
    def format_mb(f, v): return f"{v} MB"
    def format_watt(f, v): return f"{v} W"

    def render_table(db, pt, table_name, limit):
        db = db.execute(f"""
                SELECT * FROM {table_name} WHERE timestamp IN (
                    SELECT timestamp FROM {table_name} ORDER BY rowid DESC LIMIT {WATCH_HISTORY}
                )
        """)
        pt.clear_rows()
        pt.field_names = [tup[0] for tup in db.description]
        pt.add_rows(db.fetchall())
        print(pt)

    def get_last_timestamp(db):
        return db.execute("SELECT timestamp FROM gpu ORDER BY rowid DESC LIMIT 1").fetchone()[0]

    db = sqlite3.connect("gpustats.db", isolation_level=None)
    table_gpu = PrettyTable()
    table_gpu.align = "r"
    table_gpu.custom_format = {
        'timestamp': format_timestamp,
        'temp': format_temp,
        'util': format_perc,
        'fan': format_perc,
        'power_use': format_watt,
        'power_max': format_watt,
        'mem_alloc': format_mb,
        'mem_total': format_mb,
    }

    table_proc = PrettyTable()
    table_proc.align = "r"
    table_proc.custom_format = {
        'timestamp': format_timestamp,
        'mem_alloc': format_mb,
    }

    try:
        while True:
            # Resets terminal
            # https://www.unix.com/os-x-apple-/279401-means-clearing-scroll-buffer-osx-terminal.html
            print("\033c\033[3J\033[2J\033[0m\033[H")

            # Sync with data gathering script
            # 0.5 sec extra because of timestamp precision on seconds
            last_timestamp = get_last_timestamp(db)
            delay = DELAY - (time.time() - last_timestamp) + 0.5
            delay = max(1, delay)
            delay = min(DELAY, delay)
            print(f"Latency: %.03f s, Sleep: %.03f s" % \
                    (time.time() - last_timestamp, delay))

            render_table(db, table_gpu, "gpu", 1)
            render_table(db, table_proc, "proc", 1)

            time.sleep(delay)
    finally:
        db.close()

@pidfile('gpustats.pid')
def gather_stats(args):
    print(f"Starting {__file__} at {datetime.datetime.now()}...")

    db = sqlite3.connect("gpustats.db", isolation_level=None)
    prepare_db(db)

    try:
        while True:
            try:
                proc, gpu = gpustats()
                # int() floors the timestamp and breaks latency calculator in watcher
                timestamp = round(time.time())

                store_proc(proc, timestamp, db)
                store_gpu(gpu, timestamp, db)
                db.commit()

                if DEBUG:
                    print("Processes:")
                    pprint(proc)
                    print("GPUs:")
                    pprint(gpu)

            except Exception as e:
                print(e)
                if DEBUG:
                    raise

            time.sleep(DELAY)

    finally:
        db.close()

def main():
    parser = argparse.ArgumentParser()
    cmds = parser.add_mutually_exclusive_group()
    cmds.add_argument("-g", "--gather", action="store_true",
            help="Keep gathering stats and store them to sqlite")
    cmds.add_argument("-w", "--watch", action="store_true", default=True,
            help="Watch latest values.")

    args = parser.parse_args()

    if args.gather:
        gather_stats(args)
    elif args.watch:
        watch_stats(args)

if __name__ == '__main__':
    try:
        main()
    except PidFileAlreadyLockedError:
        print(f"Lockfile found, {__file__} is already running.")
 
