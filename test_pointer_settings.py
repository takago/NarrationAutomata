"""Standalone pointer integration tests (run: python -m unittest test_pointer_settings)."""
import unittest
from pointer_settings import effective_mode, create_motion
from pointer_motion import Motion, ffmpeg_position_expr


class PointerSettingsTests(unittest.TestCase):
    def setUp(self):
        self.project = {'pointer_default_mode':'static', 'pointer_slide_modes':{'2':'active'}}
        self.block = {'x':120, 'y':110, 'bbox':[110,100,320,260]}
        self.size = (640,360)

    def test_inheritance(self):
        self.assertEqual(effective_mode({},1),'static')
        self.assertEqual(effective_mode(self.project,1),'static')
        self.assertEqual(effective_mode(self.project,2),'active')
        self.assertEqual(effective_mode(self.project,2,{'pointer_mode':'static'}),'static')
        self.assertEqual(effective_mode(self.project,2,{'pointer_mode':'hidden'}),'hidden')

    def test_motion_types(self):
        for kind in ('fixed','line','ellipse','rounded_polygon','hidden'):
            value=create_motion({'type':kind},self.block,self.size)
            m=Motion.from_dict(value)
            self.assertEqual(m.jitter_px,0 if kind=='hidden' else 2)
            if kind!='hidden':
                x,y=ffmpeg_position_expr(m,0,3,*self.size)
                self.assertTrue(x and y)

    def test_invalid_bbox_falls_back(self):
        with self.assertRaises(ValueError):
            create_motion({'type':'ellipse'}, {'bbox':[0,0,900,200]}, self.size)

    def test_direction(self):
        motion=create_motion({'type':'line','direction':'right_to_left'},self.block,self.size)
        self.assertGreater(motion['points'][0][0],motion['points'][1][0])

if __name__=='__main__': unittest.main()
