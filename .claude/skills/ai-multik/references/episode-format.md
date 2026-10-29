# Формат episode.json

Полный рабочий пример — `templates/palata-s-byvshey/episode.json` (эталон, разобранный покадрово).

## Верхний уровень

```jsonc
{
  "id": "palata-s-byvshey",              // имя выходного файла
  "series": "ЧТО ЕСЛИ ТЫ...",            // шапка слева сверху
  "episode": "ПАЛАТА С БЫВШЕЙ",          // после точки в шапке
  "tag": "стены были белые",             // название-эпитафия: таблетка под CTA
  "voice": {"engine": "rhvoice", "voice": "artemiy", "tempo": 1.18, "gap": 0.05},
  "hud": [{"label": "ДЕНЬ", "value": "1"}, {"label": "БЕЛЫХ СТЕН", "value": "4"}],
  "title_card": {"kicker": "ты в старости", "lines": ["С *БЫВШЕЙ*", "В ДУРКЕ"], "sub": "стены были белые"},
  "cta": "Отправь тому, с кем хотел бы так провести старость",   // плашка на последнем шоте
  "characters": {"he": "...", "she": "..."},  // описания для промптов картинок (рендер их не читает)
  "caption_words": 3,      // макс. слов в куске субтитров
  "caption_y": 0.835,      // высота субтитров (доля кадра)
  "ai_label": true,        // метка AI-generated
  "mix": {"voice": 1.0, "sfx": 1.0},
  "music": {"file": "music.mp3", "vol": 0.12, "duck": 0.35},   // необязательно
  "shots": [ ... ]
}
```

`*слово*` в `title_card.lines` и в тексте плашек — жёлтая подсветка.

## Шот

```jsonc
{
  "image": "img/05.png",          // кадр 9:16; нет файла — рисуется заглушка с номером шота и prompt
  "prompt": "extreme close-up...", // что генерировать (для заглушки и для тебя)
  "lines": ["Это твоя бывшая. Та самая,"],  // реплики диктора; длина шота = длина голоса
  "motion": "shake",              // zoom_in | zoom_out | pan_left | pan_right | pan_up | pan_down | punch | shake | bounce | static
  "focus": [0.5, 0.4],            // точка, к которой едет камера (доли кадра)
  "zoom": 1.0,                    // доп. множитель крупности
  "fx": ["sepia"],                // sepia | vignette | desat | warm | bright
  "transition": "flash",          // cut (по умолч.) | whip | flash
  "hud": {"ДЕНЬ": "3"},           // новые значения HUD с этого шота (мигнут + щелчок)
  "stickers": [ ... ],
  "sfx": [{"name": "splat", "at": 1.6, "vol": 0.7}],  // at — секунды от начала шота
  "lead": 0.0,                    // пауза до первой реплики
  "tail": 0.12,                   // хвост после последней реплики
  "dur": 2.0,                     // минимальная длина (для шота без реплик)
  "clean": false,                 // true — без шапки и HUD (полноэкранная вставка)
  "no_particles": false
}
```

### Цензура в репликах

- `{о****л}` — в титрах «О****Л», в звуке писк на месте слова, само слово не произносится.
- `{г****й|грязью}` — в титрах звёздочки, диктор говорит «грязью», поверх писк. Удобно, когда слово нужно для ритма.

### Стикер

```jsonc
{"type": "stamp", "text": "БЫВШАЯ", "pos": [0.5, 0.25], "at_word": 2}
```

Общие поля: `pos` [x, y] доли кадра (центр стикера; рендер не даст вылезти за край), `at` (сек от начала шота) **или** `at_word` (номер слова в репликах шота, с 0 — стикер появится ровно на нём), `dur` (сколько держать; по умолчанию до конца шота), `anim` (`pop` | `slam` | `drop` | `fade`), `wobble`, `rotate`, `sfx` (имя звука или `null`), `sfx_vol`.

| type | Поля |
|---|---|
| `big` | `text` (`\n` — перенос), `size` (150), `color` |
| `stamp` / `label` / `box` | `text`, `style` (`stamp_red`, `orange`, `white_tag`, `sepia`, `red_outline`, `yellow`, `dark`, `green`), `kicker` (мелкая строка сверху), `size` (62) |
| `bubble` | `text`, `strike` (зачеркнуть), `tail` (`left`/`right`), `image` |
| `thought` | `text` или `image` (+`image_w`) |
| `list` | `title`, `items`, `reveal` (по одному), `step` (0.35 с), `width` |
| `polaroid` | `image`, `caption` (рукописная), `name` (печатная), `note` (бирка снизу), `width` |
| `calendar` | `from`, `to`, `flip_at` (сек от появления), `header` |
| `check` | `size` |
| `clipboard` | `text` (пишется по буквам), `cps` (букв в секунду), `title` |
| `image` | `image` (PNG с прозрачностью), `width` |

## Команды

```bash
python3 .claude/skills/ai-multik/scripts/render.py multiki/<id>/episode.json --preview          # 540x960, 15 к/с — проверка тайминга
python3 .claude/skills/ai-multik/scripts/render.py multiki/<id>/episode.json --still 0.5 12 31  # отдельные кадры в build/
python3 .claude/skills/ai-multik/scripts/render.py multiki/<id>/episode.json                    # финал 1080x1920 30 к/с
python3 .claude/skills/ai-multik/scripts/voice.py  multiki/<id>/episode.json                    # только озвучка + длительности реплик
```

Результат: `multiki/<id>/build/<id>.mp4`, обложка `build/cover.png` (первый кадр с титулом), голос в `build/voice/` (кэшируется — перезапуск быстрый, пересинтезируются только изменённые реплики).
