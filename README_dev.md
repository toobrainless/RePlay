## Инструкция для разработчика

### Проверка работы библиотеки после доработки
Запустите тестирующий скрипт `test_package.sh`, который сформирует документацию, проверит код pylint, pycodestyle и запустит тесты.
```bash
./test_package.sh
```
Для корректной работы скрипта в директории `replay` должна быть создана виртуальная среда venv.
```bash
python3 -m venv venv
source venv/bin/activate
```

### Проверка качества кода
Настройте pre-commit hooks для автоматического форматирования и проверки кода.\
Из директории `replay`:
```bash
pre-commit install
```