#!/usr/bin/env python
import time
import subprocess
from pprint import pprint
import psutil
import sqlite3
from filelock import FileLock, Timeout

DELAY=1 # seconds

def prepare_db(cur):
    cur.execute("""CREATE TABLE IF NOT EXISTS gpu
                    (timestamp INT, gpuid INT,
                    power_use INT, power_max INT,
                    mem_alloc_mb INT, mem_total_mb INT,
                    util INT)""")
    cur.execute("""CREATE TABLE IF NOT EXISTS proc
                    (timestamp INT, gpuid INT, pid INT,
                    mem_alloc_mb INT, user CHAR)""")

def store_proc(proc: list, timestamp: int, cur: any):
    cur.executemany(f"""INSERT INTO proc VALUES({timestamp},
        :gpuid, :pid, :mem_alloc_mb, :user)""", proc)

def store_gpu(gpu: list, timestamp: int, cur: any):
    cur.executemany(f"""INSERT INTO gpu VALUES({timestamp},
        :gpuid, :power_use, :power_max,
        :mem_alloc_mb, :mem_total_mb, :util)""", gpu)

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
            
            owner = psutil.Process(int(proc[3])).username()
            item = {
                'gpuid': int(proc[0]),
                'pid': int(proc[3]),
                'user': owner,
                'name': proc[5],
                'mem_alloc_mb': int(proc[6].replace('MiB', '')),
            }
            processes.append(item)

        gpu_idx = 0
        for line in dashboard:
            if "MiB" not in line:
                    continue

            power_info = line.split("|")[1]
            power_capacity = int(power_info.split("/")[-1].replace("W", ""))
            power_usage = int((power_info.split("/")[-2]).strip().split(" ")[-1].replace("W", ""))

            memory_info = line.split("|")[2].replace("MiB","").split("/")
            utilization_info = int(line.split("|")[3].split("%")[0])

            allocated = int(memory_info[0])
            total_memory = int(memory_info[1])
            available_memory = total_memory - allocated

            item = {
                'gpuid': gpu_idx,
                'power_use': power_usage,
                'power_max': power_capacity,
                'mem_use_perc': round(100*int(allocated)/int(total_memory), 1),
                'mem_alloc_mb': allocated,
                'mem_avail_mb': available_memory,
                'mem_total_mb': total_memory,
                'util': utilization_info
            }
            gpus.append(item)
            gpu_idx = gpu_idx + 1
    except Exception as err:
        print("there are no GPUs on your system (", str(err), ")")

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
    cur = db.cursor()
    prepare_db(cur)

    while True:
        try:
            start = time.time()
            proc, gpu = gpustats()

            store_proc(proc, int(start), cur)
            store_gpu(gpu, int(start), cur)
            db.commit()
            db.execute("BEGIN")

            #print("Request took %.03f sec" % (time.time() - start))
            #pprint(proc)
            #pprint(gpu)

        except Exception as e:
            print(e)
        time.sleep(DELAY)

if __name__ == '__main__':
    main()
