"""Годы жизни для подписи: «1902–1986», «1921–?», «~2005». Общие для HTML-страниц и для JSON."""
import datetime
import re

import dates
from cards.notes import year


# Колонка «Где» линии жизни — населённый пункт, где человек был в это время (город, деревня; ссылкой на карточку места).
# На странице её нет — две колонки, как раньше; в данные сайта она идёт отдельным полем where, чтобы видеть переезды.
WHERE_COL = re.compile(r"(где|dónde|donde|gdzie|where)$", re.I)


def life_year(v):
    """Год для шапки: точный — «1986»; «до 1986» (BEF) — «<1986»; «после 1986» (AFT) — «>1986»; «около», «между»
    и прочее неточное (ABT, EST, CAL, BET …) — «~1986»."""
    y, g = year(v), dates.card_or_none(v)
    if not (y and g and g.approx):
        return y
    return {"BEF": "<", "AFT": ">"}.get(g.kind, "~") + str(y)


def lifespan(born, died, death_event=False):
    """Живой — «1986»; умер — «1902–1986»; чего не знаем — «?»: «?–1942», «1871–?»; приблизительно — «~2005».
    Умер — если есть год смерти, событие смерти или похорон (death_event) или родился больше 100 лет назад."""
    b, x, by = life_year(born), life_year(died), year(born)
    if bool(x or died) or (by and by < datetime.date.today().year - 100) or death_event:
        return f"{b or '?'}–{x or '?'}"
    return str(b) if b else ""
