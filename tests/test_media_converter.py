import unittest
import sys
import types

try:
    import numpy  # noqa: F401
except ImportError:
    sys.modules['numpy'] = types.ModuleType('numpy')

try:
    from PIL import Image  # noqa: F401
except ImportError:
    pil_module = types.ModuleType('PIL')
    pil_module.Image = object()
    sys.modules['PIL'] = pil_module

from backend.core.media_converter import (
    _build_frame_durations_ms,
    _select_frame_step,
    _source_duration_ms,
    _source_frame_timestamp_ms,
)


class MediaConverterTimingTests(unittest.TestCase):
    def test_frame_budget_uses_ceil_step_to_cover_full_timeline(self):
        step = _select_frame_step(
            src_fps=30.0,
            target_fps=30,
            total_frames=300,
            max_frames=120,
            unlimited=False,
        )
        self.assertEqual(step, 3)

    def test_source_duration_is_preserved_in_frame_durations(self):
        timestamps = [
            _source_frame_timestamp_ms(0, 30.0),
            _source_frame_timestamp_ms(3, 30.0),
            _source_frame_timestamp_ms(6, 30.0),
        ]
        durations = _build_frame_durations_ms(
            frame_timestamps_ms=timestamps,
            final_timestamp_ms=_source_duration_ms(10, 30.0),
            fallback_frame_dur_ms=100,
        )
        self.assertEqual(durations, [100, 100, 133])
        self.assertEqual(sum(durations), 333)


if __name__ == '__main__':
    unittest.main()
