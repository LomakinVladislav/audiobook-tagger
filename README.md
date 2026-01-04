## Запуск приложения

1. Клонировать репозиторий
```git clone https://github.com/LomakinVladislav/signature-detecting.git```
2. Создать виртуальное окружение
```python -m venv venv```
3. Перейти в витруальное окружение
```.\venv\Scripts\activate```
4. Установить зависимости
```pip install -r requirements.txt```
5. Запустить файл main.py
```python main.py```

Структура проекта:
File_tagger/
├── example.mp3          # файл с образцовыми тегами
├── source/              # папка с исходными mp3 файлами
├── requirements.txt
├── edit_tags.py         # основной скрипт
└── check_tags.py        # скрипт для проверки тегов (опционально)

Для изменения тегов редактировать поля ARTIST, ALBUM и т. д. в файле main.py. 
По умолчанию каждому треку будет присвоено название "Глава 1", "Глава 2", и т. д. 
Чтобы убрать эту функцию, закомментируйте (поставтье в начале строки //) строку 114 в файле main.py: audio['TIT2'] = TIT2(encoding=3, text=f"Глава {track_number}").