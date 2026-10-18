"""Deterministic game-session engine for GPT5 Studio AI.

No Telegram, provider, billing or network dependencies. The adapter must persist
GameSession per user and only advance it on an explicit user action.
"""
from __future__ import annotations
from dataclasses import dataclass, replace
from typing import Literal

Choice = Literal["a", "b", "c", "d"]

@dataclass(frozen=True)
class Question:
    prompt: str
    answers: tuple[str, str, str, str]
    correct: Choice
    explanation: str

@dataclass(frozen=True)
class GameSession:
    game_id: str
    round_index: int = 0
    score: int = 0
    answered: bool = False
    finished: bool = False

QUIZ: tuple[Question, ...] = (
    Question("Какая планета ближе всего к Солнцу?", ("Венера", "Меркурий", "Марс", "Земля"), "b", "Меркурий — первая планета Солнечной системы."),
    Question("Сколько сторон у шестиугольника?", ("5", "7", "6", "8"), "c", "У шестиугольника шесть сторон."),
    Question("Какой океан самый большой?", ("Индийский", "Атлантический", "Северный Ледовитый", "Тихий"), "d", "Тихий океан крупнейший по площади."),
    Question("Что измеряют в герцах?", ("Частоту", "Силу", "Давление", "Массу"), "a", "Герц — единица частоты."),
    Question("Какой язык используется для описания структуры веб-страниц?", ("SQL", "HTML", "Python", "CSS"), "b", "HTML задаёт структуру веб-страницы."),
)

def start(game_id: str = "quick_quiz") -> GameSession:
    if game_id not in GAME_BANKS:
        raise ValueError("Unsupported game")
    return GameSession(game_id=game_id)

def current_question(session: GameSession) -> Question | None:
    if session.finished:
        return None
    return GAME_BANKS[session.game_id][session.round_index]

def answer(session: GameSession, choice: str) -> tuple[GameSession, bool]:
    if session.finished or session.answered:
        raise ValueError("Round is not accepting answers")
    if choice not in ("a", "b", "c", "d"):
        raise ValueError("Invalid answer")
    correct = choice == GAME_BANKS[session.game_id][session.round_index].correct
    return replace(session, score=session.score + int(correct), answered=True), correct

def next_round(session: GameSession) -> GameSession:
    if session.finished or not session.answered:
        raise ValueError("Answer current round first")
    index = session.round_index + 1
    if index >= len(GAME_BANKS[session.game_id]):
        return replace(session, finished=True)
    return replace(session, round_index=index, answered=False)

def finish(session: GameSession) -> GameSession:
    return replace(session, finished=True)

GAME_BANKS = {"quick_quiz": QUIZ}

MOVIE_QUIZ = (
    Question("Какой фильм рассказывает о лайнере, столкнувшемся с айсбергом?", ("Аватар", "Титаник", "Матрица", "Начало"), "b", "«Титаник» посвящён трагедии лайнера."),
    Question("Кто режиссёр фильма «Начало»?", ("Нолан", "Кэмерон", "Спилберг", "Тарантино"), "a", "Режиссёр — Кристофер Нолан."),
    Question("Как зовут ковбоя из «Истории игрушек»?", ("Базз", "Симба", "Вуди", "Шрек"), "c", "Ковбоя зовут Вуди."),
    Question("В каком фильме герои живут внутри симуляции?", ("Интерстеллар", "Матрица", "Рокки", "Гладиатор"), "b", "Это сюжет «Матрицы»."),
    Question("Какая франшиза связана с джедаями?", ("Звёздные войны", "Форсаж", "Терминатор", "Миссия невыполнима"), "a", "Джедаи — персонажи «Звёздных войн»."),
)
KNOWLEDGE_QUIZ = (
    Question("Какой символ у вольфрама?", ("V", "W", "T", "Wo"), "b", "Химический символ вольфрама — W."),
    Question("Кто сформулировал три закона движения?", ("Фарадей", "Максвелл", "Ньютон", "Планк"), "c", "Исаак Ньютон."),
    Question("Столица Византийской империи?", ("Рим", "Афины", "Константинополь", "Антиохия"), "c", "Столицей был Константинополь."),
    Question("Сколько бит в байте?", ("4", "8", "16", "32"), "b", "В байте восемь бит."),
    Question("Самая большая планета Солнечной системы?", ("Земля", "Сатурн", "Нептун", "Юпитер"), "d", "Юпитер — крупнейшая планета."),
)
GAME_BANKS.update({"movie": MOVIE_QUIZ, "knowledge": KNOWLEDGE_QUIZ})
