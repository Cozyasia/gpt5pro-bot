import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from io import BytesIO

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import presentation_studio as ps

BRIEF = '''
Тема презентации
Коммерческая презентация бренда VERDIA HOME — производителя интеллектуальных модульных вертикальных садов.

Название бренда
VERDIA HOME

Слоган
Живая экосистема вашего пространства

Описание компании
VERDIA HOME создаёт модульные вертикальные сады с автоматическим поливом, фитосветом и сервисным обслуживанием.

Продуктовая линейка
VERDIA MINI — от 79 000 рублей.
VERDIA WALL — от 159 000 рублей.
VERDIA PRO — от 289 000 рублей.
VERDIA CARE — от 6 900 рублей в месяц.

Контакты
Телефон: +7 900 000-00-00
Telegram: @verdia_test
Email: hello@verdia.example
Сайт: verdia.example

Создать презентацию на 12 слайдов. Не выдумывать отзывы, статистику, сертификаты и кейсы.
'''.strip()


def make_image(index: int, size=(1536, 1024)) -> bytes:
    im = Image.new('RGB', size, (244, 241, 233))
    d = ImageDraw.Draw(im)
    d.rectangle((0, 0, size[0] // 3, size[1]), fill=(31, 77, 58))
    d.ellipse((size[0] // 2, 80, size[0] - 80, size[1] - 80), fill=(110, 139, 115))
    d.rectangle((size[0] // 3 + 80, 140, size[0] - 120, size[1] - 140), outline=(176, 141, 87), width=12)
    out = BytesIO(); im.save(out, 'PNG'); return out.getvalue()


class FakeMessage:
    def __init__(self):
        self.texts = []
        self.documents = []
        self.photos = []
        self.chat_id = 200
    async def reply_text(self, text, **kwargs):
        self.texts.append(text)
        return self
    async def reply_document(self, document, **kwargs):
        self.documents.append(kwargs.get('caption', ''))
        return self
    async def reply_photo(self, photo, **kwargs):
        self.photos.append(kwargs.get('caption', ''))
        return self


class FakeBot:
    async def send_chat_action(self, *args, **kwargs):
        return None


class FakeContext:
    def __init__(self):
        self.user_data = {}
        self.bot = FakeBot()


class FakeUpdate:
    def __init__(self):
        self.effective_user = SimpleNamespace(id=100, username='tester')
        self.effective_chat = SimpleNamespace(id=200)
        self.effective_message = FakeMessage()
        self.callback_query = None


async def fake_llm(update, prompt: str) -> str:
    if 'Извлеки факты из брифа' in prompt:
        return json.dumps({
            'brand_name': 'VERDIA HOME',
            'tagline': 'Живая экосистема вашего пространства',
            'objective': 'Коммерческая презентация',
            'product': 'Интеллектуальные модульные вертикальные сады',
            'audience': 'B2C и B2B',
            'positioning': 'premium eco-tech',
            'geography': 'Москва и Санкт-Петербург',
            'contacts': ['+7 900 000-00-00', '@verdia_test', 'hello@verdia.example', 'verdia.example'],
            'prices': ['от 79 000 рублей', 'от 159 000 рублей', 'от 289 000 рублей', 'от 6 900 рублей в месяц'],
            'requested_slide_count': 12,
            'visual_direction': 'premium eco-tech editorial',
        }, ensure_ascii=False)
    if 'Создай структуру коммерческой презентации' in prompt:
        titles = [
            'VERDIA HOME', 'Природа становится частью архитектуры', 'Проблема клиента',
            'Решение VERDIA HOME', 'Как работает технология', 'Ключевые преимущества',
            'Сценарии использования', 'Продуктовая линейка', 'VERDIA CARE',
            'Этапы реализации', 'Почему VERDIA HOME', 'Следующий шаг'
        ]
        layouts = ['cover','full_image','cards','split','process','cards','split','comparison','cards','process','cards','cta']
        return json.dumps({'slides': [
            {'title': t, 'layout': layouts[i], 'image_needed': i in {0,1,3,4,6,7,8,11},
             'bullets': [f'Тезис {i+1}.1', f'Тезис {i+1}.2'],
             'image_prompt': f'Premium vertical garden interior scene for slide {t}'}
            for i,t in enumerate(titles)
        ]}, ensure_ascii=False)
    if 'Подготовь финальный текст презентации' in prompt:
        titles = [
            'VERDIA HOME', 'Природа становится частью архитектуры', 'Проблема клиента',
            'Решение VERDIA HOME', 'Как работает технология', 'Ключевые преимущества',
            'Сценарии использования', 'Продуктовая линейка', 'VERDIA CARE',
            'Этапы реализации', 'Почему VERDIA HOME', 'Следующий шаг'
        ]
        slides=[]
        for i,t in enumerate(titles):
            bullets=[f'Содержательный тезис {i+1}.1', f'Содержательный тезис {i+1}.2']
            if i == 7:
                bullets=['VERDIA MINI — от 79 000 рублей', 'VERDIA WALL — от 159 000 рублей', 'VERDIA PRO — от 289 000 рублей']
            if i == 8:
                bullets=['VERDIA CARE — от 6 900 рублей в месяц', 'Регулярное обслуживание']
            if i == 11:
                bullets=['+7 900 000-00-00','@verdia_test','hello@verdia.example','verdia.example']
            slides.append({'title':t,'subtitle':'','bullets':bullets,'image_prompt':f'Photorealistic vertical garden scene {i+1}'})
        return json.dumps({'slides': slides}, ensure_ascii=False)
    return '{}'


async def fake_images(update, context, prompts, engine, feature):
    return [make_image(i, (1024,1024) if 'logo' in feature else (1536,1024)) for i,_ in enumerate(prompts)]


async def fake_paid(update, context, engine, feature, cost, action):
    return await action()


async def main():
    with tempfile.TemporaryDirectory() as td:
        ps.DB_PATH = str(Path(td) / 'test.db')
        studio = ps.PresentationStudio(
            ps.StudioConfig(db_path=ps.DB_PATH, data_dir=str(Path(td) / 'assets'), max_generated_images=10, render_cost_usd=0),
            fake_llm, fake_images, fake_paid,
        )
        update = FakeUpdate(); context = FakeContext()
        await studio.start(update, context, 'presentation')
        assert await studio.handle_text(update, context, BRIEF)
        project = ps._load(100)
        assert project['profile']['brand_name'] == 'VERDIA HOME', project['profile']
        assert len(project['structure']) == 12
        project['logo_notes'] = ['Минималистичный архитектурный модульный знак']
        await ps._generate_logos(project, update, context)
        project['logo_selected'] = project['logo_candidates'][1]
        project['image_mode'] = 'auto'
        project['generation_engine'] = 'auto'
        project['visual_notes'] = ['Фотореалистичные вертикальные сады, без абстрактных заглушек']
        project['style_notes'] = ['premium eco-tech editorial']
        project['palette_notes'] = ['#F4F1E9 #17211C #1F4D3A #6E8B73 #C9B99A #B08D57 #E7E3D9']
        ps._save(100, project)
        pdf, pptx = await ps._build_files(project, update, context)
        assert Path(pdf).exists() and Path(pdf).stat().st_size > 20_000
        assert Path(pptx).exists() and Path(pptx).stat().st_size > 20_000
        from PyPDF2 import PdfReader
        assert len(PdfReader(pdf).pages) == 12
        from pptx import Presentation
        assert len(Presentation(pptx).slides) == 12
        print('presentation v95 smoke test: OK')
        print(pdf)
        print(pptx)

if __name__ == '__main__':
    asyncio.run(main())
