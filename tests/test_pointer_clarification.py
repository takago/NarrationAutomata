"""Optional targeted VLM lookup, tested without external GPU model dependencies."""
import ast
import unittest
from pathlib import Path
from unittest.mock import Mock

SOURCE = Path(__file__).resolve().parents[1] / 'slide_lecture.py'
tree = ast.parse(SOURCE.read_text(encoding='utf-8'))
names = {'refine_pointer_with_vlm', 'request_pointer_visual_clarification'}
module = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0)] +
                    [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in names], type_ignores=[])
ns = {'emit_pointer_clarification': Mock(), 'Path': Path, 'json': __import__('json'), 'DETECT_IMAGE_PARTS_SYSTEM_JA': 'fixed JSON',
      'DETECT_IMAGE_PARTS_SYSTEM_EN': 'fixed JSON'}
exec(compile(ast.fix_missing_locations(module), str(SOURCE), 'exec'), ns)

class ClarificationTest(unittest.TestCase):
    def setUp(self):
        self.blocks = [{'block_id': 0, 'type': 'image', 'source': 'pdf', 'bbox': [0, 0, 100, 100], 'label': 'figure'},
                       {'block_id': 1, 'type': 'text', 'source': 'pdf', 'bbox': [0, 0, 100, 20], 'label': 'title'}]
        self.sentences = ['the router', 'the title']
        self.alignments = [{'sentence': 'the router', 'block_id': 0}, {'sentence': 'the title', 'block_id': 1}]

    def test_no_question_avoids_extra_vlm(self):
        ns['request_pointer_visual_clarification'] = Mock(return_value=[])
        ns['run_vlm_element_detection'] = Mock()
        _, align, meta = ns['refine_pointer_with_vlm'](None, {'model':'x'}, Path('unused'), self.blocks, self.sentences, self.alignments)
        ns['run_vlm_element_detection'].assert_not_called()
        self.assertEqual(align[0]['block_id'], 0)
        self.assertEqual(meta['requested'], 0)

    def test_only_targeted_sentence_changes_to_new_block(self):
        ns['request_pointer_visual_clarification'] = Mock(return_value=[{'sentence_index':0,'question':'Locate the router'}])
        ns['run_vlm_element_detection'] = Mock(return_value=('', [{'bbox':[30,30,40,40], 'label':'router', 'type':'image_subpart'}]))
        ns['align_narration_with_blocks'] = Mock(return_value=[{'sentence':'the router', 'block_id':2}, {'sentence':'the title', 'block_id':0}])
        blocks, aligns, info = ns['refine_pointer_with_vlm'](None, {'model':'x'}, Path('unused'), self.blocks, self.sentences, self.alignments)
        self.assertEqual((aligns[0]['block_id'], aligns[1]['block_id']), (2,1))
        self.assertEqual(info, {'requested':1, 'added_blocks':1, 'changed_sentences':1})
        self.assertEqual(blocks[2]['source'], 'vlm')

    def test_duplicate_box_does_not_realign(self):
        ns['request_pointer_visual_clarification'] = Mock(return_value=[{'sentence_index':0,'question':'Locate the router'}])
        ns['run_vlm_element_detection'] = Mock(return_value=('', [{'bbox':[0,0,100,100], 'label':'figure'}]))
        ns['align_narration_with_blocks'] = Mock()
        _, _, info = ns['refine_pointer_with_vlm'](None, {'model':'x'}, Path('unused'), self.blocks, self.sentences, self.alignments)
        ns['align_narration_with_blocks'].assert_not_called()
        self.assertEqual(info['added_blocks'], 0)

if __name__ == '__main__':
    unittest.main()
