"""Profile routing unit tests. Context/UI boundaries are fakes, not Kodi."""
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

MODULE = Path(__file__).resolve().parents[1] / 'resources/lib/youtube_plugin/kodion/cast_profiles.py'
spec = importlib.util.spec_from_file_location('cast_profiles_under_test', MODULE)
cast = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cast)

PHONE_A = 'a' * 64
PHONE_B = 'b' * 64
USERS = {
    0: {'id': 'profile-zero', 'name': 'Signed out', 'access_token': '', 'refresh_token': ''},
    1: {'id': 'profile-one', 'name': 'One', 'access_token': '', 'refresh_token': 'fixture'},
    2: {'id': 'profile-two', 'name': 'Two', 'access_token': 'fixture', 'refresh_token': ''},
}


class Context:
    users = USERS
    root = None

    def __init__(self, path='/', params=None, plugin_id='plugin.video.youtube'):
        self.path, self.params, self.plugin_id = path, params or {}, plugin_id
        self.manager = Mock()
        self.manager.get_users.return_value = self.users
        self.manager.get_current_user.return_value = 0
        self.manager.set_user.side_effect = lambda user: setattr(self, 'selected', user)
        self.manager.get_current_user_id.side_effect = lambda: self.users[getattr(self, 'selected', 0)]['id']
        self.ui = Mock()
        self.ui.on_select.return_value = 0

    def get_access_manager(self): return self.manager
    def get_ui(self): return self.ui
    def get_data_path(self): return self.root
    def get_path(self): return self.path
    def get_params(self): return self.params
    def get_id(self): return self.plugin_id
    def get_uuid(self): return self.manager.get_current_user_id()
    def localize(self, value): return str(value)


class CastProfilesTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=os.environ.get('TMPDIR'))
        Context.root = self.tmp.name
        Context.users = dict(USERS)
        self.context = Context()
        self.store = cast.CastProfiles(self.context)

    def tearDown(self): self.tmp.cleanup()

    def test_first_phone_asks_only_signed_in_profiles_and_persists_uuid(self):
        self.assertEqual(self.store.resolve(PHONE_A, 'Phone'), 'profile-one')
        args = self.context.ui.on_select.call_args.args
        self.assertEqual(args[1], ['One', 'Two'])
        self.assertEqual(json.loads(Path(self.store.filepath).read_text()), {PHONE_A: 'profile-one'})

    def test_second_invocation_reuses_mapping_without_dialog(self):
        self.store.resolve(PHONE_A, 'Phone')
        other = Context()
        self.assertEqual(cast.CastProfiles(other).resolve(PHONE_A, 'Renamed'), 'profile-one')
        other.ui.on_select.assert_not_called()

    def test_two_phones_have_separate_profiles(self):
        self.store.resolve(PHONE_A, 'A')
        self.context.ui.on_select.return_value = 1
        self.assertEqual(self.store.resolve(PHONE_B, 'B'), 'profile-two')
        self.assertEqual(self.store.resolve(PHONE_A, 'A'), 'profile-one')

    def test_cancel_aborts_and_does_not_write(self):
        self.context.ui.on_select.return_value = -1
        with self.assertRaises(cast.CastProfileError): self.store.resolve(PHONE_A, 'A')
        self.assertFalse(Path(self.store.filepath).exists())

    def test_invalid_or_missing_identity_never_prompts_or_uses_default(self):
        for sender in ('', None, '../escape', 'a' * 63, 'a' * 64 + '\n'):
            with self.subTest(sender=sender), self.assertRaises(cast.CastProfileError):
                self.store.resolve(sender, 'A')
        self.context.ui.on_select.assert_not_called()

    def test_deleted_profile_requires_explicit_repair(self):
        self.store.resolve(PHONE_A, 'A')
        Context.users = {0: USERS[0], 2: USERS[2]}
        repaired_context = Context()
        repaired_context.ui.on_select.return_value = -1
        with self.assertRaises(cast.CastProfileError):
            cast.CastProfiles(repaired_context).resolve(PHONE_A, 'A')
        repaired_context.ui.on_select.assert_called_once()

    def test_signed_out_mapping_does_not_fall_back(self):
        self.store.resolve(PHONE_A, 'A')
        Context.users = {0: USERS[0]}
        with self.assertRaises(cast.CastProfileError):
            cast.CastProfiles(Context()).resolve(PHONE_A, 'A')

    def test_empty_token_slots_are_not_a_signed_in_profile(self):
        Context.users = {0: {'id': 'profile-zero', 'name': 'Out',
                             'access_token': '|||', 'refresh_token': '|||'}}
        with self.assertRaises(cast.CastProfileError):
            cast.CastProfiles(Context()).resolve(PHONE_A, 'A')

    def test_corrupt_store_aborts_instead_of_overwriting_pairings(self):
        Path(self.store.filepath).write_text('{broken')
        with self.assertRaises(cast.CastProfileError): self.store.resolve(PHONE_A, 'A')
        self.assertEqual(Path(self.store.filepath).read_text(), '{broken')

    def test_non_object_store_aborts(self):
        Path(self.store.filepath).write_text('[]')
        with self.assertRaises(cast.CastProfileError): self.store.resolve(PHONE_A, 'A')

    def test_save_failure_aborts_before_returning_a_profile(self):
        with patch.object(cast.os, 'replace', side_effect=OSError('fixture failure')):
            with self.assertRaises(cast.CastProfileError): self.store.resolve(PHONE_A, 'A')
        self.assertEqual(list(Path(self.tmp.name).iterdir()), [])

    def test_reset_removes_all_associations_including_corrupt_store(self):
        Path(self.store.filepath).write_text('{broken')
        self.store.reset()
        self.assertFalse(Path(self.store.filepath).exists())

    def test_new_context_has_independent_manager_and_uuid(self):
        selected = cast.profile_context(self.context, 'profile-two')
        self.assertIsNot(selected, self.context)
        self.assertIsNot(selected.manager, self.context.manager)
        self.assertEqual(selected.get_uuid(), 'profile-two')
        self.context.manager.set_user.assert_not_called()
        selected.manager.set_user.assert_called_once_with(2)

    def test_profile_context_fails_closed_if_profile_no_longer_exists(self):
        with self.assertRaises(cast.CastProfileError):
            cast.profile_context(self.context, 'removed-profile')

    def test_profile_context_preserves_path_params_and_plugin_id(self):
        source = Context('/play/', {'video_id': 'synthetic'}, 'plugin.video.youtube')
        selected = cast.profile_context(source, 'profile-one')
        self.assertEqual(selected.get_path(), '/play/')
        self.assertEqual(selected.get_params(), {'video_id': 'synthetic'})
        self.assertIsNot(selected.get_params(), source.get_params())

    def test_monitor_binding_has_independent_context_and_provider(self):
        provider = MockProvider()
        selected_provider, selected_context = cast.playback_profile(provider, self.context, {'profile_id': 'profile-one'})
        self.assertIsNot(selected_provider, provider)
        self.assertEqual(selected_context.get_uuid(), 'profile-one')
        self.assertEqual(self.context.get_uuid(), 'profile-zero')
        other_provider, other_context = cast.playback_profile(provider, self.context, {'profile_id': 'profile-two'})
        self.assertIsNot(selected_provider, other_provider)
        self.assertEqual(other_context.get_uuid(), 'profile-two')
        self.assertEqual(selected_context.get_uuid(), 'profile-one')

    def test_legacy_monitor_without_profile_keeps_existing_behavior(self):
        provider = MockProvider()
        self.assertEqual(cast.playback_profile(provider, self.context, {}), (provider, self.context))


class MockProvider:
    pass


if __name__ == '__main__': unittest.main()
