"""Tests des utilitaires (wzmontage.utils)."""
from wzmontage.utils import VIDEO_EXTS, list_videos


def test_video_exts_contains_common_formats():
    for ext in (".mp4", ".mkv", ".mov", ".avi", ".webm"):
        assert ext in VIDEO_EXTS


def test_list_videos_single_file(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"x")
    assert list_videos(f) == [f]


def test_list_videos_filters_non_video(tmp_path):
    (tmp_path / "a.mp4").write_bytes(b"x")
    (tmp_path / "b.txt").write_text("nope")
    (tmp_path / "c.mov").write_bytes(b"x")
    result = list_videos(tmp_path)
    names = {p.name for p in result}
    assert names == {"a.mp4", "c.mov"}


def test_list_videos_is_case_insensitive(tmp_path):
    (tmp_path / "UPPER.MP4").write_bytes(b"x")
    result = list_videos(tmp_path)
    assert len(result) == 1
    assert result[0].name == "UPPER.MP4"


def test_list_videos_recursive(tmp_path):
    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "deep.mkv").write_bytes(b"x")
    (tmp_path / "top.mp4").write_bytes(b"x")
    result = list_videos(tmp_path)
    assert {p.name for p in result} == {"deep.mkv", "top.mp4"}


def test_list_videos_sorted(tmp_path):
    for name in ("c.mp4", "a.mp4", "b.mp4"):
        (tmp_path / name).write_bytes(b"x")
    result = list_videos(tmp_path)
    assert [p.name for p in result] == ["a.mp4", "b.mp4", "c.mp4"]


def test_list_videos_empty_dir(tmp_path):
    assert list_videos(tmp_path) == []
