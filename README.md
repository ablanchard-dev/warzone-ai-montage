# Warzone AI Montage

> Automatically builds a highlight montage from a folder of **Call of Duty: Warzone**
> clips, combining computer vision (HUD kill detection), audio analysis and speech
> transcription.

![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![OpenCV](https://img.shields.io/badge/OpenCV-template%20matching-5C3EE8?logo=opencv&logoColor=white)
![FFmpeg](https://img.shields.io/badge/FFmpeg-render-007808?logo=ffmpeg&logoColor=white)
![License](https://img.shields.io/badge/License-MIT-green)

Point it at a folder of clips/VODs and it finds the real highlights (multikills,
2v1/3v1, squad wipes, victories, proximity-chat moments), keeps the best across all
videos, and edits a 30 s–2 min clip: voices kept up front, music underneath, cuts
synced to the beat.

## Demo

![Demo — automatically generated montage](docs/demo.gif)

Produced with no manual editing: kills detected on the HUD, selected and assembled by the program.

## How it works — 3 fused signals

| Signal | Method | Role |
|---|---|---|
| HUD vision | Template matching (OpenCV) of the kill / knock / elimination icon that flashes on screen | Reliable signal: detects kills independently of sound |
| Action density | Temporal clustering of nearby kills | Multikill / 2v1 / 3v1 / wipe → high score |
| Voice / prox chat | Whisper transcription + audio peaks | Boosts when a voice lands right before a kill (last words) or right after (reactions); victory detected via OCR |

The three signals are scored together, the best moments are kept, with an adaptive
clip length (a short no-scope, a long clutch) and the victory as the closer.

```
   clips/ (multiple VODs)
        |
        v
 [ vision.py ]   [ audio.py ]   [ killdetect.py ]
  HUD template    peaks + voice   kill counter
        \_____________|_______________/
                      v
                [ scoring.py ]   scoring + global selection
                      v
                [ montage.py ]   beat-synced cuts + ffmpeg render
                      v
                 montage.mp4
```

## Stack

- Python — modular pipeline (`wzmontage/`)
- OpenCV — kill detection via HUD template matching
- librosa / soundfile — audio action-peak analysis
- faster-whisper (optional) — prox-chat transcription
- pytesseract (optional) — victory-screen OCR
- FFmpeg — cutting, beat-sync and final render

## System requirements

- ffmpeg + ffprobe (required)
- tesseract (optional, victory detection)

```bash
sudo apt install ffmpeg tesseract-ocr        # Linux
brew install ffmpeg tesseract                # macOS
# Windows: winget install Gyan.FFmpeg
```

## Installation

```bash
pip install -r requirements.txt
pip install faster-whisper   # optional: voice + subtitles
pip install pytesseract      # optional: victory detection
```

## Usage

```bash
# Montage from a folder of clips + music
python main.py ./clips -m music.mp3 -o montage.mp4

# Without vision (if templates not created yet): audio + voice
python main.py ./clips -m music.mp3 --no-vision

# Without voice transcription (faster)
python main.py ./clips -m music.mp3 --no-voice
```

Vertical TikTok format: `width: 1080 / height: 1920` in `config.yaml`.
Burned-in prox-chat subtitles: `output.subtitles: true` (Whisper required).

The pipeline runs out of the box with audio + voice. Vision-based kill detection
turns on once the templates are created (below) and noticeably improves the selection.

## Calibrating the kill templates

The kill icon depends on your resolution / HUD, so you capture it from your own clips, once.

```bash
# 1) Frame the area around the icon (check preview.png):
python calibrate.py clip.mp4 -t 73.5 -r 0.42 0.46 0.06 0.06

# 2) Save the template:
python calibrate.py clip.mp4 -t 73.5 -r 0.42 0.46 0.06 0.06 --save-template templates/knock.png
```

Create `templates/knock.png`, `templates/elim.png`, `templates/kill.png`, then set
the search area in `config.yaml > vision.search_region` (and `victory_region` for the #1 banner).

Templates are setup-specific: they are not versioned (`.gitignore`); everyone generates their own.

## Useful settings (`config.yaml`)

| Setting | Effect |
|---|---|
| `vision.threshold` | Lower = detects more kills (and more false positives) |
| `scoring.multikill_multiplier` / `wipe_multiplier` | Weight of big chains |
| `scoring.voice_kill_multiplier` | Importance of "last words" moments |
| `editing.beat_sync` | Aligns cuts to the music tempo |
| `editing.music_volume` / `game_audio_volume` | Music / voice balance |
| `editing.max_total_seconds` | Max montage length |
| `output.subtitles` | Burns in the prox-chat text |

## Architecture (`wzmontage/`)

| Module | Responsibility |
|---|---|
| `vision.py` | Template matching of the kill icon on the HUD |
| `killdetect.py` | Automatic kill detection via the on-screen counter (no calibration) |
| `audio.py` | Action peaks + spoken-segment detection |
| `scoring.py` | Moment scoring + global multi-clip selection |
| `montage.py` | Beat-synced cuts + FFmpeg assembly |
| `models.py` / `utils.py` | Shared types + helpers (ffprobe, I/O) |

## Limitations

- Single audio track: voice is detected but enemy / team can't be separated (the transcript helps in part).
- Templates are resolution-dependent: recreate them if you change settings.
- Whisper on game audio can produce imperfect transcriptions.
- This is a solid automatic first pass, to be refined by hand for polished content.
- For other players' clips: mind the rights on the source videos.

## Roadmap

- "Pure" 1vX via reading the HUD squad counter
- YOLOv8 model trained on the kill feed (alternative to templates)
- Speed-ramp / zoom + SFX on the kill frame
- Other games (Apex, Fortnite…) via the same modular pipeline

## License

MIT — see [`LICENSE`](LICENSE).
