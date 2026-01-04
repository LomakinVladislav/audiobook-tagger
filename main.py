import os
import shutil
from pathlib import Path
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TDRC, TRCK, TPOS, TCON, TLAN

# ========== НАСТРОЙКИ ==========
# Меняйте эти переменные под свои нужды

ARTIST = "Саймон Маршалл Лесли Патерсон"
ALBUM = "В голове победителя Как тренировать мозг..."
ALBUM_ARTIST = "Игорь Ломакин"
YEAR = "2026"

# Жанр (константа)
GENRE = "Аудиокнига"

# Начинать нумерацию треков с:
START_TRACK_NUMBER = 1

# ===============================

def process_audiobook_files():
    """
    Основная функция для обработки аудиокниг
    """
    # Создаем пути к папкам
    project_root = Path(__file__).parent
    source_dir = project_root / "source"
    result_dir = project_root / "result"
    
    # Проверяем существование папки source
    if not source_dir.exists() or not source_dir.is_dir():
        print("Ошибка: Папка source не найдена или не является папкой!")
        return
    
    # Создаем папку result если её нет
    result_dir.mkdir(exist_ok=True)
    
    # Получаем список mp3 файлов в папке source и сортируем по имени
    mp3_files = sorted(list(source_dir.glob("*.mp3")))
    
    if not mp3_files:
        print("В папке source не найдено mp3 файлов!")
        return
    
    print("=" * 60)
    print("НАСТРОЙКИ:")
    print("=" * 60)
    print(f"Артист: {ARTIST}")
    print(f"Альбом: {ALBUM}")
    print(f"Артист альбома: {ALBUM_ARTIST}")
    print(f"Год: {YEAR}")
    print(f"Жанр: {GENRE}")
    print(f"Начальный номер трека: {START_TRACK_NUMBER}")
    print(f"Всего файлов: {len(mp3_files)}")
    print("=" * 60)
    
    # Обрабатываем каждый файл
    for index, mp3_file in enumerate(mp3_files, start=START_TRACK_NUMBER):
        print(f"\nОбработка файла {index}/{len(mp3_files)}: {mp3_file.name}")
        
        # Создаем путь для результата
        result_file = result_dir / mp3_file.name
        
        try:
            # Копируем файл
            shutil.copy2(mp3_file, result_file)
            print(f"✓ Файл скопирован")
            
            # Применяем теги
            if apply_audiobook_tags(result_file, index, len(mp3_files)):
                print(f"✓ Теги добавлены")
            else:
                print(f"✗ Ошибка при добавлении тегов")
                
        except Exception as e:
            print(f"✗ Ошибка при обработке файла: {e}")
    
    print(f"\n{'=' * 60}")
    print(f"ГОТОВО! Обработано {len(mp3_files)} файлов.")
    print(f"Результаты сохранены в папке: {result_dir}")
    print(f"{'=' * 60}")

def apply_audiobook_tags(file_path, track_number, total_tracks):
    """
    Применяет теги аудиокниги к файлу
    
    Args:
        file_path: Путь к файлу
        track_number: Номер текущего трека
        total_tracks: Общее количество треков
    """
    try:
        # Открываем файл
        audio = MP3(file_path, ID3=ID3)
        
        # Создаем теги если их нет
        try:
            audio.add_tags()
        except:
            pass
        
        # 1. ТРЕК (TRCK) - сквозная нумерация
        track_str = f"{track_number:02d}"  # Формат "01", "02", ...
        if total_tracks > 0:
            track_info = f"{track_str}/{total_tracks:02d}"
        else:
            track_info = track_str
        audio['TRCK'] = TRCK(encoding=3, text=track_info)
        
        # 2. НАЗВАНИЕ (TIT2) - НЕ меняем, оставляем оригинальное
        # Если хотите все равно установить, раскомментируйте:
        audio['TIT2'] = TIT2(encoding=3, text=f"Глава {track_number}")
        
        # 3. АРТИСТ (TPE1) - автор книги
        audio['TPE1'] = TPE1(encoding=3, text=ARTIST)
        
        # 4. АЛЬБОМ (TALB) - название книги
        album_title = ALBUM
        audio['TALB'] = TALB(encoding=3, text=album_title)
        
        # 5. АРТИСТ АЛЬБОМА (TPE2) - чтец/озвучка
        audio['TPE2'] = TPE2(encoding=3, text=ALBUM_ARTIST)
        
        # 6. ГОД (TDRC) - год выпуска
        audio['TDRC'] = TDRC(encoding=3, text=YEAR)
        
        # 7. ЖАНР (TCON) - всегда "Аудиокнига"
        audio['TCON'] = TCON(encoding=3, text=GENRE)
        
        # 8. ДИСК (TPOS) - если книга в нескольких частях/томах
        # audio['TPOS'] = TPOS(encoding=3, text="1/1")
        
        # 9. ЯЗЫК (TLAN) - опционально
        # audio['TLAN'] = TLAN(encoding=3, text=LANGUAGE)
        
        # 10. КОММЕНТАРИЙ (COMM) - можно добавить информацию
        # from mutagen.id3 import COMM
        # comment_text = f"Аудиокнига, {YEAR} год, озвучка: {ALBUM_ARTIST}"
        # audio['COMM'] = COMM(encoding=3, lang='rus', desc='', text=comment_text)
        
        # Сохраняем изменения
        audio.save()
        return True
        
    except Exception as e:
        print(f"Ошибка при применении тегов: {e}")
        return False

if __name__ == "__main__":
    print("Скрипт для обработки аудиокниг")
    print("=" * 60)
    
    process_audiobook_files()