"""Exercise the real DASH generator with uneven codec quality coverage."""
import xml.etree.ElementTree as ET
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from urllib.parse import urlencode, urlunsplit

from test_android_vr import production_clients


NS = {'m': 'urn:mpeg:dash:schema:mpd:2011'}


def stream(media_type, codec, height=0, width=0):
    return {
        'id': '{}-{}'.format(codec, height),
        'container': codec,
        'mimeType': media_type + '/mp4',
        'mediaType': media_type,
        'langCode': '', 'langName': '', 'role': '',
        'duration': 60, 'label': '{}p {}'.format(height, codec),
        'height': height, 'width': width, 'fps': 30, 'frameRate': '30',
        'hdr': False, 'channels': 2, 'sampleRate': 48000,
        'codecs': codec, 'bitrate': 1000000,
        'baseUrl': 'https://media.invalid/synthetic',
        'indexRange': '100-200', 'initRange': '0-99',
    }


class ManifestQualityTests(TestCase):
    def manifest(self, mode=('list',), primary_codec='avc1', primary_height=1080,
                 features=()):
        _, player_class = production_clients()
        player = player_class.__new__(player_class)
        player._context = Mock()
        settings = player._context.get_settings.return_value
        settings.stream_select.return_value = mode
        settings.stream_features.return_value = features
        player._context.localize.return_value = 'Automatic'
        player.log = Mock()
        player.video_id = 'synthetic-video'
        primary = stream('video', primary_codec, primary_height,
                         primary_height * 16 // 9)
        low = stream('video', 'av01', 144, 256)
        audio = stream('audio', 'mp4a')
        # This is the order returned by the production adaptive stream sorter.
        video = [((s['container'],), [s]) for s in (primary, low)]
        if 'auto' in mode:
            video = [((primary['mimeType'],), [primary])] + video
        sounds = [((audio['container'],), [audio])]
        if 'auto' in mode:
            sounds.insert(0, ((audio['mimeType'],), [audio]))
        # load_module deliberately scopes imports to its dependency stubs. The
        # function globals give us the actual executed production module here.
        globals_ = player._generate_mpd_manifest.__func__.__globals__
        file_ = Mock()
        file_.__enter__ = Mock(return_value=file_)
        file_.__exit__ = Mock(return_value=False)
        file_.write.return_value = True
        with patch.dict(globals_, {
            'xbmcvfs': Mock(File=Mock(return_value=file_)),
            'VALUE_TO_STR': {True: 'true', False: 'false'},
            'get_connect_address': Mock(return_value='127.0.0.1:1234'),
            'PATHS': SimpleNamespace(MPD='/mpd'),
            'urlencode': urlencode, 'urlunsplit': urlunsplit,
        }), patch.object(player, 'BASE_PATH', '/synthetic'):
            url, selected = player._generate_mpd_manifest(video, sounds, {})
        self.assertIsNotNone(url)
        self.assertEqual(selected['video'], primary)
        return ET.fromstring(file_.write.call_args.args[0])

    def video_sets(self, root):
        return [s for s in root.findall('.//m:AdaptationSet', NS)
                if s.get('contentType') == 'video']

    def test_list_mode_defaults_to_full_resolution_not_low_resolution_av1(self):
        sets = self.video_sets(self.manifest())
        defaults = [s for s in sets if s.get('default') == 'true']
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0].find('m:Representation', NS).get('height'), '1080')
        self.assertEqual(defaults[0].find('m:Role', NS).get('value'), 'main')
        self.assertEqual(len(sets), 2, 'Keep the manual AV1 alternative available')

    def test_full_resolution_av1_remains_supported(self):
        sets = self.video_sets(self.manifest(primary_codec='av01', primary_height=2160))
        defaults = [s for s in sets if s.get('default') == 'true']
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0].find('m:Representation', NS).get('height'), '2160')
        self.assertEqual(defaults[0].find('m:Representation', NS).get('codecs'), 'av01')

    def test_auto_plus_list_keeps_only_automatic_video_default(self):
        sets = self.video_sets(self.manifest(mode=('auto', 'list')))
        defaults = [s for s in sets if s.get('default') == 'true']
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0].find('m:Representation', NS).get('height'), '1080')

    def test_audio_default_is_preserved(self):
        root = self.manifest()
        audio = [s for s in root.findall('.//m:AdaptationSet', NS)
                 if s.get('contentType') == 'audio']
        self.assertEqual(len(audio), 1)
        self.assertEqual(audio[0].get('default'), 'true')

    def test_group_filter_keeps_preferred_video_default(self):
        sets = self.video_sets(self.manifest(features=('filter',)))
        defaults = [s for s in sets if s.get('default') == 'true']
        self.assertEqual(len(defaults), 1)
        self.assertEqual(defaults[0].find('m:Representation', NS).get('height'), '1080')
