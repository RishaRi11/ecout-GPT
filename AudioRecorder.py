import speech_recognition as sr
import pyaudiowpatch as pyaudio
from datetime import datetime

RECORD_TIMEOUT = 3
ENERGY_THRESHOLD = 1000
DYNAMIC_ENERGY_THRESHOLD = False

class BaseRecorder:
    def __init__(self, source):
        self.recorder = sr.Recognizer()
        self.recorder.energy_threshold = ENERGY_THRESHOLD
        self.recorder.dynamic_energy_threshold = DYNAMIC_ENERGY_THRESHOLD

        if source is None:
            raise ValueError("audio source can't be None")

        self.source = source
        self.muted = False                     # ← флаг mute


    # ---------- Mute control ----------
    def set_muted(self, state: bool):
        """Включить / отключить отправку аудио в очередь."""
        self.muted = bool(state)

    # ---------- Capture ----------
    def record_into_queue(self, audio_queue):
        """
        Ставим listen_in_background и, если self.muted == True,
        просто игнорируем поступающие фреймы.
        """
        def record_callback(_, audio: sr.AudioData) -> None:
            if self.muted:                 # ← проверка mute
                return
            data = audio.get_raw_data()
            audio_queue.put((data, datetime.utcnow()))

        self._stopper = self.recorder.listen_in_background(   # NEW / FIX
            self.source,
            record_callback,
            phrase_time_limit=RECORD_TIMEOUT,
        )

    def stop(self):
        """Останавливает фоновую запись, если запущена."""
        if hasattr(self, "_stopper") and self._stopper:
            self._stopper()

    def adjust_for_noise(self, device_name, msg):
        print(f"[INFO] Adjusting for ambient noise from {device_name}. " + msg)
        with self.source:
            self.recorder.adjust_for_ambient_noise(self.source)
        print(f"[INFO] Completed ambient noise adjustment for {device_name}.")


class DefaultMicRecorder(BaseRecorder):
    def __init__(self):
        super().__init__(source=sr.Microphone(sample_rate=16000))
        self.adjust_for_noise("Default Mic", "Please make some noise from the Default Mic...")

class DefaultSpeakerRecorder(BaseRecorder):
    def __init__(self):
        with pyaudio.PyAudio() as p:
            wasapi_info = p.get_host_api_info_by_type(pyaudio.paWASAPI)
            default_speakers = p.get_device_info_by_index(wasapi_info["defaultOutputDevice"])
            
            if not default_speakers["isLoopbackDevice"]:
                for loopback in p.get_loopback_device_info_generator():
                    if default_speakers["name"] in loopback["name"]:
                        default_speakers = loopback
                        break
                else:
                    print("[ERROR] No loopback device found.")
        
        source = sr.Microphone(speaker=True,
                               device_index= default_speakers["index"],
                               sample_rate=int(default_speakers["defaultSampleRate"]),
                               chunk_size=pyaudio.get_sample_size(pyaudio.paInt16),
                               channels=default_speakers["maxInputChannels"])
        super().__init__(source=source)
        self.adjust_for_noise("Default Speaker", "Please make or play some noise from the Default Speaker...")