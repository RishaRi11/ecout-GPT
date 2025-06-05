import wave
import os
import threading
import tempfile
import speech_recognition as sr
import io
from datetime import timedelta, datetime, timezone
import pyaudiowpatch as pyaudio
from heapq import merge

PHRASE_TIMEOUT = 3.05
MAX_PHRASES = 10

class AudioTranscriber:
    def __init__(self, mic_source, speaker_source, model,
                 context_depth=3, pause_threshold=3.0, min_user_speech=1.5,
                 logger=None, language="ru"):
        self.context_start = 0
        self.context_end = context_depth - 1
        self.pause_threshold = pause_threshold
        self.min_user_speech = min_user_speech
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
                "last_spoken": None,
                "new_phrase": True,
                "process_data_func": self.process_mic_data
            },
            "Speaker": {
                "sample_rate": speaker_source.SAMPLE_RATE,
                "sample_width": speaker_source.SAMPLE_WIDTH,
                "channels": speaker_source.channels,
                "last_sample": bytes(),
                "last_spoken": None,
                "new_phrase": True,
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
        import queue

        while True:
            pending_transcriptions = []

            mic_data = []
            while True:
                try:
                    data, time_spoken = mic_queue.get_nowait()
                    self.update_last_sample_and_phrase_status("You", data, time_spoken)
                    mic_data.append((data, time_spoken))
                except queue.Empty:
                    break

            speaker_data = []
            while True:
                try:
                    data, time_spoken = speaker_queue.get_nowait()
                    self.update_last_sample_and_phrase_status("Speaker", data, time_spoken)
                    speaker_data.append((data, time_spoken))
                except queue.Empty:
                    break

            if mic_data:
                source_info = self.audio_sources["You"]
                try:
                    fd, path = tempfile.mkstemp(suffix=".wav")
                    os.close(fd)
                    source_info["process_data_func"](source_info["last_sample"], path)
                    text = self.audio_model.get_transcription(path, self.get_language())
                    if text != '' and text.lower() != 'you':
                        latest_time = max(time for _, time in mic_data)
                        pending_transcriptions.append(("You", text, latest_time))
                except Exception as e:
                    print(f"Transcription error for You: {e}")
                finally:
                    os.unlink(path)

            if speaker_data:
                source_info = self.audio_sources["Speaker"]
                try:
                    fd, path = tempfile.mkstemp(suffix=".wav")
                    os.close(fd)
                    source_info["process_data_func"](source_info["last_sample"], path)
                    text = self.audio_model.get_transcription(path, self.get_language())
                    if text != '' and text.lower() != 'you':
                        latest_time = max(time for _, time in speaker_data)
                        pending_transcriptions.append(("Speaker", text, latest_time))
                except Exception as e:
                    print(f"Transcription error for Speaker: {e}")
                finally:
                    os.unlink(path)

            if pending_transcriptions:
                pending_transcriptions.sort(key=lambda x: x[2])
                for who_spoke, text, time_spoken in pending_transcriptions:
                    self.update_transcript(who_spoke, text, time_spoken)
                    self._check_gpt_trigger()

                self.transcript_changed_event.set()

            threading.Event().wait(0.1)

    def update_last_sample_and_phrase_status(self, who_spoke, data, time_spoken):
        source_info = self.audio_sources[who_spoke]
        if source_info["last_spoken"] and time_spoken - source_info["last_spoken"] > timedelta(seconds=PHRASE_TIMEOUT):
            source_info["last_sample"] = bytes()
            source_info["new_phrase"] = True
        else:
            source_info["new_phrase"] = False

        source_info["last_sample"] += data
        source_info["last_spoken"] = time_spoken 

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

    def update_transcript(self, who_spoke, text, time_spoken):
        source_info = self.audio_sources[who_spoke]
        transcript = self.transcript_data[who_spoke]

        if source_info["new_phrase"] or len(transcript) == 0:
            if len(transcript) > MAX_PHRASES:
                transcript.pop(-1)
            transcript.insert(0, (f"{who_spoke}: [{text}]\n\n", time_spoken, who_spoke))
        else:
            transcript[0] = (f"{who_spoke}: [{text}]\n\n", time_spoken, who_spoke)

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

        self.audio_sources["You"]["new_phrase"] = True
        self.audio_sources["Speaker"]["new_phrase"] = True

    def _check_gpt_trigger(self):
        if not self._gpt_callback:
            return
        if not self.audio_sources['Speaker']['last_spoken']:
            return
        now = datetime.utcnow()
        pause = (now - self.audio_sources['Speaker']['last_spoken']).total_seconds()
        if pause >= self.pause_threshold:
            self._gpt_callback(self.get_current_prompt())
            return
        user_info = self.audio_sources['You']
        if user_info['last_spoken'] and (now - user_info['last_spoken']).total_seconds() < 3:
            dur = len(user_info['last_sample']) / (user_info['sample_rate'] * user_info['sample_width'])
            if dur >= self.min_user_speech:
                self._gpt_callback(self.get_current_prompt())
