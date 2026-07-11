# v74 access presets — Neyro-Bot GPT 5 Studio

Сборка поверх v73. Изменения только по доступам/лимитам, меню и маркетинговые тексты v73 сохранены.

## Что добавлено

1. Полный безлимит по username:
   - `@NeyroBotSupport`
   - `@granova_elena`
   - старый `@gpt5pro_support` оставлен как запасной.

2. Промо-доступ для `@MrMariton`:
   - GPT-чат без дневного лимита;
   - платные функции — по `5` бесплатных запусков в день на каждую функцию отдельно.

3. Новая диагностика:
   - `/diag_access`

## ENV

Поставить/заменить в Render:

```env
UNLIM_USERNAMES=gpt5pro_support,neyrobotsupport,granova_elena
PROMO_DAILY5_USERNAMES=MrMariton
PROMO_UNLIM_GPT_USERNAMES=MrMariton
PROMO_DAILY5_PER_FUNCTION_LIMIT=5
```

`@` можно не писать. Регистр не важен.

## Замена файлов

В `gpt5pro-bot` заменить:

```text
main_v74_access_presets.py → main.py
requirements_v74_access_presets.txt → requirements.txt
runtime_v74_access_presets.txt → runtime.txt
render_v74_access_presets.yaml → render.yaml
```

WebApp менять не обязательно. `premium_v74_neyrobot_gpt5_studio_marketing.html` приложен только для комплекта.

## Проверка после деплоя

1. В боте:

```text
/version
/diag_access
```

2. Ожидаемая версия:

```text
v74-access-presets-2026-07-11
```

3. Проверка аккаунтов:
   - зайти с `@NeyroBotSupport` → `/diag_access` должен показать `unlimited: True`;
   - зайти с `@granova_elena` → `unlimited: True`;
   - зайти с `@MrMariton` → `promo_unlim_gpt: True`, `promo_daily5: True`.
