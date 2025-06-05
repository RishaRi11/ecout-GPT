from openai import OpenAI

class APIWhisperTranscriber:
    def __init__(self, api_key=None):
        self.client = OpenAI(api_key=api_key)

    def get_transcription(self, wav_file_path, language="ru"):
        try:
            with open(wav_file_path, "rb") as audio_file:
                result = self.client.audio.transcriptions.create(
                    model="whisper-1",
                    file=audio_file,
                    language=language,
                )
            return result.text.strip()
        except Exception as e:
            print(e)
            return ''


def get_model(*_, **__):
    return APIWhisperTranscriber()
