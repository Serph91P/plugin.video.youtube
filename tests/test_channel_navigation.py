"""Actual menu builder against a URI boundary; no playback or Kodi UI."""
import ast
from pathlib import Path
import types
import unittest
from unittest.mock import Mock
from test_cast_playback import load_module

ROOT = Path(__file__).resolve().parents[1]

class NavigationTests(unittest.TestCase):
    def setUp(self):
        constants=types.ModuleType('navigation.kodion.constants')
        constants.PROPERTY_AS_LABEL='$INFO[Window(home).Property(plugin.video.youtube-%s)]'
        constants.PATHS=types.SimpleNamespace(ROUTE='kodion/route',CHANNEL='channel')
        self.menu=load_module('kodion/items/menu_items.py','navigation.kodion.items.menu_items', {constants.__name__:constants})
        self.context=Mock()
        self.context.localize.side_effect=lambda key,label: label
        self.context.get_ui().bold.side_effect=lambda text: text
        self.context.create_uri.side_effect=lambda path,params,**kwargs: (path,params,kwargs)

    def test_missing_channel_has_no_broken_route(self):
        for value in (None, ''):
            self.assertIsNone(self.menu.channel_go_to(self.context,value,'Channel'))
        self.context.create_uri.assert_not_called()

    def test_bound_id_uses_native_route_in_every_profile(self):
        for profile in ('global','phone-a','phone-b'):
            self.context.profile=profile
            before=dict(self.context.__dict__)
            label,(path,params,kwargs)=self.menu.channel_go_to(self.context,'UCfixture','Channel, One')
            self.assertEqual(path,('kodion/route','channel','UCfixture'))
            self.assertEqual(params['category_label'],'Channel, One')
            self.assertNotIn('$INFO',str(path))
            self.assertEqual(self.context.profile,profile)
        self.context.get_access_manager.assert_not_called()
        self.context.execute.assert_not_called()

    def test_different_items_cannot_reuse_stale_global_channel(self):
        for channel in ('UCfirst','UCsecond'):
            result=self.menu.channel_go_to(self.context,channel,channel)
            self.assertEqual(result[1][0][-1],channel)

    def test_video_and_playlist_population_bind_real_metadata(self):
        tree=ast.parse((ROOT/'resources/lib/youtube_plugin/youtube/helper/utils.py').read_text())
        calls=[n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='channel_go_to']
        self.assertEqual(len(calls),2)
        for call in calls:
            self.assertEqual([ast.unparse(a) for a in call.args],['context','channel_id','channel_name'])

if __name__=='__main__': unittest.main()
