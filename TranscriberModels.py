import torch
from faster_whisper import WhisperModel
from openai import AsyncOpenAI

def get_model(use_api):
    if use_api:
        return APIWhisperTranscriber()
    else:
        return FasterWhisperTranscriber()

class FasterWhisperTranscriber:
    def __init__(self):
        print(f"[INFO] Loading Faster Whisper model...")
        self.model = WhisperModel(
            "tiny.en",
            device="cuda" if torch.cuda.is_available() else "cpu",
            compute_type="float32" if torch.cuda.is_available() else "int8",
        )
        print(f"[INFO] Faster Whisper using GPU: {torch.cuda.is_available()}")

    async def get_transcription(self, wav_file_path, language="ru"):
        try:
            # language игнорируется для локальной модели
            segments, _ = self.model.transcribe(wav_file_path, beam_size=5)
            full_text = " ".join(segment.text for segment in segments)
            return full_text.strip()
        except Exception as e:
            print(e)
            return ''

class APIWhisperTranscriber:
    def __init__(self, api_key=None):
        self.client = AsyncOpenAI(api_key=api_key)

    async def get_transcription(self, wav_file_path, language="ru"):
        try:
            with open(wav_file_path, "rb") as audio_file:
                result = await self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                )
            return result.text.strip()
        except Exception as e:
            print(e)
            return ''
