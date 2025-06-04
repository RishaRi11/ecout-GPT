import os, time, openai

print("KEY:", (os.getenv("OPENAI_API_KEY") or "")[:8] + "...")

print("HTTP_PROXY =", os.getenv("HTTP_PROXY"))
print("HTTPS_PROXY =", os.getenv("HTTPS_PROXY"))

client = openai.OpenAI()          # ← берёт ключ и прокси из env
t = time.time()
try:
    client.models.list()          # короткий запрос «список моделей»
    print("✓ OpenAI ответил за", round(time.time() - t, 2), "сек.")
except Exception as e:
    print("❌ Ошибка:", e)
