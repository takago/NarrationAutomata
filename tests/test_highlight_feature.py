"""No extra runtime dependencies: exercise highlight timing and filters."""
import ast
import unittest
from pathlib import Path

source = Path(__file__).resolve().parents[1] / 'slide_lecture.py'
module = ast.parse(source.read_text(encoding='utf-8'))
selected = [node for node in module.body if isinstance(node, ast.FunctionDef) and node.name in ('build_highlight_schedule', 'highlight_filters')]
namespace = {}
exec(compile(ast.Module(body=selected, type_ignores=[]), str(source), 'exec'), namespace)

class HighlightTests(unittest.TestCase):
    def test_detected_code_line(self):
        result = namespace['build_highlight_schedule'](
            [{'block_id':1, 'type':'code_line', 'bbox':[10,20,150,40]}],
            [{'block_id':1}], [{'start':1., 'end':2.}], (957,718))
        self.assertEqual(result[0]['w'], 140)
        self.assertIn('lt(t,2)', namespace['highlight_filters'](result,'yellow',0.3))

    def test_missing_or_invalid_target(self):
        self.assertEqual(namespace['build_highlight_schedule']([{'block_id':1, 'bbox':[0,0,1,1]}], [{'block_id':1}], [{'start':0,'end':2}], (957,718)), [])

    def test_stationary_drawbox(self):
        event = {'start': 1., 'end': 3., 'x': 0, 'y': 0,
                 'w': 30, 'h': 15, 'canvas_w': 100, 'canvas_h': 80}
        chain = namespace['highlight_filters']([event], 'cyan', .3)
        self.assertEqual(chain.count('drawbox='), 1)
        self.assertIn('x=0:y=0:w=30:h=15', chain)
        self.assertNotIn('mod(', chain)

    def test_bbox_area_threshold(self):
        blocks = [{'block_id': 1, 'type': 'text', 'bbox': [0, 0, 50, 50]},
                  {'block_id': 2, 'type': 'text', 'bbox': [0, 0, 51, 50]}]
        align = [{'block_id': 1}, {'block_id': 2}]
        timing = [{'start': 0, 'end': 1}, {'start': 1, 'end': 2}]
        result = namespace['build_highlight_schedule'](blocks, align, timing, (100, 100))
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]['w'], 50)
        self.assertEqual(len(namespace['build_highlight_schedule'](blocks, align, timing, (100, 100), 30)), 2)

    def test_highlight_does_not_modify_pointer_schedule(self):
        # The video-generation caller must not suppress the pointer when highlighting.
        source_text = source.read_text(encoding='utf-8')
        self.assertNotIn('suppress_pointer_during_highlights', source_text)
        self.assertIn('schedule,\n                laser_img,', source_text)

    def test_reject_unsafe_color(self):
        with self.assertRaises(ValueError):
            namespace['highlight_filters']([], 'red;null', 0.3)
