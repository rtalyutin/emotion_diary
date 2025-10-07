# Руководство по внесению изменений

## Начало работы

1. Создайте виртуальное окружение и установите зависимости для разработки:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -e .[dev]
   ```
2. Установите git-хуки и выполните полную проверку до коммита:
   ```bash
   pre-commit install
   pre-commit run --all-files
   ```
   Команда прогонит `ruff`, `black`, `mypy --strict`, `bandit`, `pip-audit`, а также `pytest` под `coverage` с порогом 85%.

## Перед отправкой pull request

- Убедитесь, что пайплайн CI (GitHub Actions `CI`) проходит на вашей ветке и ветке `main` без ошибок.
- Обновите документацию при изменении поведения или зависимостей.
- Соблюдайте формат Conventional Commits для сообщений.
- Для значимых изменений добавляйте или обновляйте тесты.

## Review checklist

- [ ] Все проверки `pre-commit run --all-files` зелёные.
- [ ] Локально пройдены `pytest`, `mypy --strict src/`, `bandit -c pyproject.toml -r src/`, `pip-audit --strict --skip-editable .`.
- [ ] Ветка успешно проходит GitHub Actions `CI`.
