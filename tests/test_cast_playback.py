"""Execute the real play/monitor modules against explicit Kodi dependency stubs.

These are integration-boundary tests, not a signed-in native Kodi acceptance.
"""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import Mock, patch

import test_cast_profiles as fixtures
from test_cast_profiles import cast, Context, PHONE_A, MockProvider

ROOT = Path(__file__).resolve().parents[1] / 'resources/lib/youtube_plugin'


def load_module(relative, name, dependencies):
    """Stub imports only; compile and execute the complete production module."""
    path = ROOT / relative
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.ImportFrom) and node.level:
            package = importlib.util.resolve_name('.' * node.level + (node.module or ''), name.rpartition('.')[0])
            if package not in dependencies:
                dependencies[package] = types.ModuleType(package)
            module = dependencies[package]
            for alias in node.names:
                if not hasattr(module, alias.name):
                    setattr(module, alias.name, alias.name.lower() if alias.name.isupper() else Mock())
    for fullname in list(dependencies) + [name]:
        parts = fullname.split('.')
        for length in range(1, len(parts)):
            parent = '.'.join(parts[:length])
            if parent not in dependencies:
                module = types.ModuleType(parent)
                module.__path__ = []
                dependencies[parent] = module
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    with patch.dict(sys.modules, dependencies): spec.loader.exec_module(module)
    return module


def production_modules():
    dependencies = {'cast_test.kodion.cast_profiles': cast}
    compat = types.ModuleType('cast_test.kodion.compatibility')
    compat.xbmc = types.SimpleNamespace(Player=type('Player', (), {}))
    compat.string_type = str
    compat.urlencode = compat.urlunsplit = Mock()
    dependencies[compat.__name__] = compat
    play = load_module('youtube/helper/yt_play.py', 'cast_test.youtube.helper.yt_play', dependencies)
    monitor = load_module('kodion/monitors/player_monitor.py', 'cast_test.kodion.monitors.player_monitor', dependencies)
    return play, monitor


class PlaybackBoundaryTests(unittest.TestCase):
    def setUp(self):
        fixtures.CastProfilesTests.setUp(self)
        self.play, self.monitor = production_modules()

    def tearDown(self):
        fixtures.CastProfilesTests.tearDown(self)

    def test_play_resolves_phone_before_creating_client(self):
        self.context.params = {'video_id': 'synthetic', 'cast_device': PHONE_A, 'cast_name': 'A'}
        provider = Mock()
        provider.get_client.side_effect = RuntimeError('stop after client boundary')
        with self.assertRaisesRegex(RuntimeError, 'client boundary'):
            self.play._play_stream(provider, self.context)
        selected = provider.get_client.call_args.args[0]
        self.assertEqual(selected.get_uuid(), 'profile-one')
        self.assertEqual(self.context.get_uuid(), 'profile-zero')

    def test_cancelled_pairing_never_creates_client(self):
        self.context.params = {'video_id': 'synthetic', 'cast_device': PHONE_A}
        self.context.ui.on_select.return_value = -1
        provider = Mock()
        self.assertFalse(self.play._play_stream(provider, self.context))
        provider.get_client.assert_not_called()

    def test_play_handoff_carries_bound_profile_to_service(self):
        self.context.params = {'video_id': 'synthetic', 'cast_device': PHONE_A, 'cast_name': 'A'}
        settings = Mock()
        for option in ('default_player_web_urls', 'ask_for_video_quality', 'audio_only',
                       'use_mpd_videos', 'get_bool'):
            getattr(settings, option).return_value = False
        settings.use_remote_history.return_value = True
        settings.use_local_history.return_value = True
        self.context.ui.get_property.return_value = False
        self.context.ui.pop_property.return_value = None
        provider = Mock()
        provider.get_client.return_value.load_stream_info.return_value = ([{}], None)
        stream = {'url': 'fixture-url', 'video': {'codec': 'fixture'}, 'playback_stats': {}}
        self.play.VideoItem.return_value.get_play_count.return_value = 0
        with patch.object(Context, 'get_settings', return_value=settings, create=True), \
             patch.object(Context, 'get_ui', return_value=self.context.ui), \
             patch.object(Context, 'send_notification', create=True), \
             patch.object(self.play, '_select_stream', return_value=stream):
            self.assertTrue(self.play._play_stream(provider, self.context))
        handoff = [call.kwargs['value'] for call in self.context.ui.set_property.call_args_list
                   if call.args[0] == self.play.PLAYER_DATA][0]
        self.assertEqual(handoff['profile_id'], 'profile-one')
        self.assertTrue(handoff['use_remote_history'])
        self.assertTrue(handoff['use_local_history'])

    def test_monitor_uses_profile_from_playback_data_not_service_profile(self):
        monitor = self.monitor.PlayerMonitor(MockProvider(), self.context, Mock())
        self.context.ui.pop_property.return_value = {
            'video_id': 'synthetic', 'profile_id': 'profile-two',
            'seek_time': 0, 'start_time': 0, 'end_time': 0,
        }
        self.context.ui.get_property.return_value = False
        monitor.getTime = Mock(return_value=0)
        monitor.getTotalTime = Mock(return_value=60)
        with patch.object(self.monitor, 'PlayerMonitorThread') as thread:
            monitor.onAVStarted()
        selected = thread.call_args.args[2]
        self.assertEqual(selected.get_uuid(), 'profile-two')
        self.assertIsNot(thread.call_args.args[1], monitor._provider)
        self.assertEqual(self.context.get_uuid(), 'profile-zero')

    def test_real_monitor_sends_playing_and_stopped_history_to_bound_profile(self):
        # Execute the complete production monitor run; only Kodi and HTTP/storage
        # are boundary mocks. A service-global user change must not affect it.
        provider, context = cast.playback_profile(MockProvider(), self.context, {'profile_id': 'profile-one'})
        client = Mock(logged_in=True)
        provider.get_client = Mock(return_value=client)
        settings = Mock()
        settings.get_play_count_min_percent.return_value = 90
        settings.get_bool.return_value = False
        context.get_settings = Mock(return_value=settings)
        context.get_playback_history = Mock(return_value=Mock())
        context.get_playlist_player = Mock(return_value=Mock())
        context.send_notification = Mock()
        context.abort_requested = Mock(return_value=False)
        player = Mock(current_time=20, total_time=100, seeking=False,
                      start_time=None, seek_time=None, end_time=None)
        player.isPlaying.return_value = True
        player.getPlayingFile.return_value = 'synthetic-url'
        player.getTime.return_value = 20
        player.getTotalTime.return_value = 100
        data = {'video_id': 'synthetic', 'profile_id': 'profile-one',
                'playing_file': 'synthetic-url', 'video_status': {},
                'use_remote_history': True, 'use_local_history': True,
                'playback_stats': {'playback_url': 'fixture-playback', 'watchtime_url': 'fixture-watchtime'}}
        with patch.object(self.monitor.threading, 'Thread'):
            thread = self.monitor.PlayerMonitorThread(player, provider, context, Mock(), data)
        thread.abort_now = Mock(side_effect=[False, True])
        self.context.manager.set_user(2)
        thread.run()
        self.assertEqual(context.get_uuid(), 'profile-one')
        self.assertEqual(client.update_watch_history.call_count, 3)
        self.assertEqual(client.update_watch_history.call_args.kwargs['status'][-1], 'stopped')
        context.get_playback_history.return_value.set_item.assert_called_once()
        for call in provider.get_client.call_args_list:
            self.assertIs(call.args[0], context)
        self.assertTrue(thread.ended())

    def test_removed_playback_profile_never_starts_global_history_monitor(self):
        monitor = self.monitor.PlayerMonitor(MockProvider(), self.context, Mock())
        self.context.ui.pop_property.return_value = {'profile_id': 'removed'}
        self.context.ui.get_property.return_value = False
        with patch.object(self.monitor, 'PlayerMonitorThread') as thread:
            monitor.onAVStarted()
        thread.assert_not_called()


if __name__ == '__main__': unittest.main()
