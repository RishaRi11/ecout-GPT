### main.py
from dotenv import load_dotenv
load_dotenv() 
import threading
import queue
import time
import asyncio
import subprocess
import os
from datetime import datetime
import customtkinter as ctk
import re
from PIL import Image
import tkinter as tk   

import AudioRecorder
from AudioTranscriber import AudioTranscriber
from vertical_range_slider import VerticalRangeSlider
from gpt_manager import GPTManager
from log_manager import LogManager
import TranscriberModels
from config_manager import load_config, save_config 


# ---------- CONFIG DEFAULTS ----------
CONTEXT_DEPTH_DEFAULT = 3
BTN_ICON_FONT = ("Arial", 18)

load_dotenv()  # подгружаем OPENAI_API_KEY из .env

FONT_CFG = {
    "speaker": {"family": "Arial",  "size": 16, "bold": False, "italic": False, "color": "#33ffaa"},
    "user":    {"family": "Arial",  "size": 16, "bold": False, "italic": False, "color": "#ffaa33"},
    "gpt":     {"family": "Courier","size": 16, "bold": False, "italic": True,  "color": "#c4ffee"}
}
# ---------- UI helpers ----------

# В файле main.py, примерно строка 34
def write_transcript(tb: ctk.CTkTextbox, items, start: int, end: int):
    # для совместимости со старыми/новыми версиями customtkinter
    inner = getattr(tb, "textbox", None) or tb._textbox        

    inner.configure(state="normal")
    inner.delete("1.0", "end")

    # --- задаём (или пере-задаём) теги под фиксированные стили
    def _tag_style(cfg):
        styles = []
        if cfg["bold"]:
            styles.append("bold")
        if cfg["italic"]:
            styles.append("italic")
        return (cfg["family"], cfg["size"]) if not styles else (cfg["family"], cfg["size"], " ".join(styles))

    inner.tag_configure("speaker_tag", font=_tag_style(FONT_CFG["speaker"]),
                        foreground=FONT_CFG["speaker"]["color"])
    inner.tag_configure("user_tag",    font=_tag_style(FONT_CFG["user"]),
                        foreground=FONT_CFG["user"]["color"])
        # Фон для строк, попадающих в контекст
    inner.tag_configure("ctx_tag", background="#444444")

    spk_index = 0
    for item in items:
        text, _, role = item[:3]
        tag = "speaker_tag" if role == "Speaker" else "user_tag"
        extra = ()
        if role == "Speaker":
            if start <= spk_index <= end:
                extra = ("ctx_tag",)
            spk_index += 1
        inner.insert("end", text, (tag, *extra))

    inner.configure(state="disabled")

def write_in_textbox(tb: ctk.CTkTextbox, text: str):
    tb.configure(state="normal")
    tb.delete("0.0", "end")
    tb.insert("0.0", text)
    tb.configure(state="disabled")


# ---------- UI creation ----------

def create_ui(root, transcriber, gpt_mgr, mic_rec, spk_rec, config):
    ctk.set_appearance_mode("dark")
    ctk.set_default_color_theme("dark-blue")

    root.title("Ecoute + GPT")
    root.geometry("1200x650")
    root.grid_columnconfigure(0, weight=1)
    root.grid_columnconfigure(1, weight=0)
    root.grid_columnconfigure(2, weight=1)
    root.grid_rowconfigure(0, weight=1)

    # --- Left: transcript ---
    transcript_tb = ctk.CTkTextbox(root, font=("Arial", 16), wrap="word", text_color="#FFFCF2")
    transcript_tb.grid(row=0, column=0, sticky="nsew", padx=(10, 5), pady=10)

    # --- Right: GPT answer ---
    gpt_tb = ctk.CTkTextbox(root, font=("Arial", 16, "italic"), wrap="word", text_color="#C4FFEE")
    gpt_tb.grid(row=0, column=2, sticky="nsew", padx=(5, 10), pady=10)

    # --- Vertical range slider for context selection ---
    range_slider = VerticalRangeSlider(
        root,
        from_=0,
        to=1,
        number_of_steps=1,
        command=lambda v: update_context_range(int(v[0]), int(v[1]))
    )
    range_slider.grid(row=0, column=1, sticky="ns", pady=10)
    range_slider.set(transcriber.context_start, transcriber.context_end)

    # --- делаем оба textbox-а доступными для выделения/копирования ---
    for tb in (transcript_tb, gpt_tb):
        tb.bind("<Key>", lambda e: "break")   # блокируем ввод, но оставляем Ctrl-C

    # GPT textbox шрифт
    gpt_tb.configure(
            font=(FONT_CFG["gpt"]["family"],
                FONT_CFG["gpt"]["size"],
                "italic" if FONT_CFG["gpt"]["italic"] else ""),
            text_color=FONT_CFG["gpt"]["color"]
            )
    # --- Bottom panel ---
    bottom = ctk.CTkFrame(root)
    bottom.grid(row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=(0, 10))
    bottom.grid_columnconfigure(0, weight=1)    # левые кнопки тянутся влево
    bottom.grid_columnconfigure(1, weight=1)    # правые тянутся вправо

    # ----- ЛЕВАЯ группа (Mute + Language) ------------------
    left_box = ctk.CTkFrame(bottom, fg_color="transparent")
    left_box.grid(row=0, column=0, sticky="w")

    # --- динамик с перечёркнутой линией -------------------------------
    # Файл:   assets/muted.png   (18×18 px, белый/прозрачный)
    try:
        icon_muted = ctk.CTkImage(
            light_image=Image.open(os.path.join("assets", "muted.png")),
            size=(18, 18)
        )
    except Exception as e:
        print("Icon load error:", e)
        icon_muted = None  # на случай отсутствия картинки
        
    # Размещаем слева от переключателей
    ctk.CTkLabel(left_box, image=icon_muted, text="").pack(side="left", padx=(0, 2))

    # --- Mic -----------------------------------------------------------------
    mute_mic_var = ctk.BooleanVar(value=True)
    def _toggle_mic():
        mic_rec.set_muted(not mute_mic_var.get())
    ctk.CTkSwitch(left_box,
                  text=" Mic",
                  variable=mute_mic_var,
                  command=_toggle_mic
                 ).pack(side="left", padx=(4,0))

    # вставляем ВТОРУЮ иконку 🔇 перед Speaker-switch
    ctk.CTkLabel(left_box, image=icon_muted, text="").pack(side="left", padx=(12,2))

    # --- Speaker -------------------------------------------------------------
    mute_spk_var = ctk.BooleanVar(value=True)
    def _toggle_spk():
        spk_rec.set_muted(not mute_spk_var.get())

    ctk.CTkSwitch(left_box,
                  text=" Speaker",
                  variable=mute_spk_var,
                  command=_toggle_spk
                 ).pack(side="left", padx=(4,0))

    ctk.CTkButton(left_box, text="🌐", width=30, font=("Arial", 18),
                  command=lambda: open_language_settings(root, transcriber, config)
                  ).pack(side="left", padx=4)
    

    # ----- ПРАВАЯ группа (GPT-управление) ------------------
    right_box = ctk.CTkFrame(bottom, fg_color="transparent")
    right_box.grid(row=0, column=1, sticky="e")

    auto_var = ctk.BooleanVar(value=True)
    ctk.CTkSwitch(right_box, text="GPT ON/OFF",
                  variable=auto_var
                 ).pack(side="left", padx=10)
    gpt_mgr.set_auto_var(auto_var)

    ctk.CTkButton(right_box, text="Отправить пул",
                  command=gpt_mgr.manual_send
                 ).pack(side="left", padx=10)

    ctk.CTkButton(right_box, text="Повторить ответ",
                  command=gpt_mgr.repeat_last
                 ).pack(side="left", padx=10)
    
    # ---------------------------------------------
    # БЛОК: Управление объёмом контекста и его превью
    # ---------------------------------------------
    # Frame для ползунка и окна превью контекста
    context_frame = ctk.CTkFrame(bottom, fg_color="transparent")
    context_frame.grid(row=1, column=0, columnspan=3, sticky="ew", padx=10, pady=(5, 10))
    context_frame.grid_columnconfigure(0, weight=1)

    ctk.CTkLabel(context_frame, text="Контекст:").grid(row=0, column=0, sticky="w", padx=(0,5), pady=(0,3))

    # Окно превью того, что будет отправляться в GPT
    prompt_preview = ctk.CTkTextbox(
        context_frame,
        font=(FONT_CFG["gpt"]["family"], FONT_CFG["gpt"]["size"], "italic" if FONT_CFG["gpt"]["italic"] else ""),
        height=100,
        wrap="word",
        text_color=FONT_CFG["gpt"]["color"]
    )
    prompt_preview.grid(row=1, column=0, columnspan=2, sticky="nsew", padx=(0, 5), pady=(5, 0))
    prompt_preview.configure(state="disabled")

    # Функция-обработчик изменения ползунка
    def update_context_range(start: int, end: int):
        if end < start:
            start, end = end, start
        spk_total = len(transcriber.transcript_data["Speaker"])
        max_val = max(spk_total - 1, 0)
        start = max(0, min(start, max_val))
        end = max(0, min(end, max_val))
        if end < start:
            end = start
        transcriber.context_start = start
        transcriber.context_end = end


        current_list = transcriber.get_current_prompt()
        preview_text = "".join(current_list)

        write_transcript(transcript_tb, transcriber.get_transcript(), start, end)

        prompt_preview.configure(state="normal")
        prompt_preview.delete("0.0", "end")
        prompt_preview.insert("0.0", preview_text)
        prompt_preview.configure(state="disabled")

    def update_slider_limits():
        spk_total = len(transcriber.transcript_data["Speaker"])
        max_val = max(spk_total - 1, 0)
        slider_max = max(1, max_val)
        if hasattr(range_slider, "configure"):
            range_slider.configure(to=slider_max, number_of_steps=slider_max)
        if transcriber.context_start > max_val:
            transcriber.context_start = max_val
        if transcriber.context_end > max_val:
            transcriber.context_end = max_val
        if transcriber.context_end < transcriber.context_start:
            transcriber.context_start = transcriber.context_end
        if hasattr(range_slider, "set"):
            range_slider.set(transcriber.context_start, transcriber.context_end)

    # Инициализируем превью при старте
    update_context_range(transcriber.context_start, transcriber.context_end)


    def _poll_events():
        # новый текст от транскрипции
        if transcriber.transcript_changed_event.is_set():
            update_slider_limits()
            update_context_range(transcriber.context_start, transcriber.context_end)
            transcriber.transcript_changed_event.clear()

        # новый ответ GPT
        if gpt_mgr.answer_changed.is_set():
            write_in_textbox(gpt_tb, gpt_mgr.latest_answer)
            gpt_mgr.answer_changed.clear()

        root.after(200, _poll_events)    # опрашиваем ~5 раз/сек

    _poll_events()   # -> первый запуск
 

def open_language_settings(parent, transcriber, config):
    if getattr(parent, "_lang_win", None) and parent._lang_win.winfo_exists():
        parent._lang_win.focus_force()
        return

    win = ctk.CTkToplevel(parent)
    win.title("Выбор языка")
    win.resizable(False, False)
    win.transient(parent)
    win.grab_set()
    parent._lang_win = win

    options = {
        "Автоопределение": None,
        "Русский (ru)": "ru",
        "English (en)": "en",
        "Deutsch (de)": "de",
        "Français (fr)": "fr",
        "Español (es)": "es",
        "中文 (zh)": "zh",
        "日本語 (ja)": "ja",
    }

    current_code = transcriber.get_language()
    current_name = next((k for k, v in options.items() if v == current_code), "Русский (ru)")
    var = ctk.StringVar(value=current_name)

    ctk.CTkLabel(win, text="Язык распознавания:").pack(pady=(10, 5))
    menu = ctk.CTkOptionMenu(win, variable=var, values=list(options.keys()))
    menu.pack(padx=20, pady=10)

    def _save():
        lang_code = options[var.get()] or "ru"
        transcriber.set_language(lang_code)
        config["language"] = lang_code
        save_config(config)
        win.destroy()

    ctk.CTkButton(win, text="Сохранить", command=_save).pack(pady=20)



# ---------- main() ----------

def main():
    # check ffmpeg
    try:
        subprocess.run(["ffmpeg", "-version"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except FileNotFoundError:
        print("FFmpeg не найден. Установи ffmpeg и попробуй снова.")
        return
    
    config = load_config()        
    root = ctk.CTk()

    speaker_q = queue.Queue()
    mic_q = queue.Queue()

    mic_rec = AudioRecorder.DefaultMicRecorder()
    mic_rec.record_into_queue(mic_q)
    time.sleep(1)
    spk_rec = AudioRecorder.DefaultSpeakerRecorder()
    spk_rec.record_into_queue(speaker_q)

    model = TranscriberModels.get_model(use_api=True)

    log_mgr = LogManager(log_dir=os.path.join(os.path.dirname(__file__), "log"))

    transcriber = AudioTranscriber(
        mic_rec.source,
        spk_rec.source,
        model,
        context_depth=CONTEXT_DEPTH_DEFAULT,
        logger=log_mgr,
        language=config.get("language", "ru"),
    )

    gpt_mgr = GPTManager(transcriber)

    thr = threading.Thread(target=transcriber.transcribe_audio_queue, args=(speaker_q, mic_q))
    thr.daemon = True
    thr.start()

    create_ui(root, transcriber, gpt_mgr, mic_rec, spk_rec, config)

    root.mainloop()


if __name__ == "__main__":
    main()
