import os
import shutil
import threading
import datetime
from pathlib import Path

import customtkinter as ctk
from tkinter import filedialog, messagebox

from mutagen.mp3 import MP3
from mutagen.wave import WAVE
from mutagen.id3 import ID3, TIT2, TPE1, TALB, TPE2, TDRC, TRCK, TCON

from dataclasses import dataclass, field

# Поддерживаемые форматы аудиофайлов (расширения в нижнем регистре)
AUDIO_EXTENSIONS = (".mp3", ".wav")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

MIN_TRACK_WIDTH = 1
MAX_TRACK_WIDTH = 8  # максимум 7 ведущих нулей

# Виртуальные коды клавиш A / C / X / V (Windows VK-коды, они совпадают с ASCII-кодами
# букв и НЕ зависят от текущей раскладки клавиатуры — в отличие от keysym, который при
# кириллической раскладке превращается в "с", "в" и т.д. и не совпадает с "c", "v").
_CTRL_KEYCODES = {65: "select_all", 67: "copy", 88: "cut", 86: "paste"}


@dataclass
class Range:
    prefix: str = ""
    start: int = 1
    end: int = 1  # абсолютный номер последнего трека


@dataclass
class RangeSettings:
    enabled: bool = False
    ranges: list[Range] = field(default_factory=list)

    def locate(self, absolute_track: int):
        """
        Куда попадает трек с абсолютным номером.
        Возвращает (номер_главы_внутри_диапазона, индекс_диапазона, префикс).
        Если ни в один диапазон не попал → (absolute_track, -1, "").
        """
        for idx, r in enumerate(self.ranges):
            if r.start <= absolute_track <= r.end:
                return absolute_track - r.start + 1, idx, r.prefix
        return absolute_track, -1, ""


def build_track_title(
    absolute_track: int, settings: RangeSettings, width: int = 2
) -> str:
    """
    Строит TIT2 для трека:
      - если разбиение выключено или трек вне диапазонов → "Глава N"
      - если внутри диапазона → "Глава K", где K = позиция внутри диапазона
      - если K == 1 и есть префикс → "Префикс Глава K"
    """
    chapter, range_idx, prefix = settings.locate(absolute_track)
    chapter_str = f"{chapter:0{width}d}"
    title = f"Глава {chapter_str}"
    if range_idx >= 0 and prefix and chapter == 1:
        title = f"{prefix} {title}"
    return title


def find_audio_files(source_dir: Path) -> list[Path]:
    """
    Ищет все поддерживаемые аудиофайлы (mp3, wav) в папке, без учёта регистра
    расширения. Path.glob чувствителен к регистру на некоторых системах, поэтому
    фильтруем сами через iterdir() + suffix.lower(), а не плодим отдельные glob()
    на каждый вариант регистра (что дало бы дубликаты на Windows).
    """
    files = [
        p
        for p in source_dir.iterdir()
        if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
    ]
    return sorted(files)


def bind_shortcuts(widget, kind="entry"):
    """
    Включает Ctrl+A/C/X/V для CTkEntry / CTkTextbox независимо от раскладки клавиатуры.
    Стандартные tk-биндинги завязаны на keysym, который при русской раскладке перестаёт
    совпадать с латинскими 'a'/'c'/'x'/'v' — из-за этого горячие клавиши "не работали".
    Здесь распознаём клавишу по keycode (физической клавише), это раскладко-независимо.
    """
    target = (
        getattr(widget, "_entry", None) or getattr(widget, "_textbox", None) or widget
    )

    def on_key(event):
        # 0x4 — бит модификатора Control в event.state
        if not (event.state & 0x4):
            return None

        keysym = (event.keysym or "").lower()
        action = _CTRL_KEYCODES.get(event.keycode)
        if action is None:
            # запасной путь для раскладок/платформ, где keysym остаётся латинским
            action = {"a": "select_all", "c": "copy", "x": "cut", "v": "paste"}.get(
                keysym
            )
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


class RangeDialog(ctk.CTkToplevel):
    MIN_RANGES = 1
    MAX_RANGES = 100

    def __init__(self, master, initial: RangeSettings, on_save, total_tracks: int = 0):
        super().__init__(master)

        self._app = master  # чтобы брать шрифты главного окна
        self._on_save = on_save
        self._total_tracks = total_tracks

        # Список актуальных "переменных" каждой строки.
        # Храним ИМЕННО StringVar, но только пока живы виджеты —
        # при пересборке мы их уничтожим и создадим новые.
        self._row_vars: list[tuple[ctk.StringVar, ctk.StringVar, ctk.StringVar]] = []

        self.title("Разбиение на диапазоны")
        self.geometry("760x560")
        self.minsize(560, 400)  # окно ресайзится — это требование

        self._build(initial)

        # модальность + фокус (см. пояснение в прошлом ответе)
        self.transient(master)
        self.grab_set()
        self.after(200, self.lift)
        self.after(200, self.focus_force)

    # ---------- построение интерфейса ----------

    def _build(self, initial: RangeSettings):
        pad = {"padx": 14, "pady": 8}

        # --- Верх: галочка + количество + подсказка ---
        top = ctk.CTkFrame(self, fg_color="transparent")
        top.pack(fill="x", padx=14, pady=(14, 4))

        self.var_enabled = ctk.BooleanVar(value=initial.enabled)
        ctk.CTkCheckBox(
            top,
            text="Применять разбиение на диапазоны",
            variable=self.var_enabled,
            font=self._app.font_normal,
        ).pack(side="left")

        if self._total_tracks:
            ctk.CTkLabel(
                top,
                text=f"Всего треков: {self._total_tracks}",
                font=self._app.font_normal,
                text_color="gray",
            ).pack(side="right")

        # --- Вторая строка: количество диапазонов ---
        cnt = ctk.CTkFrame(self, fg_color="transparent")
        cnt.pack(fill="x", padx=14, pady=(0, 6))

        ctk.CTkLabel(
            cnt, text="Количество диапазонов:", font=self._app.font_normal
        ).pack(side="left")

        # Стартовое число диапазонов — сколько уже сохранено (минимум 1)
        start_n = max(self.MIN_RANGES, len(initial.ranges))
        self.var_count = ctk.StringVar(value=str(start_n))
        # trace_add вызывается на КАЖДОЕ изменение; там мы фильтруем промежуточные
        # состояния ("", "1", "10" при наборе "10" с нуля и т.п.)
        self.var_count.trace_add("write", self._on_count_changed)

        ctk.CTkEntry(
            cnt,
            textvariable=self.var_count,
            width=80,
            font=self._app.font_normal,
            height=34,
        ).pack(side="left", padx=8)

        ctk.CTkLabel(
            cnt,
            text=f"(от {self.MIN_RANGES} до {self.MAX_RANGES})",
            font=self._app.font_normal,
            text_color="gray",
        ).pack(side="left")

        # --- Шапка таблицы (вне скролла, чтобы всегда была видна) ---
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.pack(fill="x", padx=(14, 30), pady=(4, 4))  # справа запас под скроллбар
        ctk.CTkLabel(header, text="№", width=30, font=self._app.font_bold).pack(
            side="left", padx=4
        )
        ctk.CTkLabel(header, text="Префикс", anchor="w", font=self._app.font_bold).pack(
            side="left", fill="x", expand=True, padx=4
        )
        ctk.CTkLabel(header, text="Начало", width=70, font=self._app.font_bold).pack(
            side="left", padx=4
        )
        ctk.CTkLabel(header, text="Конец", width=70, font=self._app.font_bold).pack(
            side="left", padx=4
        )

        # --- Прокручиваемая область под строки ---
        # fill="both", expand=True → растёт вместе с окном (требование)
        self.rows_frame = ctk.CTkScrollableFrame(self)
        self.rows_frame.pack(fill="both", expand=True, padx=14, pady=(0, 8))

        # --- Кнопки снизу ---
        btns = ctk.CTkFrame(self, fg_color="transparent")
        btns.pack(fill="x", padx=14, pady=(0, 14))
        ctk.CTkButton(
            btns,
            text="Сохранить",
            height=38,
            font=self._app.font_normal,
            command=self._save,
        ).pack(side="right")
        ctk.CTkButton(
            btns,
            text="Отмена",
            height=38,
            font=self._app.font_normal,
            fg_color="#555",
            hover_color="#444",
            command=self.destroy,
        ).pack(side="right", padx=(0, 8))

        # Собрать строки: если настроек ещё нет — одну пустую
        self._rebuild_rows(start_n, initial.ranges if initial.ranges else None)

    # ---------- реакция на смену количества ----------

    def _on_count_changed(self, *_):
        s = self.var_count.get().strip()
        if not s.isdigit():
            return  # промежуточное состояние при наборе
        n = int(s)
        if not (self.MIN_RANGES <= n <= self.MAX_RANGES):
            return  # вне допустимого — не реагируем
        if n == len(self._row_vars):
            return  # ничего не изменилось
        self._rebuild_rows(n)

    # ---------- чтение/пересборка строк ----------

    def _read_rows(self) -> list[tuple[str, str, str]]:
        """Значения всех полей в виде простых строк. Пока виджеты живы."""
        return [(pv.get(), sv.get(), ev.get()) for pv, sv, ev in self._row_vars]

    def _rebuild_rows(self, n: int, initial_list=None):
        # 1) снять текущие значения — ПОКА старые виджеты живы
        current = self._read_rows()

        # 2) первый запуск: берём initial, если он есть
        if initial_list is not None and not current:
            current = [(r.prefix, str(r.start), str(r.end)) for r in initial_list]

        # 3) дополнить умными дефолтами (последний известный end + 1)
        last_valid_end = 0
        for _, s, e in current:
            try:
                last_valid_end = max(last_valid_end, int(e))
            except (ValueError, TypeError):
                pass
        while len(current) < n:
            default_start = str(last_valid_end + 1) if last_valid_end else ""
            current.append(("", default_start, ""))

        # 4) обрезать, если стало меньше
        current = current[:n]

        # 5) уничтожить старые виджеты и очистить список
        for w in self.rows_frame.winfo_children():
            w.destroy()
        self._row_vars.clear()

        # 6) создать новые
        for i, (p, s, e) in enumerate(current):
            row = ctk.CTkFrame(self.rows_frame, fg_color="transparent")
            row.pack(fill="x", pady=2)

            ctk.CTkLabel(
                row, text=str(i + 1), width=30, font=self._app.font_normal
            ).pack(side="left", padx=4)

            pv = ctk.StringVar(value=p)
            sv = ctk.StringVar(value=s)
            ev = ctk.StringVar(value=e)

            ctk.CTkEntry(
                row,
                textvariable=pv,
                height=32,
                font=self._app.font_normal,
            ).pack(side="left", fill="x", expand=True, padx=4)
            ctk.CTkEntry(
                row,
                textvariable=sv,
                width=70,
                height=32,
                font=self._app.font_normal,
            ).pack(side="left", padx=4)
            ctk.CTkEntry(
                row,
                textvariable=ev,
                width=70,
                height=32,
                font=self._app.font_normal,
            ).pack(side="left", padx=4)

            self._row_vars.append((pv, sv, ev))

    # ---------- сохранение ----------

    def _save(self):
        ranges: list[Range] = []

        for i, (pv, sv, ev) in enumerate(self._row_vars):
            prefix = pv.get().strip()
            try:
                start = int(sv.get().strip())
                end = int(ev.get().strip())
            except ValueError:
                messagebox.showerror(
                    "Ошибка",
                    f"Диапазон {i + 1}: начало и конец должны быть целыми числами.",
                    parent=self,
                )
                return
            if start < 1 or end < start:
                messagebox.showerror(
                    "Ошибка",
                    f"Диапазон {i + 1}: некорректные границы ({start}–{end}).",
                    parent=self,
                )
                return
            ranges.append(Range(prefix=prefix, start=start, end=end))

        # мягкая проверка на пересечения — только предупреждаем
        srt = sorted(ranges, key=lambda r: r.start)
        for a, b in zip(srt, srt[1:]):
            if b.start <= a.end:
                if not messagebox.askyesno(
                    "Пересечение диапазонов",
                    f"Диапазоны [{a.start}–{a.end}] и [{b.start}–{b.end}] пересекаются.\n"
                    "Будет использован первый подходящий.\nПродолжить?",
                    parent=self,
                ):
                    return
                break

        # собираем чистый Python-объект и отдаём наружу
        self._on_save(RangeSettings(enabled=self.var_enabled.get(), ranges=ranges))
        self.destroy()


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
        self.range_settings = RangeSettings()  # по умолчанию выключено

    # ---------- UI ----------

    def _change_appearance(self, choice):
        mode = "Dark" if choice == "Тёмная" else "Light"
        ctk.set_appearance_mode(mode)

    def _build_ui(self):
        pad = {"padx": 14, "pady": 7}

        # ---- Заголовок + переключатель темы ----
        top_frame = ctk.CTkFrame(self, fg_color="transparent")
        top_frame.pack(fill="x", padx=16, pady=(16, 0))

        ctk.CTkLabel(
            top_frame, text="Аудиокнига — обработчик тегов", font=self.font_header
        ).pack(side="left")

        self.theme_switch = ctk.CTkSegmentedButton(
            top_frame,
            values=["Тёмная", "Светлая"],
            command=self._change_appearance,
            font=self.font_normal,
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
        self.entry_source = ctk.CTkEntry(
            folders_frame, font=self.font_normal, height=36
        )
        self.entry_source.grid(row=1, column=1, sticky="ew", **pad)
        ctk.CTkButton(
            folders_frame,
            text="Обзор...",
            width=100,
            font=self.font_normal,
            height=36,
            command=self._browse_source,
        ).grid(row=1, column=2, **pad)

        ctk.CTkLabel(
            folders_frame, text="Папка результата:", font=self.font_normal
        ).grid(row=2, column=0, sticky="w", **pad)
        self.entry_result = ctk.CTkEntry(
            folders_frame, font=self.font_normal, height=36
        )
        self.entry_result.grid(row=2, column=1, sticky="ew", **pad)
        ctk.CTkButton(
            folders_frame,
            text="Обзор...",
            width=100,
            font=self.font_normal,
            height=36,
            command=self._browse_result,
        ).grid(row=2, column=2, **pad)


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
            ctk.CTkLabel(meta_frame, text=label, font=self.font_normal).grid(
                row=i, column=0, sticky="w", **pad
            )
            entry = ctk.CTkEntry(meta_frame, font=self.font_normal, height=36)
            entry.grid(row=i, column=1, sticky="ew", **pad)
            setattr(self, attr, entry)
            if attr == "entry_year":
                ctk.CTkButton(
                    meta_frame,
                    text="Текущий год",
                    width=120,
                    font=self.font_normal,
                    height=36,
                    command=self._set_current_year,
                ).grid(row=i, column=2, padx=14, pady=7)

        self.entry_genre.insert(0, "Аудиокнига")
        self._set_current_year()

        row = len(labels_and_attrs) + 1

        ctk.CTkLabel(
            meta_frame, text="Начальный номер трека:", font=self.font_normal
        ).grid(row=row, column=0, sticky="w", **pad)
        self.entry_start = ctk.CTkEntry(
            meta_frame, width=110, font=self.font_normal, height=36
        )
        self.entry_start.insert(0, "1")
        self.entry_start.grid(row=row, column=1, sticky="w", **pad)
        row += 1

        ctk.CTkLabel(
            meta_frame, text="Ширина номера трека (кол-во цифр):", font=self.font_normal
        ).grid(row=row, column=0, sticky="w", **pad)
        self.combo_width = ctk.CTkComboBox(
            meta_frame,
            width=110,
            font=self.font_normal,
            height=36,
            values=[str(i) for i in range(MIN_TRACK_WIDTH, MAX_TRACK_WIDTH + 1)],
        )
        self.combo_width.set("2")
        self.combo_width.grid(row=row, column=1, sticky="w", pady=(7, 13), padx=14)

        meta_frame.grid_columnconfigure(1, weight=1)

        # включаем Ctrl+A во всех текстовых полях ввода
        for entry in (
            self.entry_source,
            self.entry_result,
            self.entry_artist,
            self.entry_album,
            self.entry_album_artist,
            self.entry_year,
            self.entry_genre,
            self.entry_start,
        ):
            bind_shortcuts(entry, kind="entry")

        # ---- Кнопки управления ----
        buttons_frame = ctk.CTkFrame(self, fg_color="transparent")
        buttons_frame.pack(fill="x", padx=16, pady=8)

        ctk.CTkButton(
            buttons_frame, text="Разбиение на диапазоны…",
            font=self.font_normal, height=40,
            command=self._open_ranges,
        ).pack(side="left", padx=10)


        self.btn_start = ctk.CTkButton(
            buttons_frame,
            text="Начать обработку",
            font=self.font_normal,
            height=40,
            command=self._start_processing,
        )
        self.btn_start.pack(side="left", padx=(0, 10))

        self.btn_stop = ctk.CTkButton(
            buttons_frame,
            text="Остановить",
            font=self.font_normal,
            height=40,
            command=self._stop_processing,
            state="disabled",
            fg_color="#8a3b3b",
            hover_color="#6e2f2f",
        )
        self.btn_stop.pack(side="left", padx=10)

        self.btn_open_result = ctk.CTkButton(
            buttons_frame,
            text="Открыть папку результата",
            font=self.font_normal,
            height=40,
            command=self._open_result_folder,
        )
        self.btn_open_result.pack(side="left", padx=10)

        # ---- Лог ----
        log_frame = ctk.CTkFrame(self)
        log_frame.pack(fill="both", expand=True, padx=16, pady=(8, 16))

        ctk.CTkLabel(log_frame, text="Лог", font=self.font_bold).pack(
            anchor="w", padx=12, pady=(10, 4)
        )

        self.log_box = ctk.CTkTextbox(log_frame, wrap="word", font=self.font_normal)
        self.log_box.pack(fill="both", expand=True, padx=12, pady=(0, 12))
        self.log_box.configure(state="disabled")
        bind_shortcuts(self.log_box, kind="text")

    # ---------- Вспомогательные ----------

    def _open_ranges(self):
        RangeDialog(
            master=self,
            initial=self.range_settings,
            on_save=self._on_ranges_saved,
            total_tracks=0,  # можно подставить len(find_audio_files(source)) при желании
        )

    def _on_ranges_saved(self, settings: RangeSettings):
        self.range_settings = settings  # просто заменяем ссылку — этого достаточно
        if settings.enabled:
            self._log(f"Разбиение включено: {len(settings.ranges)} диапазон(ов)")
        else:
            self._log("Разбиение отключено")

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
            messagebox.showwarning(
                "Папка не найдена", "Папка результата ещё не создана."
            )
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
            messagebox.showerror(
                "Ошибка",
                "Начальный номер трека должен быть неотрицательным целым числом.",
            )
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
        settings["range_settings"] = self.range_settings

        self.stop_event.clear()
        self._log_clear()
        self.btn_start.configure(state="disabled")
        self.btn_stop.configure(state="normal")

        self.worker_thread = threading.Thread(
            target=self._run_processing, args=(settings,), daemon=True
        )
        self.worker_thread.start()

    def _stop_processing(self):
        self.stop_event.set()
        self._log("Остановка запрошена, завершаю текущий файл...")

    def _run_processing(self, settings):
        source_dir = settings["source"]
        result_dir = settings["result"]

        result_dir.mkdir(parents=True, exist_ok=True)

        audio_files = find_audio_files(source_dir)
        if not audio_files:
            self._log("В исходной папке не найдено mp3/wav файлов!")
            self._finish()
            return

        total = len(audio_files)
        self._log(f"Найдено файлов: {total}")

        processed = 0
        for offset, audio_file in enumerate(audio_files):
            if self.stop_event.is_set():
                self._log("Обработка остановлена пользователем.")
                break

            index = settings["start_number"] + offset
            self._log(f"\n[{offset + 1}/{total}] {audio_file.name}")

            result_file = result_dir / audio_file.name
            try:
                shutil.copy2(audio_file, result_file)
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
            suffix = file_path.suffix.lower()
            if suffix == ".mp3":
                audio = MP3(file_path, ID3=ID3)
            elif suffix == ".wav":
                # WAVE-файлы тоже поддерживают ID3-теги (в чанке "id3 "),
                # интерфейс у mutagen тот же: add_tags()/dict-style/save()
                audio = WAVE(file_path)
            else:
                self._log(f"  Неподдерживаемый формат файла: {suffix}")
                return False

            try:
                audio.add_tags()
            except Exception:
                pass

            width = settings["width"]
            track_str = f"{track_number:0{width}d}"
            total_str = f"{total_tracks:0{width}d}" if total_tracks > 0 else ""
            audio["TRCK"] = TRCK(
                encoding=3, text=f"{track_str}/{total_str}" if total_str else track_str
            )

            # ---- TIT2: с учётом разбиения на диапазоны ----
            rs: RangeSettings = settings["range_settings"]
            if rs.enabled and rs.ranges:
                title_text = build_track_title(track_number, rs, width)
            else:
                title_text = f"Глава {track_str}"
            audio["TIT2"] = TIT2(encoding=3, text=title_text)

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