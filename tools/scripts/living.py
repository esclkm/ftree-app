"""Кто в дереве считается живым — одно правило на всё приложение (сайт, сторож личного, выгрузки).

Живой — у кого нет даты смерти и кто родился не раньше, чем `living_years` лет назад (ftree.toml, раздел [privacy];
по умолчанию 110). Пример: сейчас 2026 год, правило 110 лет. Родился в 1964-м, смерти нет — живой. Родился в 1890-м,
смерти нет — уже нет: 136 лет никто не живёт. Год рождения неизвестен — решает тот, кто спрашивает (`unknown`): сайту
важно не закрыть паролем всех предков без дат, а выгрузке на чужой сайт — не отдать лишнего о том, о ком мало известно.
"""
from __future__ import annotations

from datetime import date

import dates
import paths


def living_years() -> int:
    return int(paths.tree_conf("privacy.living_years", 110) or 110)


def is_living(born, died, unknown: bool = False, today: date | None = None) -> bool:
    """born, died — дата карточки (строка, GDate или None). Есть смерть — не живой; родился позже, чем `living_years`
    лет назад, — живой; года рождения нет — `unknown`."""
    if died is not None and str(died).strip():
        return False
    y = born.first_year if isinstance(born, dates.GDate) else dates.year(born)
    if not y:
        return unknown
    return y > (today or date.today()).year - living_years()
