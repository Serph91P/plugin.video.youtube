"""Fork release metadata must advertise the natively accepted feature build."""
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]


class ReleaseMetadataTests(unittest.TestCase):
    def test_fork_has_its_own_higher_stable_version(self):
        addon = ET.parse(ROOT / 'addon.xml').getroot()
        self.assertEqual(addon.get('id'), 'plugin.video.youtube')
        self.assertEqual(addon.get('version'), '7.4.4.1')
        self.assertGreater(tuple(map(int, addon.attrib['version'].split('.'))), (7, 4, 4))

    def test_release_notes_describe_profile_routing_and_retained_vr_auth(self):
        notes = (ROOT / 'changelog.txt').read_text()
        current = notes.split('## v7.4.4\n', 1)[0]
        self.assertTrue(current.startswith('## v7.4.4.1\n'))
        self.assertIn('TubeCast', current)
        self.assertIn('profile', current)
        self.assertIn('Android VR', current)
        self.assertIn('authentication', current)


if __name__ == '__main__':
    unittest.main()
