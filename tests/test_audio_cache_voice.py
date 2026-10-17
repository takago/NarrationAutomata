"""Regressions for voice-scoped audio and invalidation conditions."""
import json
import tempfile
import unittest
from pathlib import Path
from audio_cache import audio_path, cache_matches, save_signature, tts_signature, signature


class AudioCacheVoiceTests(unittest.TestCase):
    def test_voice_and_model_are_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp) / 'audio'
            a = {'model': 'TTS/X', 'voice': 'A'}
            b = {'model': 'TTS/X', 'voice': 'B'}
            c = {'model': 'TTS/Y', 'voice': 'A'}
            self.assertEqual(audio_path(base, 1, a), audio_path(base, 1, a))
            self.assertEqual(audio_path(base, 1, a).name, '001.mp3')
            self.assertEqual(len({audio_path(base, 1, z) for z in (a, b, c)}), 3)
            self.assertTrue(all(x.parent.parent == base for x in (audio_path(base, 1, z) for z in (a, b, c))))

    def test_audio_without_matching_signature_is_not_reused(self):
        with tempfile.TemporaryDirectory() as tmp:
            mp3 = Path(tmp) / '001.mp3'
            mp3.write_bytes(b'mp3')
            self.assertFalse(cache_matches(mp3, 'abc'))
            save_signature(mp3, 'abc')
            self.assertTrue(cache_matches(mp3, 'abc'))
            self.assertFalse(cache_matches(mp3, 'def'))

    def test_changes_to_text_and_project_reading_dictionary_invalidate(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            txt = root / '001.txt'
            filt = root / 'filter.yaml'
            txt.write_text('hello')
            filt.write_text('dictionary: {}')
            cfg = {'model': 'M', 'voice': 'V'}
            a = tts_signature(txt, cfg, filt, 'ja', root)
            txt.write_text('hello!')
            b = tts_signature(txt, cfg, filt, 'ja', root)
            self.assertNotEqual(a, b)
            (root / 'project.json').write_text(json.dumps({'tts_dictionary': {'KIT': 'キット'}}))
            c = tts_signature(txt, cfg, filt, 'ja', root)
            self.assertNotEqual(b, c)
            self.assertNotEqual(c, tts_signature(txt, {**cfg, 'voice': 'V2'}, filt, 'ja', root))

    def test_project_audio_path_requires_tts_configuration(self):
        """Avoid reintroducing the root-level audio/<page>.mp3 lookup."""
        import ast
        source = Path(__file__).resolve().parents[1].joinpath('app.py').read_text(encoding='utf-8')
        module = ast.parse(source)
        cls = next(x for x in module.body if isinstance(x, ast.ClassDef) and x.name == 'ProjectPaths')
        method = next(x for x in cls.body if isinstance(x, ast.FunctionDef) and x.name == 'audio')
        self.assertEqual(len(method.args.defaults), 1)  # lang only; config is required
        self.assertNotIn('Legacy lookup', ast.get_source_segment(source, method))

    def test_model_name_sanitization_cannot_collide(self):
        base = Path('/tmp/audio')
        self.assertNotEqual(audio_path(base, 1, {'model': 'A/B', 'voice': 'X'}),
                            audio_path(base, 1, {'model': 'A?B', 'voice': 'X'}))


if __name__ == '__main__':
    unittest.main()
