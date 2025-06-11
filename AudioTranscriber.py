import wave
import os
import threading
import tempfile
import custom_speech_recognition as sr
import io
import asyncio
from datetime import timedelta, datetime, timezone
import pyaudiowpatch as pyaudio
from heapq import merge

PHRASE_TIMEOUT = 3.05
MAX_PHRASES = 10

class AudioTranscriber:
    def __init__(self, mic_source, speaker_source, model,
                 context_depth=3,
                 logger=None, language="ru"):
        self.context_start = 0
        self.context_end = context_depth - 1
        self.logger = logger
        self.language = language
        self._gpt_callback = None
        self.transcript_data = {"You": [], "Speaker": []}
        self.transcript_changed_event = threading.Event()
        self.audio_model = model
        self.audio_sources = {
            "You": {
                "sample_rate": mic_source.SAMPLE_RATE,
                "sample_width": mic_source.SAMPLE_WIDTH,
                "channels": mic_source.channels,
                "last_sample": bytes(),
                "phrase_buffer": bytearray(),
                "last_spoken": None,
                "new_phrase": True,
                "phrase_id": 0,
                "phrase_start": None,
                "process_data_func": self.process_mic_data
            },
            "Speaker": {
                "sample_rate": speaker_source.SAMPLE_RATE,
                "sample_width": speaker_source.SAMPLE_WIDTH,
                "channels": speaker_source.channels,
                "last_sample": bytes(),
                "phrase_buffer": bytearray(),
                "last_spoken": None,
                "new_phrase": True,
                "phrase_id": 0,
                "phrase_start": None,
                "process_data_func": self.process_speaker_data
            }
        }
        
    def set_gpt_callback(self, cb):
        self._gpt_callback = cb

    def get_language(self):
        return self.language

    def set_language(self, lang_code):
        self.language = lang_code

    def get_current_prompt(self):
        spk = self.transcript_data['Speaker']
        if not spk:
            return []
        start = min(self.context_start, len(spk) - 1)
        end = min(self.context_end, len(spk) - 1)
        if end < start:
            end = start
        return [t[0].strip() for t in spk[start:end + 1]]

    def transcribe_audio_queue(self, speaker_queue, mic_queue):
        asyncio.run(self.transcribe_audio_queue_async(speaker_queue, mic_queue))

    async def transcribe_audio_queue_async(self, speaker_queue, mic_queue):
        import queue

        pending_tasks = set()

        while True:
            now = datetime.utcnow()

            while True:
                try:
                    data, time_spoken = mic_queue.get_nowait()
                    completed = self.update_last_sample_and_phrase_status("You", data, time_spoken)
                    if completed:
                        buf, pid, t_spoken = completed
                        pending_tasks.add(asyncio.create_task(
                            self._process_phrase("You", buf, t_spoken, pid)
                        ))
                except queue.Empty:
                    break

            while True:
                try:
                    data, time_spoken = speaker_queue.get_nowait()
                    completed = self.update_last_sample_and_phrase_status("Speaker", data, time_spoken)
                    if completed:
                        buf, pid, t_spoken = completed
                        pending_tasks.add(asyncio.create_task(
                            self._process_phrase("Speaker", buf, t_spoken, pid)
                        ))
                except queue.Empty:
                    break

            for who in ("You", "Speaker"):
                src = self.audio_sources[who]
                if (
                    src["phrase_buffer"]
                    and src["last_spoken"] is not None
                    and now - src["last_spoken"] > timedelta(seconds=PHRASE_TIMEOUT)
                ):
                    buf = bytes(src["phrase_buffer"])
                    pid = src["phrase_id"]
                    t_spoken = src["last_spoken"]
                    src["phrase_buffer"] = bytearray()
                    src["phrase_id"] += 1
                    src["new_phrase"] = True
                    pending_tasks.add(asyncio.create_task(
                        self._process_phrase(who, buf, t_spoken, pid)
                    ))

            done = {t for t in pending_tasks if t.done()}
            for t in done:
                pending_tasks.remove(t)
                try:
                    await t
                except Exception as e:
                    print(f"Transcription task error: {e}")

            await asyncio.sleep(0.1)

    def update_last_sample_and_phrase_status(self, who_spoke, data, time_spoken):
        source_info = self.audio_sources[who_spoke]
        completed = None

        if (
            source_info["last_spoken"] is not None
            and time_spoken - source_info["last_spoken"] > timedelta(seconds=PHRASE_TIMEOUT)
            and source_info["phrase_buffer"]
        ):
            completed = (
                bytes(source_info["phrase_buffer"]),
                source_info["phrase_id"],
                source_info["last_spoken"],
            )
            source_info["phrase_buffer"] = bytearray()
            source_info["phrase_id"] += 1
            source_info["new_phrase"] = True
        else:
            source_info["new_phrase"] = False

        source_info["phrase_buffer"] += data
        source_info["last_sample"] = bytes(source_info["phrase_buffer"])
        source_info["last_spoken"] = time_spoken

        return completed

    async def _process_phrase(self, who_spoke, data, time_spoken, phrase_id):
        source_info = self.audio_sources[who_spoke]
        try:
            fd, path = tempfile.mkstemp(suffix=".wav")
            os.close(fd)
            source_info["process_data_func"](data, path)
            text = await self.audio_model.get_transcription(path, self.get_language())
            if text != '' and text.lower() != 'you':
                self.update_transcript(who_spoke, text, time_spoken, phrase_id)
                self._check_gpt_trigger()
                self.transcript_changed_event.set()
        except Exception as e:
            print(f"Transcription error for {who_spoke}: {e}")
        finally:
            os.unlink(path)

    def process_mic_data(self, data, temp_file_name):
        audio_data = sr.AudioData(data, self.audio_sources["You"]["sample_rate"], self.audio_sources["You"]["sample_width"])
        wav_data = io.BytesIO(audio_data.get_wav_data())
        with open(temp_file_name, 'w+b') as f:
            f.write(wav_data.read())

    def process_speaker_data(self, data, temp_file_name):
        with wave.open(temp_file_name, 'wb') as wf:
            wf.setnchannels(self.audio_sources["Speaker"]["channels"])
            p = pyaudio.PyAudio()
            wf.setsampwidth(p.get_sample_size(pyaudio.paInt16))
            wf.setframerate(self.audio_sources["Speaker"]["sample_rate"])
            wf.writeframes(data)

    def update_transcript(self, who_spoke, text, time_spoken, phrase_id):
        source_info = self.audio_sources[who_spoke]
        transcript = self.transcript_data[who_spoke]

        # Try to find existing entry for this phrase
        for idx, entry in enumerate(transcript):
            if len(entry) >= 4 and entry[3] == phrase_id:
                transcript[idx] = (f"{who_spoke}: [{text}]\n\n", time_spoken, who_spoke, phrase_id)
                break
        else:
            if len(transcript) >= MAX_PHRASES:
                transcript.pop(-1)
            transcript.insert(0, (f"{who_spoke}: [{text}]\n\n", time_spoken, who_spoke, phrase_id))

    def get_transcript(self):
        combined = list(merge(
            self.transcript_data["You"], self.transcript_data["Speaker"],
            key=lambda x: x[1], reverse=True))
        return combined[:MAX_PHRASES]   # список кортежей (text, time, role)

    def clear_transcript_data(self):
        self.transcript_data["You"].clear()
        self.transcript_data["Speaker"].clear()

        self.audio_sources["You"]["last_sample"] = bytes()
        self.audio_sources["Speaker"]["last_sample"] = bytes()
        self.audio_sources["You"]["phrase_buffer"] = bytearray()
        self.audio_sources["Speaker"]["phrase_buffer"] = bytearray()

        self.audio_sources["You"]["new_phrase"] = True
        self.audio_sources["Speaker"]["new_phrase"] = True

    def _check_gpt_trigger(self):
        if not self._gpt_callback:
            return
        self._gpt_callback(self.get_current_prompt())
