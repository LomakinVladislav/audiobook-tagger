import os
import shutil
import threading
from pathlib import Path
import datetime

import tkinter as tk
from tkinter import filedialog, messagebox, scrolledtext, ttk

import mutagen
from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TDRC, TRCK, TCON
from mutagen.wave import WAVE

# ========== РАБОТА С ТЕГАМИ ==========
def apply_audio_tags(file_path, track_number, total_tracks, settings):
    """
    Универсальная установка тегов через mutagen.File
    """
    try:
        audio = mutagen.File(file_path)
        if audio is None:
            raise Exception("Не удалось загрузить файл")

        track_str = f"{track_number:02d}"
        track_info = f"{track_str}/{total_tracks:02d}" if total_tracks > 0 else track_str

        # MP3 – ID3 теги
        if isinstance(audio, MP3):
            try:
                audio.add_tags()
            except Exception:
                pass  # теги уже есть
            audio['TRCK'] = TRCK(encoding=3, text=track_info)
            audio['TPE1'] = TPE1(encoding=3, text=settings['ARTIST'])
            audio['TALB'] = TALB(encoding=3, text=settings['ALBUM'])
            audio['TPE2'] = TPE2(encoding=3, text=settings['ALBUM_ARTIST'])
            audio['TDRC'] = TDRC(encoding=3, text=settings['YEAR'])
            audio['TCON'] = TCON(encoding=3, text=settings['GENRE'])

        # WAV – LIST INFO chunk
        elif isinstance(audio, WAVE):
            if audio.tags is None:
                audio.add_tags()   # создаёт пустой INFO chunk
            # Записываем стандартные поля
            audio.tags['ITRK'] = track_info
            audio.tags['IART'] = settings['ARTIST']
            audio.tags['IPRD'] = settings['ALBUM']
            audio.tags['ICRD'] = settings['YEAR']
            audio.tags['IGNR'] = settings['GENRE']
            audio.tags['ICMT'] = f"Album Artist: {settings['ALBUM_ARTIST']}"
            # Оригинальное имя файла можно оставить как TITLE (нестандартно)
            audio.tags['TITLE'] = Path(file_path).stem

        audio.save()
        return True

    except Exception as e:
        raise Exception(f"Ошибка тегов: {e}")


def process_file(src_path, dst_path, track_number, total_tracks, settings, log_callback):
    """Копирует файл и применяет теги"""
    try:
        shutil.copy2(src_path, dst_path)
        if not dst_path.exists():
            raise Exception("Файл не был скопирован")

        log_callback(f"  Копирован: {src_path.name}")
        apply_audio_tags(dst_path, track_number, total_tracks, settings)
        log_callback(f"  Теги применены")
        return True

    except Exception as e:
        log_callback(f"  Ошибка: {e}")
        return False


def process_audiobook(source_dir, result_dir, settings, log_callback, should_stop):
    """
    Основная функция обработки.
    should_stop – вызываемый объект, возвращающий True, если нужно остановить.
    """
    source_path = Path(source_dir)
    result_path = Path(result_dir)

    if not source_path.exists():
        log_callback("Ошибка: исходная папка не существует")
        return

    result_path.mkdir(parents=True, exist_ok=True)

    files = sorted(list(source_path.glob("*.mp3")) + list(source_path.glob("*.wav")))
    if not files:
        log_callback("Нет файлов .mp3 или .wav в выбранной папке")
        return

    start_track = settings.get('START_TRACK_NUMBER', 1)
    total = len(files)
    log_callback(f"Найдено файлов: {total}")
    log_callback(f"Начальный номер: {start_track}")

    success_count = 0
    for idx, file in enumerate(files, start=start_track):
        if should_stop():
            log_callback("Остановка по запросу.")
            break

        log_callback(f"\n[{idx - start_track + 1}/{total}] {file.name}")
        dst = result_path / file.name
        if process_file(file, dst, idx, total, settings, log_callback):
            success_count += 1

    log_callback(f"\nОбработка завершена. Успешно: {success_count} из {total}")


# ========== GUI ==========
class AudioBookProcessorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("Аудиокнига - обработчик тегов")
        self.root.geometry("700x600")
        self.root.resizable(True, True)

        # Переменные
        self.source_dir = tk.StringVar()
        self.result_dir = tk.StringVar()
        self.artist = tk.StringVar(value="")
        self.album = tk.StringVar(value="")
        self.album_artist = tk.StringVar(value="")
        self.year = tk.StringVar(value=str(datetime.datetime.now().year))
        self.genre = tk.StringVar(value="Аудиокнига")
        self.start_track = tk.IntVar(value=1)

        self.stop_processing = False
        self.create_widgets()

    def create_widgets(self):
        # Рамка выбора папок
        folder_frame = ttk.LabelFrame(self.root, text="Папки", padding=5)
        folder_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(folder_frame, text="Исходная папка:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(folder_frame, textvariable=self.source_dir, width=50).grid(row=0, column=1, padx=5, pady=2)
        ttk.Button(folder_frame, text="Обзор...", command=self.select_source).grid(row=0, column=2, padx=5, pady=2)

        ttk.Label(folder_frame, text="Папка результата:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(folder_frame, textvariable=self.result_dir, width=50).grid(row=1, column=1, padx=5, pady=2)
        ttk.Button(folder_frame, text="Обзор...", command=self.select_result).grid(row=1, column=2, padx=5, pady=2)

        # Рамка метаданных
        tags_frame = ttk.LabelFrame(self.root, text="Метаданные", padding=5)
        tags_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(tags_frame, text="Автор:").grid(row=0, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(tags_frame, textvariable=self.artist, width=40).grid(row=0, column=1, padx=5, pady=2)

        ttk.Label(tags_frame, text="Название книги:").grid(row=1, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(tags_frame, textvariable=self.album, width=40).grid(row=1, column=1, padx=5, pady=2)

        ttk.Label(tags_frame, text="Чтец:").grid(row=2, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(tags_frame, textvariable=self.album_artist, width=40).grid(row=2, column=1, padx=5, pady=2)

        ttk.Label(tags_frame, text="Год:").grid(row=3, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(tags_frame, textvariable=self.year, width=40).grid(row=3, column=1, padx=5, pady=2)

        ttk.Label(tags_frame, text="Жанр:").grid(row=4, column=0, sticky="w", padx=5, pady=2)
        ttk.Entry(tags_frame, textvariable=self.genre, width=40).grid(row=4, column=1, padx=5, pady=2)

        ttk.Label(tags_frame, text="Начальный номер трека:").grid(row=5, column=0, sticky="w", padx=5, pady=2)
        ttk.Spinbox(tags_frame, from_=1, to=999, textvariable=self.start_track, width=10).grid(row=5, column=1, sticky="w", padx=5, pady=2)

        # Кнопки
        btn_frame = ttk.Frame(self.root)
        btn_frame.pack(fill="x", padx=10, pady=5)

        ttk.Button(btn_frame, text="Начать обработку", command=self.start_processing).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Остановить", command=self.stop_processing_func).pack(side="left", padx=5)
        ttk.Button(btn_frame, text="Открыть папку результата", command=self.open_result_folder).pack(side="left", padx=5)

        # Лог
        log_frame = ttk.LabelFrame(self.root, text="Лог", padding=5)
        log_frame.pack(fill="both", expand=True, padx=10, pady=5)
        self.log_area = scrolledtext.ScrolledText(log_frame, wrap=tk.WORD, height=20)
        self.log_area.pack(fill="both", expand=True)

        # Статус
        self.status_var = tk.StringVar(value="Готов")
        status_bar = ttk.Label(self.root, textvariable=self.status_var, relief=tk.SUNKEN, anchor=tk.W)
        status_bar.pack(fill="x", padx=10, pady=2)

    def select_source(self):
        folder = filedialog.askdirectory(title="Выберите папку с исходными файлами")
        if folder:
            self.source_dir.set(folder)
            self.result_dir.set(os.path.join(folder, "result"))

    def select_result(self):
        folder = filedialog.askdirectory(title="Выберите папку для сохранения результата")
        if folder:
            self.result_dir.set(folder)

    def stop_processing_func(self):
        self.stop_processing = True
        self.log("Остановка по запросу...")

    def open_result_folder(self):
        """Открывает папку результата в проводнике Windows"""
        folder = self.result_dir.get().strip()
        if not folder:
            messagebox.showwarning("Предупреждение", "Папка результата не указана")
            return
        if not os.path.isdir(folder):
            messagebox.showwarning("Предупреждение", f"Папка не существует:\n{folder}")
            return
        try:
            os.startfile(folder)
        except Exception as e:
            messagebox.showerror("Ошибка", f"Не удалось открыть папку:\n{e}")

    def log(self, message):
        """Безопасное добавление в лог из любого потока"""
        def _update():
            self.log_area.insert(tk.END, message + "\n")
            self.log_area.see(tk.END)
        self.root.after(0, _update)

    def start_processing(self):
        source = self.source_dir.get().strip()
        if not source:
            messagebox.showerror("Ошибка", "Укажите исходную папку")
            return
        if not os.path.isdir(source):
            messagebox.showerror("Ошибка", "Исходная папка не существует")
            return

        result = self.result_dir.get().strip()
        if not result:
            result = os.path.join(source, "result")
            self.result_dir.set(result)

        settings = {
            'ARTIST': self.artist.get().strip(),
            'ALBUM': self.album.get().strip(),
            'ALBUM_ARTIST': self.album_artist.get().strip(),
            'YEAR': self.year.get().strip(),
            'GENRE': self.genre.get().strip(),
            'START_TRACK_NUMBER': self.start_track.get()
        }

        # Очистка лога
        self.log_area.delete(1.0, tk.END)
        self.status_var.set("Обработка...")
        self.stop_processing = False

        # Запуск в отдельном потоке
        thread = threading.Thread(target=self.run_processing, args=(source, result, settings), daemon=True)
        thread.start()

    def run_processing(self, source, result, settings):
        def log_callback(msg):
            self.log(msg)

        try:
            process_audiobook(source, result, settings, log_callback, lambda: self.stop_processing)
        except Exception as e:
            log_callback(f"Критическая ошибка: {e}")
        finally:
            self.root.after(0, lambda: self.status_var.set("Готов"))
            self.log("\nОбработка завершена.")


if __name__ == "__main__":
    root = tk.Tk()
    app = AudioBookProcessorApp(root)
    root.mainloop()