"""Exercise the real VR client builder and adaptive gate without Kodi or HTTP."""
import html
import types
import unittest
from unittest.mock import Mock
from urllib.parse import unquote, urljoin

from test_cast_playback import load_module


def production_clients():
    prefix = 'vr_boundary'
    compat = types.ModuleType(prefix + '.kodion.compatibility')
    for name, value in {'range_type': range, 'string_type': str,
                        'unescape': html.unescape, 'unquote': unquote,
                        'urljoin': urljoin}.items():
        setattr(compat, name, value)
    network = types.ModuleType(prefix + '.kodion.network')
    setattr(network, 'BaseRequestsClass', type('BaseRequestsClass', (), {}))
    dependencies = {compat.__name__: compat, network.__name__: network}
    methods = load_module('kodion/utils/methods.py', prefix + '.kodion.utils.methods', dependencies)
    dependencies[methods.__name__] = methods
    request = load_module('youtube/client/request_client.py', prefix + '.youtube.client.request_client', dependencies)
    data = types.ModuleType(prefix + '.youtube.client.data_client')
    setattr(data, 'YouTubeDataClient', request.YouTubeRequestClient)
    dependencies[data.__name__] = data
    player = load_module('youtube/client/player_client.py', prefix + '.youtube.client.player_client', dependencies)
    return request.YouTubeRequestClient, player.YouTubePlayerClient


class ObservedFormats(list):
    """Observe whether the actual adaptive gate reads a client's formats."""
    def __init__(self):
        super().__init__([{}])
        self.read = False

    def __iter__(self):
        self.read = True
        return super().__iter__()


class AndroidVRBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.request, player_class = production_clients()
        self.player = player_class.__new__(player_class)
        self.player._context = Mock()
        settings = self.player._context.get_settings.return_value
        settings.stream_features.return_value = ()
        settings.mpd_video_qualities.return_value = (360, 720)
        self.player._audio_only = False
        self.player._language_base = 'en'
        self.player._language_prefer_default = False
        self.player.log = Mock(debugging=False)

    def test_vr_builder_keeps_authentication_but_disables_adaptive(self):
        client = self.request.build_client('android_vr', data={
            '_auth_requested': True,
            '_access_tokens': {'vr': 'synthetic-vr-token'},
        })
        self.assertEqual(client['_auth_type'], 'vr')
        self.assertEqual(client['_has_auth'], 'vr')
        self.assertEqual(client['headers']['Authorization'], 'Bearer synthetic-vr-token')
        self.assertIs(client.get('_use_adaptive', True), False)
        self.assertNotIn('Authorization', self.request.CLIENTS['android_vr']['headers'])

    def test_real_adaptive_gate_never_reads_vr_formats(self):
        formats = ObservedFormats()
        result = self.player._process_adaptive_streams({
            'android_vr': {'client': self.request.build_client('android_vr'), 'adaptive_fmts': formats},
        })
        self.assertFalse(formats.read)
        self.assertEqual(result, (None, None))

    def test_mixed_clients_skip_vr_without_skipping_ios(self):
        vr_formats, ios_formats = ObservedFormats(), ObservedFormats()
        self.player._process_adaptive_streams({
            'android_vr': {'client': self.request.build_client('android_vr'), 'adaptive_fmts': vr_formats},
            'ios': {'client': self.request.build_client('ios'), 'adaptive_fmts': ios_formats},
        })
        self.assertFalse(vr_formats.read)
        self.assertTrue(ios_formats.read)

    def test_other_client_adaptive_default_stays_enabled(self):
        self.assertIs(self.request.build_client('ios').get('_use_adaptive', True), True)


if __name__ == '__main__':
    unittest.main()
