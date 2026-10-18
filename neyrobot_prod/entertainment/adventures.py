"""Finite, replayable interactive adventures without external model or billing calls."""
from __future__ import annotations
from dataclasses import dataclass, replace

STORIES = {
    "detective": (
        ("🕵️ Из музея исчез редкий экспонат. С чего начнёте?", ("Осмотреть витрину", "Опросить охранника"), (1, 2)),
        ("На стекле обнаружен след перчатки. Что дальше?", ("Проверить камеры", "Обвинить директора"), (3, 4)),
        ("Охранник видел курьера после закрытия. Ваш шаг?", ("Проверить накладные", "Закрыть дело"), (3, 4)),
        ("Камеры и накладные совпали: курьер подменил коробку. Дело раскрыто! 🏆", (), ()),
        ("Подозреваемый предупреждён, улики потеряны. Попробуйте другой путь.", (), ()),
    ),
    "story": (
        ("🚀 Ваш корабль поймал неизвестный сигнал. Что делаете?", ("Ответить", "Исследовать источник"), (1, 2)),
        ("Сигнал оказался просьбой о помощи. Ваш выбор?", ("Отправить спасательный зонд", "Игнорировать"), (3, 4)),
        ("Вы обнаружили заброшенную станцию. Ваш выбор?", ("Пристыковаться", "Вернуться"), (3, 4)),
        ("Вы нашли команду исследователей и вернулись героями! 🌟", (), ()),
        ("Приключение завершено. В следующий раз попробуйте другой маршрут.", (), ()),
    ),
    "roleplay": (
        ("🐉 Вы — хранитель крепости. Дракон просит убежища.", ("Выслушать", "Отказать"), (1, 2)),
        ("Дракон обещает защитить деревню. Ваш ответ?", ("Заключить союз", "Потребовать золото"), (3, 4)),
        ("Дракон улетает, а на деревню идёт буря.", ("Позвать его обратно", "Укрыть жителей"), (3, 4)),
        ("Вы защитили деревню и заслужили доверие жителей! 🏆", (), ()),
        ("Ваш путь завершён. Попробуйте принять другое решение.", (), ()),
    ),
}
@dataclass(frozen=True)
class Adventure:
    story_id: str
    node: int = 0
    finished: bool = False

def start(story_id: str) -> Adventure:
    if story_id not in STORIES:
        raise ValueError("Unknown story")
    return Adventure(story_id)

def scene(session: Adventure):
    return STORIES[session.story_id][session.node]

def choose(session: Adventure, choice: int) -> Adventure:
    if session.finished:
        raise ValueError("Adventure finished")
    prompt, options, destinations = scene(session)
    if not 0 <= choice < len(options):
        raise ValueError("Invalid choice")
    destination = destinations[choice]
    return replace(session, node=destination, finished=not bool(STORIES[session.story_id][destination][1]))
