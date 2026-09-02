"""Phase 3.5C: emotion_style seed-reproducibility + micro variation sanity."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from director import emotion_style


def test_emotion_style_reproducible_with_seed():
    r1 = emotion_style("happy", 0.6, seed=42)
    r2 = emotion_style("happy", 0.6, seed=42)
    assert r1 == r2


def test_emotion_style_differs_across_seeds():
    a = emotion_style("happy", 0.6, seed=1)
    b = emotion_style("happy", 0.6, seed=999)
    assert a != b


def test_emotion_style_backward_compatible_call():
    res = emotion_style("sad")
    assert len(res) == 3
