import importlib.util
from pathlib import Path
import unittest

path = Path(__file__).resolve().parents[1] / 'scripts/release_tracking_check.py'
spec = importlib.util.spec_from_file_location('tracking', path)
tracking = importlib.util.module_from_spec(spec)
spec.loader.exec_module(tracking)


class Tracking(unittest.TestCase):
    def test_sources_and_repeated_events_are_not_merged(self):
        app = 'E UtTrackFirebaseImpl: logEvent: event: select_content, content: denoise, item_id: start'
        sdk = 'V FA: Logging event (FE): select_content, Bundle[{content_type=denoise, item_id=start, uuid=secret}]'
        result = tracking.report('\n'.join([app, app, sdk]), {'denoise'})
        self.assertEqual([x['count'] for x in result['counts']], [2, 1])
        self.assertNotIn('secret', str(result))

    def test_legacy_and_old_firebase_format(self):
        value = tracking.parse('V FA: Logging event: origin=app,name=select_content,params=Bundle[{content_type=denoise,item_id=failed}]')
        self.assertEqual(value['item_id'], 'failed')
        value = tracking.parse('ISFirebaseListener sendEvent eventName=select_content key=[content_type,uuid] value=[denoise,secret] item_id: start')
        self.assertEqual(value['content_type'], 'denoise')
        self.assertNotIn('secret', str(value))

    def test_unrelated_and_sampled_events_excluded(self):
        self.assertIsNone(tracking.parse('V FA: Logging event: sampled_select_content, Bundle[{content_type=denoise}]'))
        self.assertEqual(tracking.report('V FA: Logging event: select_content, Bundle[{content_type=other}]', {'denoise'})['events'], [])
