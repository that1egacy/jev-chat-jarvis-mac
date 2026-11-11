"""跨屏拼接算法：重叠对缝、k=1 不算可靠、断层只保留新帧。"""
import types
import unittest

import stitch


def _msg(text, side='them'):
    return types.SimpleNamespace(text=text, side=side)


class OverlapTests(unittest.TestCase):
    def test_two_line_overlap_is_found(self):
        previous = [_msg('一'), _msg('二'), _msg('三')]
        current = [_msg('二'), _msg('三'), _msg('四')]
        self.assertEqual(stitch.overlap(previous, current), 2)

    def test_full_containment_uses_the_whole_previous_frame(self):
        previous = [_msg('一'), _msg('二')]
        current = [_msg('一'), _msg('二'), _msg('三')]
        self.assertEqual(stitch.overlap(previous, current), 2)

    def test_single_line_overlap_is_not_trusted(self):
        previous = [_msg('一')]
        current = [_msg('一'), _msg('二')]
        self.assertEqual(stitch.overlap(previous, current), 0)

    def test_side_must_match(self):
        previous = [_msg('一'), _msg('二', 'me')]
        current = [_msg('一'), _msg('二', 'them'), _msg('三')]
        self.assertEqual(stitch.overlap(previous, current), 0)

    def test_empty_frames(self):
        self.assertEqual(stitch.overlap([], [_msg('一')]), 0)
        self.assertEqual(stitch.overlap([_msg('一')], []), 0)


class MergeTests(unittest.TestCase):
    def test_joined_history_appends_only_new_messages(self):
        previous = [_msg('一'), _msg('二'), _msg('三')]
        current = [_msg('二'), _msg('三'), _msg('四')]
        merged, joined = stitch.merge(previous, current)
        self.assertTrue(joined)
        self.assertEqual([m.text for m in merged], ['一', '二', '三', '四'])

    def test_gap_keeps_only_the_new_frame(self):
        previous = [_msg('一'), _msg('二')]
        current = [_msg('五'), _msg('六')]
        merged, joined = stitch.merge(previous, current)
        self.assertFalse(joined)
        self.assertEqual([m.text for m in merged], ['五', '六'])

    def test_first_frame_is_taken_whole(self):
        merged, joined = stitch.merge([], [_msg('一'), _msg('二')])
        self.assertTrue(joined)
        self.assertEqual(len(merged), 2)

    def test_merge_does_not_mutate_inputs(self):
        previous = [_msg('一'), _msg('二')]
        current = [_msg('二'), _msg('三')]
        stitch.merge(previous, current)
        self.assertEqual([m.text for m in previous], ['一', '二'])
        self.assertEqual([m.text for m in current], ['二', '三'])

    def test_min_overlap_can_be_relaxed_explicitly(self):
        previous = [_msg('一')]
        current = [_msg('一'), _msg('二')]
        merged, joined = stitch.merge(previous, current, min_overlap=1)
        self.assertTrue(joined)
        self.assertEqual([m.text for m in merged], ['一', '二'])


class FrameChainTests(unittest.TestCase):
    def test_chain_stitches_every_frame(self):
        frames = [
            [_msg('一'), _msg('二'), _msg('三')],
            [_msg('二'), _msg('三'), _msg('四')],
            [_msg('三'), _msg('四'), _msg('五')],
        ]
        merged = stitch.merge_frames(frames)
        self.assertEqual([m.text for m in merged], ['一', '二', '三', '四', '五'])

    def test_gap_restarts_the_segment(self):
        frames = [
            [_msg('一'), _msg('二')],
            [_msg('八'), _msg('九')],
        ]
        merged = stitch.merge_frames(frames)
        self.assertEqual([m.text for m in merged], ['八', '九'])

    def test_tuple_records_are_supported(self):
        merged, joined = stitch.merge([('一', 'them', '甲')], [('一', 'them', '甲'), ('二', 'them', '甲')],
                                      min_overlap=1)
        self.assertTrue(joined)
        self.assertEqual(len(merged), 2)


if __name__ == '__main__':
    unittest.main()
