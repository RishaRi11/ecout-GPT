### gpt_manager.py

import os
import threading
from openai import OpenAI

class GPTManager:
    def __init__(self, transcriber):
        self.transcriber = transcriber
        self.answer_changed = threading.Event()
        self.latest_answer = ""
        self.auto_var = None  # будет CTk BooleanVar
        self.last_prompt = None
        self.client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

    # связываем переключатель
    def set_auto_var(self, var):
        self.auto_var = var
        self.transcriber.set_gpt_callback(self.auto_trigger)

    # вызывается transcriber'ом при автоусловии
    def auto_trigger(self, prompt_lines):
        if self.auto_var and self.auto_var.get():
            self._send_async(prompt_lines)

    def manual_send(self):
        prompt = self.transcriber.get_current_prompt()
        if prompt:
            self._send_async(prompt)

    def repeat_last(self):
        if self.last_prompt:
            self._send_async(self.last_prompt)

    # ------------- внутреннее -------------
    def _send_async(self, prompt_lines):
        self.last_prompt = prompt_lines
        threading.Thread(target=self._send_sync,args=(prompt_lines,),daemon=True).start()

    def _send_sync(self, prompt_lines):
        prompt = "\n".join(prompt_lines)
        try:
            resp = self.client.chat.completions.create(
                model="gpt-4o-mini",
                messages=[{"role":"user","content":prompt}],
                temperature=0.3
            )
            self.latest_answer = resp.choices[0].message.content.strip()
        except Exception as e:
            self.latest_answer = f"[GPT error] {e}"
        self.answer_changed.set()
