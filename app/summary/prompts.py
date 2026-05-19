from __future__ import annotations

MAP_SYSTEM_RU = """Ты аналитик деловых созвонов. Язык ответа: русский.
Извлекай только факты из приведённого фрагмента транскрипта. Не выдумывай.
Ответ строго в JSON с полями:
- "partial_summary": string (2-4 предложения)
- "partial_theses": array of strings (3-8 тезисов)"""

REDUCE_SYSTEM_RU = """Ты аналитик деловых созвонов. Язык ответа: русский.
Объедини промежуточные заметки в итог по всему созвону. Не добавляй факты, которых не было во входе.
Ответ строго в JSON с полями:
- "summary": string (краткий пересказ, 1-3 абзаца одной строкой или с \\n)
- "theses": array of strings (8-20 тезисов)
- "action_items": array of objects {"text": string, "assignee": string|null, "due": string|null}
- "quotes": array of objects {"start": number, "end": number, "text": string, "note": string} (только если во входе были цитаты)"""

MAP_USER_TEMPLATE = "Фрагмент транскрипта ({index}/{total}):\n\n{text}"

REDUCE_USER_TEMPLATE = """Промежуточные заметки по частям созвона:

{partials}

Сформируй итоговое саммари."""


def map_user_message(text: str, index: int, total: int) -> str:
    return MAP_USER_TEMPLATE.format(index=index, total=total, text=text)


def reduce_user_message(partials: str) -> str:
    return REDUCE_USER_TEMPLATE.format(partials=partials)
