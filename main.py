import os
import shutil
import threading
import datetime
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

from mutagen.mp3 import MP3
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TDRC, TRCK, TCON

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

MIN_TRACK_WIDTH = 1
MAX_TRACK_WIDTH = 8  # максимум 7 ведущих нулей

# Виртуальные коды клавиш A / C / X / V (Windows VK-коды, они совпадают с ASCII-кодами
# букв и НЕ зависят от текущей раскладки клавиатуры — в отличие от keysym, который при
# кириллической раскладке превращается в "с", "в" и т.д. и не совпадает с "c", "v").
_CTRL_KEYCODES = {65: "select_all", 67: "copy", 88: "cut", 86: "paste"}


def bind_shortcuts(widget, kind="entry"):
    """
    Включает Ctrl+A/C/X/V для CTkEntry / CTkTextbox независимо от раскладки клавиатуры.
    Стандартные tk-биндинги завязаны на keysym, который при русской раскладке перестаёт
    совпадать с латинскими 'a'/'c'/'x'/'v' — из-за этого горячие клавиши "не работали".
    Здесь распознаём клавишу по keycode (физической клавише), это раскладко-независимо.
    """
    target = getattr(widget, "_entry", None) or getattr(widget, "_textbox", None) or widget

    def on_key(event):
        # 0x4 — бит модификатора Control в event.state
        if not (event.state & 0x4):
            return None

        keysym = (event.keysym or "").lower()
        action = _CTRL_KEYCODES.get(event.keycode)
        if action is None:
            # запасной путь для раскладок/платформ, где keysym остаётся латинским
            action = {"a": "select_all", "c": "copy", "x": "cut", "v": "paste"}.get(keysym)
        if action is None:
            return None

        if action == "select_all":
            if kind == "entry":
                target.select_range(0, "end")
                target.icursor("end")
            else:
                target.tag_add("sel", "1.0", "end")
        elif action == "copy":
            target.event_generate("<<Copy>>")
        elif action == "cut":
            target.event_generate("<<Cut>>")
        elif action == "paste":
            target.event_generate("<<Paste>>")
        return "break"

    target.bind("<KeyPress>", on_key)


class AudiobookTaggerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title("Аудиокнига — обработчик тегов")
        self.geometry("840x840")
        self.minsize(760, 760)

        # крупные шрифты для всего приложения
        self.font_normal = ctk.CTkFont(size=15)
        self.font_bold = ctk.CTkFont(size=17, weight="bold")
        self.font_header = ctk.CTkFont(size=20, weight="bold")

        self.stop_event = threading.Event()
        self.worker_thread = None

        self._build_ui()

    # ---------- UI ----------

    def _change_appearance(self, choice):
        mode = "Dark" if choice == "Тёмная" else "Light"
        ctk.set_appearance_mode(mode)

    def _build_ui(self):
        pad = {"padx": 14, "pady": 7}

        # ---- Заголовок + переключатель темы ----
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=16, pady=(16, 0))

        ctk.CTkLabel(top_frame, text="Аудиокнига — обработчик тегов", font=self.font_header).pack(side="left")

        self.theme_switch = ctk.CTkSegmentedButton(
            top_frame, values=["Тёмная", "Светлая"], command=self._change_appearance, font=self.font_normal
        )
        self.theme_switch.set("Тёмная")
        self.theme_switch.pack(side="right")

        # ---- Папки ----
        folders_frame = ctk.CTkFrame(self)
        folders_frame.pack(fill="x", padx=16, pady=(12, 8))

        ctk.CTkLabel(folders_frame, text="Папки", font=self.font_bold).grid(
            row=0, column=0, columnspan=3, sticky="w", padx=12, pady=(10, 4)
        )

        ctk.CTkLabel(folders_frame, text="Исходная папка:", font=self.font_normal).grid(
            row=1, column=0, sticky="w", **pad
        )
        self.entry_source = ctk.CTkEntry(folders_frame, font=self.font_normal, height=36)
        self.entry_source.grid(row=1, column=1, sticky="ew", **pad)
        ctk.CTkButton(folders_frame, text="Обзор...", width=100, font=self.font_normal, height=36,
                      command=self._browse_source).grid(row=1, column=2, **pad)

        ctk.CTkLabel(folders_frame, text="Папка результата:", font=self.font_normal).grid(
            row=2, column=0, sticky="w", **pad
        )
        self.entry_result = ctk.CTkEntry(folders_frame, font=self.font_normal, height=36)
        self.entry_result.grid(row=2, column=1, sticky="ew", **pad)
        ctk.CTkButton(folders_frame, text="Обзор...", width=100, font=self.font_normal, height=36,
                      command=self._browse_result).grid(row=2, column=2, **pad)

        folders_frame.grid_columnconfigure(1, weight=1)

        # ---- Метаданные ----
        meta_frame = ctk.CTkFrame(self)
        meta_frame.pack(fill="x", padx=16, pady=8)

        ctk.CTkLabel(meta_frame, text="Метаданные", font=self.font_bold).grid(
            row=0, column=0, columnspan=2, sticky="w", padx=12, pady=(10, 4)
        )

        labels_and_attrs = [
            ("Автор:", "entry_artist"),
            ("Название книги:", "entry_album"),
            ("Чтец:", "entry_album_artist"),
            ("Год:", "entry_year"),
            ("Жанр:", "entry_genre"),
        ]
        for i, (label, attr) in enumerate(labels_and_attrs, start=1):
            ctk.CTkLabel(meta_frame, text=label, font=self.font_normal).grid(row=i, column=0, sticky="w", **pad)
            entry = ctk.CTkEntry(meta_frame, font=self.font_normal, height=36)
            entry.grid(row=i, column=1, sticky="ew", **pad)
            setattr(self, attr, entry)
            if attr == "entry_year":
                ctk.CTkButton(
                    meta_frame, text="Текущий год", width=120, font=self.font_normal, height=36,
                    command=self._set_current_year,
                ).grid(row=i, column=2, padx=14, pady=7)

        self.entry_genre.insert(0, "Аудиокнига")
        self._set_current_year()

        row = len(labels_and_attrs) + 1

        ctk.CTkLabel(meta_frame, text="Начальный номер трека:", font=self.font_normal).grid(
            row=row, column=0, sticky="w", **pad
        )
        self.entry_start = ctk.CTkEntry(meta_frame, width=110, font=self.font_normal, height=36)
        self.entry_start.insert(0, "1")
        self.entry_start.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        ctk.CTkLabel(meta_frame, text="Ширина номера трека (кол-во цифр):", font=self.font_normal).grid(
            row=row, column=0, sticky="w", **pad
        )
        self.combo_width = ctk.CTkComboBox(
            meta_frame, width=110, font=self.font_normal, height=36,
            values=[str(i) for i in range(MIN_TRACK_WIDTH, MAX_TRACK_WIDTH + 1)],
        )
        self.combo_width.set("2")
        self.combo_width.grid(row=row, column=1, sticky="w", pady=(7, 13), padx=14)

        meta_frame.grid_columnconfigure(1, weight=1)

        # включаем Ctrl+A во всех текстовых полях ввода
        for entry in (
            self.entry_source, self.entry_result, self.entry_artist, self.entry_album,
            self.entry_album_artist, self.entry_year, self.entry_genre, self.entry_start,
        ):
            bind_shortcuts(entry, kind="entry")

        # ---- Кнопки управления ----
        buttons_frame = ctk.CTkFrame(self, fg_color="transparent")
        buttons_frame.pack(fill="x", padx=16, pady=8)

        self.btn_start = ctk.CTkButton(buttons_frame, text="Начать обработку", font=self.font_normal, height=40,
                                        command=self._start_processing)
        self.btn_start.pack(side="left", padx=(0, 10))

        self.btn_stop = ctk.CTkButton(
            buttons_frame, text="Остановить", font=self.font_normal, height=40, command=self._stop_processing,
            state="disabled", fg_color="#8a3b3b", hover_color="#6e2f2f",
        )
        self.btn_stop.pack(side="left", padx=10)

        self.btn_open_result = ctk.CTkButton(
            buttons_frame, text="Открыть папку результата", font=self.font_normal, height=40,
            command=self._open_result_folder
        )
        self.btn_open_result.pack(side="left", padx=10)

        # ---- Лог ----
        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(8, 16))

        ctk.CTkLabel(log_frame, text="Лог", font=self.font_bold).pack(anchor="w", padx=12, pady=(10, 4))

        self.log_box = ctk.CTkTextbox(log_frame, wrap="word", font=self.font_normal)
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")
        bind_shortcuts(self.log_box, kind="text")

    # ---------- Вспомогательные ----------

    def _browse_source(self):
        folder = filedialog.askdirectory(title="Выберите исходную папку")
        if folder:
            self.entry_source.delete(0, "end")
            self.entry_source.insert(0, folder)
            if not self.entry_result.get().strip():
                self.entry_result.delete(0, "end")
                self.entry_result.insert(0, str(Path(folder) / "result"))

    def _browse_result(self):
        folder = filedialog.askdirectory(title="Выберите папку результата")
        if folder:
            self.entry_result.delete(0, "end")
            self.entry_result.insert(0, folder)

    def _set_current_year(self):
        self.entry_year.delete(0, "end")
        self.entry_year.insert(0, str(datetime.date.today().year))

    def _open_result_folder(self):
        result_path = self.entry_result.get().strip()
        if not result_path or not Path(result_path).exists():
            messagebox.showwarning("Папка не найдена", "Папка результата ещё не создана.")
            return
        os.startfile(result_path)  # Windows

    def _log(self, text):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _log_clear(self):
        self.log_box.configure(state="normal")
        self.log_box.delete("1.0", "end")
        self.log_box.configure(state="disabled")

    # ---------- Обработка ----------

    def _validate_inputs(self):
        source = self.entry_source.get().strip()
        result = self.entry_result.get().strip()

        if not source or not Path(source).is_dir():
            messagebox.showerror("Ошибка", "Укажите существующую исходную папку.")
            return None

        if not result:
            messagebox.showerror("Ошибка", "Укажите папку результата.")
            return None

        try:
            start_number = int(self.entry_start.get().strip())
            if start_number < 0:
                raise ValueError
        except ValueError:
            messagebox.showerror("Ошибка", "Начальный номер трека должен быть неотрицательным целым числом.")
            return None

        try:
            width = int(self.combo_width.get().strip())
            if not (MIN_TRACK_WIDTH <= width <= MAX_TRACK_WIDTH):
                raise ValueError
        except ValueError:
            messagebox.showerror(
                "Ошибка",
                f"Ширина номера трека должна быть целым числом от {MIN_TRACK_WIDTH} до {MAX_TRACK_WIDTH}.",
            )
            return None

        return {
            "source": Path(source),
            "result": Path(result),
            "artist": self.entry_artist.get().strip(),
            "album": self.entry_album.get().strip(),
            "album_artist": self.entry_album_artist.get().strip(),
            "year": self.entry_year.get().strip(),
            "genre": self.entry_genre.get().strip() or "Аудиокнига",
            "start_number": start_number,
            "width": width,
        }

    def _start_processing(self):
        settings = self._validate_inputs()
        if settings is None:
            return

        self.stop_event.clear()
        self._log_clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        self.worker_thread = threading.Thread(target=self._run_processing, args=(settings,), daemon=True)
        self.worker_thread.start()

    def _stop_processing(self):
        self.stop_event.set()
        self._log("Остановка запрошена, завершаю текущий файл...")

    def _run_processing(self, settings):
        source_dir = settings["source"]
        result_dir = settings["result"]

        result_dir.mkdir(parents=True, exist_ok=True)

        mp3_files = sorted(source_dir.glob("*.mp3"))
        if not mp3_files:
            self._log("В исходной папке не найдено mp3 файлов!")
            self._finish()
            return

        total = len(mp3_files)
        self._log(f"Найдено файлов: {total}")

        processed = 0
        for offset, mp3_file in enumerate(mp3_files):
            if self.stop_event.is_set():
                self._log("Обработка остановлена пользователем.")
                break

            index = settings["start_number"] + offset
            self._log(f"\n[{offset + 1}/{total}] {mp3_file.name}")

            result_file = result_dir / mp3_file.name
            try:
                shutil.copy2(mp3_file, result_file)
                self._log("  Скопирован")

                if self._apply_tags(result_file, index, total, settings):
                    self._log("  Теги применены")
                    processed += 1
                else:
                    self._log("  Ошибка при применении тегов")
            except Exception as e:
                self._log(f"  Ошибка при обработке файла: {e}")

        self._log(f"\nОбработка завершена. Успешно: {processed} из {total}")
        self._finish()

    def _apply_tags(self, file_path, track_number, total_tracks, settings):
        try:
            audio = MP3(file_path, ID3=ID3)
            try:
                audio.add_tags()
            except Exception:
                pass

            width = settings["width"]
            track_str = f"{track_number:0{width}d}"
            total_str = f"{total_tracks:0{width}d}" if total_tracks > 0 else ""
            track_info = f"{track_str}/{total_str}" if total_str else track_str

            audio["TRCK"] = TRCK(encoding=3, text=track_info)

            audio["TIT2"] = TIT2(encoding=3, text=f"Глава {track_str}")

            if settings["artist"]:
                audio["TPE1"] = TPE1(encoding=3, text=settings["artist"])
            if settings["album"]:
                audio["TALB"] = TALB(encoding=3, text=settings["album"])
            if settings["album_artist"]:
                audio["TPE2"] = TPE2(encoding=3, text=settings["album_artist"])
            if settings["year"]:
                audio["TDRC"] = TDRC(encoding=3, text=settings["year"])
            audio["TCON"] = TCON(encoding=3, text=settings["genre"])

            audio.save()
            return True
        except Exception as e:
            self._log(f"  Ошибка тегирования: {e}")
            return False

    def _finish(self):
        self.btn_start.configure(state="normal")
        self.btn_stop.configure(state="disabled")


if __name__ == "__main__":
    app = AudiobookTaggerApp()
    app.mainloop()