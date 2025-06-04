import os
from datetime import datetime

class LogManager:
    def __init__(self, log_dir="log"):
        os.makedirs(log_dir, exist_ok=True)
        self.path = os.path.join(log_dir, datetime.now().strftime("%Y-%m-%d_%H-%M-%S.txt"))

    def write(self, speaker_line:str):
        with open(self.path,"a",encoding="utf-8") as f:
            f.write(speaker_line+"\n")