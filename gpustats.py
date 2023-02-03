#!/usr/bin/env python
import time
import subprocess
from pprint import pprint
import psutil
import sqlite3
from filelock import FileLock, Timeout

DELAY=10 # seconds
DEBUG=False

def prepare_db(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS gpu
                    (timestamp INT, gpuid INT,
                    power_use INT, power_max INT,
                    mem_alloc INT, mem_total INT,
                    util INT, fan INT, temp INT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS proc
                    (timestamp INT, gpuid INT, pid INT,
                    mem_alloc INT, user CHAR)""")
def store_gpu(gpu: list, timestamp: int, cur: any):
    cur.executemany(f"""INSERT INTO gpu VALUES({timestamp},
        :gpuid, :power_use, :power_max,
        :mem_alloc, :mem_total, :util, :fan, :temp)""", gpu)

def store_proc(proc: list, timestamp: int, cur: any):
    cur.executemany(f"""INSERT INTO proc VALUES({timestamp},
        :gpuid, :pid, :mem_alloc, :user)""", proc)

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
            power_usage = int(power_info[3].replace("W", ""))
            power_max = int(power_info[5].replace("W", ""))

            memory_info = line.split("|")[2].replace("MiB","").split("/")
            util_info = int(line.split("|")[3].split("%")[0])
            mem_alloc = int(memory_info[0])
            mem_total = int(memory_info[1])

            item = {
                'gpuid': gpu_idx,
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

def main():
    try:
        fl = FileLock('.lock', timeout=1)
        fl.acquire()
    except Timeout:
        print(f"Lockfile found, {__file__} is already running.")
        return

    print(f"Starting {__file__}...")
    db = sqlite3.connect("gpustats.db")
    prepare_db(db)

    while True:
        try:
            start = time.time()
            proc, gpu = gpustats()

            store_proc(proc, int(start), db)
            store_gpu(gpu, int(start), db)
            db.commit()

            if DEBUG:
                print("Request took %.03f sec" % (time.time() - start))
                print("Processes:")
                pprint(proc)
                print("GPUs:")
                pprint(gpu)

        except Exception as e:
            print(e)
            if DEBUG:
                raise

        time.sleep(DELAY)

if __name__ == '__main__':
    main()
