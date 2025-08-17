import threading
import subprocess
import sys
import os
import time

def run_collector():
    """啟動 collector.py"""
    python_exec = sys.executable  # 當前 python 解譯器
    collector_path = os.path.join(os.path.dirname(__file__), "collector.py")
    subprocess.Popen([python_exec, collector_path])
    print("[MAIN] Collector 啟動")

def run_writer():
    """啟動 writer.py"""
    python_exec = sys.executable
    writer_path = os.path.join(os.path.dirname(__file__), "writer.py")
    subprocess.Popen([python_exec, writer_path])
    print("[MAIN] Writer 啟動")

if __name__ == "__main__":
    print("=== 啟動主程式 (Collector + Writer) ===")
    # 分別啟動兩個子進程
    t1 = threading.Thread(target=run_collector)
    t2 = threading.Thread(target=run_writer)

    t1.start()
    t2.start()

    # 主執行緒等待（不退出）
    while True:
        time.sleep(10)
