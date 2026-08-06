"""
Озвучка текста — через edge-tts (бесплатно, без ключа, использует голоса
Microsoft Edge). Для другого качества можно позже заменить на ElevenLabs
или Google Cloud TTS, интерфейс функции останется тем же.
"""

import asyncio
import edge_tts

# Список голосов: `edge-tts --list-voices | grep ru-RU`
VOICE = "ru-RU-DmitryNeural"  # мужской, энергичный; альтернатива: ru-RU-SvetlanaNeural


async def _synthesize(text: str, out_path: str, voice: str, rate: str) -> None:
    communicate = edge_tts.Communicate(text, voice=voice, rate=rate)
    await communicate.save(out_path)


def synthesize_speech(text: str, out_path: str = "voice.mp3", voice: str = VOICE, rate: str = "+8%") -> str:
    """Сохраняет озвучку в mp3 и возвращает путь к файлу."""
    asyncio.run(_synthesize(text, out_path, voice, rate))
    return out_path


if __name__ == "__main__":
    path = synthesize_speech("Знаете ли вы, что осьминоги имеют три сердца?")
    print("Сохранено:", path)
