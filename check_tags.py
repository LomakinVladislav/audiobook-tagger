from mutagen.mp3 import MP3
from mutagen.id3 import ID3
from pathlib import Path

def check_target_tags():
    """Проверяет только целевые теги в файле example.mp3"""
    example_file = Path(__file__).parent / "example.mp3"
    
    if not example_file.exists():
        print("✗ Файл example.mp3 не найден в корне проекта!")
        print("  Поместите файл example.mp3 в ту же папку, где находится этот скрипт.")
        return False
    
    try:
        audio = MP3(example_file, ID3=ID3)
        
        if not audio.tags:
            print("✗ В файле example.mp3 нет тегов ID3!")
            return False
        
        print("\n" + "=" * 70)
        print("ПРОВЕРКА ТЕГОВ ДЛЯ РЕДАКТИРОВАНИЯ:")
        print("=" * 70)
        
        # Только те теги, которые нас интересуют
        target_tags = {
            'TRCK': 'Трек',
            'TIT2': 'Название', 
            'TPE1': 'Артист',
            'TALB': 'Альбом',
            'TPE2': 'Артист альбома',
            'TDRC': 'Год',
            'TCON': 'Жанр',
        }
        
        results = {}
        print(f"{'ТЕГ':25} | {'ID3':6} | {'СТАТУС':15} | {'ЗНАЧЕНИЕ'}")
        print("-" * 70)
        
        for tag_id, tag_name in target_tags.items():
            if tag_id in audio.tags:
                value = audio.tags[tag_id]
                if hasattr(value, 'text'):
                    tag_value = value.text[0]
                    status = "✓ НАЙДЕН"
                else:
                    tag_value = str(value)
                    status = "✓ НАЙДЕН (не текст)"
                results[tag_id] = tag_value
            else:
                tag_value = "-"
                status = "✗ ОТСУТСТВУЕТ"
                results[tag_id] = None
            
            print(f"{tag_name:25} | {tag_id:6} | {status:15} | {tag_value}")
        
        print("\n" + "=" * 70)
        print("АНАЛИЗ РЕЗУЛЬТАТОВ:")
        print("-" * 70)
        
        # Проверяем, какие теги нужно будет создавать
        missing_tags = [tag_name for tag_id, tag_name in target_tags.items() 
                       if results.get(tag_id) is None]
        
        if missing_tags:
            print(f"Будут СОЗДАНЫ новые теги ({len(missing_tags)}):")
            for tag in missing_tags:
                print(f"  - {tag}")
        else:
            print("Все целевые теги найдены в example.mp3")
        
        existing_tags = [tag_name for tag_id, tag_name in target_tags.items() 
                        if results.get(tag_id) is not None]
        
        if existing_tags:
            print(f"\nБудут ПЕРЕЗАПИСАНЫ теги ({len(existing_tags)}):")
            for tag in existing_tags:
                print(f"  - {tag}")
        
        # Важные примечания
        print("\n" + "=" * 70)
        print("ВАЖНЫЕ ЗАМЕЧАНИЯ:")
        print("-" * 70)
        print("1. Тег 'Трек (TRCK)' будет заменен на сквозную нумерацию: '01', '02', ...")
        print("2. Тег 'Название (TIT2)' можно оставить оригинальным или заменить на 'Глава X'")
        print("3. Остальные теги берутся из переменных в основном скрипте")
        print("4. Все файлы в папке source получат одинаковые теги (кроме номера трека)")
        
        return True
        
    except Exception as e:
        print(f"✗ Ошибка при чтении файла: {e}")
        return False

if __name__ == "__main__":
    print("Скрипт проверки тегов аудиокниги")
    print("=" * 70)
    check_target_tags()