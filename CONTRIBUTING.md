# Руководство по внесению изменений

## Git-flow и ветки

Мы придерживаемся git-flow с двумя основными долгоживущими ветками:

- `main` — стабильные релизы.
- `develop` — актуальное состояние разработки.

Новые работы ведём в короткоживущих ветках с префиксами по типу задачи:

- `feature/<issue>-<slug>` для новых возможностей.
- `bugfix/<issue>-<slug>` для исправлений.
- `hotfix/<issue>-<slug>` для срочных правок в production.

Перед началом работы создайте ветку от `develop` и синхронизируйтесь с `main` перед релизом.

## Начало работы

1. Создайте виртуальное окружение и установите зависимости для разработки:
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   python -m pip install --upgrade pip
   python -m pip install -e .[dev]
   python -m pip install -e .[docs]  # для работы с документацией Sphinx
   ```
2. Установите git-хуки и выполните полную проверку до коммита:
   ```bash
   pre-commit install
   pre-commit run --all-files
   ```
   Команда прогонит `ruff`, `black`, `mypy --strict`, `bandit`, `pip-audit`, а также `pytest` под `coverage` с порогом 85%.

## Требования к pull request

- Используйте Conventional Commits в сообщениях и названиях PR.
- Опишите контекст задачи, ссылку на issue и сделанные изменения.
- Обновите документацию и `CHANGELOG.md`, если меняется поведение или интерфейсы.
- Добавьте или обновите тесты при изменении логики.
- Убедитесь, что ветка проходит пайплайн GitHub Actions `CI`.

## Перед отправкой на review

1. Выполните `pre-commit run --all-files`.
2. Запустите основные проверки вручную:
   ```bash
   ruff check src
   black --check src tests
   mypy --strict src/
   bandit -c pyproject.toml -r src/
   pip-audit --strict --skip-editable .
   pytest --cov=emotion_diary --cov-report=term-missing
   ```
3. При изменениях в документации соберите её локально:
   ```bash
   cd docs
   make html
   ```
4. Убедитесь, что `build/` и другие артефакты не попадают в git.

## Review checklist

- [ ] Все проверки `pre-commit run --all-files` зелёные.
- [ ] Локально пройдены `pytest`, `mypy --strict src/`, `bandit -c pyproject.toml -r src/`, `pip-audit --strict --skip-editable .`.
- [ ] Документация Sphinx успешно собирается (`make html`).
- [ ] Ветка успешно проходит GitHub Actions `CI`.
