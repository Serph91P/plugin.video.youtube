# -*- coding: utf-8 -*-
"""Local TubeCast phone associations; no Google credentials leave this add-on.

A sender key is an opaque SHA-256 device identifier, not proof of Google login.
Users explicitly pair it with an already signed-in, stable local profile UUID.
"""
from __future__ import absolute_import, division, unicode_literals

import json
import os
import re
import tempfile
from io import open


class CastProfileError(Exception):
    """Stop playback rather than accidentally using the globally selected user."""


def signed_in_users(manager):
    return [(user, details) for user, details in sorted(manager.get_users().items())
            if details.get('id') and any(
                token for field in ('access_token', 'refresh_token')
                for token in (details.get(field) or '').split('|'))]


class CastProfiles(object):
    def __init__(self, context):
        self.context = context
        self.filepath = os.path.join(context.get_data_path(), 'tubecast_profiles.json')

    def _load(self):
        try:
            with open(self.filepath, encoding='utf-8') as handle:
                data = json.load(handle)
            if not isinstance(data, dict) or not all(
                    isinstance(key, str) and re.fullmatch(r'[a-f0-9]{64}', key)
                    and isinstance(value, str) and value for key, value in data.items()):
                raise ValueError('Invalid TubeCast associations')
            return data
        except FileNotFoundError:
            return {}
        except (OSError, ValueError, TypeError):
            raise CastProfileError('Cannot read TubeCast associations')

    def _save(self, data):
        filename = None
        try:
            fd, filename = tempfile.mkstemp(prefix='.tubecast-', dir=os.path.dirname(self.filepath))
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(data, handle, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(filename, self.filepath)
        except (OSError, ValueError, TypeError):
            raise CastProfileError('Cannot save TubeCast association')
        finally:
            if filename and os.path.exists(filename):
                os.unlink(filename)

    def reset(self):
        try:
            os.unlink(self.filepath)
        except FileNotFoundError:
            pass
        except OSError:
            raise CastProfileError('Cannot reset TubeCast associations')

    def resolve(self, sender, name):
        if not isinstance(sender, str) or not re.fullmatch(r'[a-f0-9]{64}', sender):
            raise CastProfileError('Missing TubeCast phone identity')
        associations = self._load()
        users = signed_in_users(self.context.get_access_manager())
        profile = associations.get(sender)
        if profile and any(details['id'] == profile for _, details in users):
            return profile
        if not users:
            raise CastProfileError('Sign in to a YouTube profile before pairing TubeCast')
        # Sender names are untrusted display text, not account identities or markup.
        name = str(name or 'TubeCast').replace('[', '(').replace(']', ')')[:80]
        choice = self.context.get_ui().on_select(
            '{} - {}'.format(self.context.localize(30990), name),
            [details.get('name') or self.context.localize(30659) for _, details in users],
        )
        if not isinstance(choice, int) or choice < 0 or choice >= len(users):
            raise CastProfileError('TubeCast profile selection cancelled')
        profile = users[choice][1]['id']
        associations[sender] = profile
        self._save(associations)
        return profile


def profile_context(context, profile_id):
    """Construct a genuinely independent context, not clone()'s shared manager.

    set_user without switch_to selects only this manager's user. The persistent
    globally selected user, other players and service context remain untouched.
    """
    selected = context.__class__(path=context.get_path(),
                                 params=dict(context.get_params()),
                                 plugin_id=context.get_id())
    manager = selected.get_access_manager()
    for user, details in signed_in_users(manager):
        if details['id'] == profile_id:
            manager.set_user(user)
            return selected
    raise CastProfileError('TubeCast profile is missing or signed out')


def playback_profile(provider, context, player_data):
    profile_id = player_data.get('profile_id')
    if not profile_id:
        return provider, context
    # Provider owns a mutable cached client: never share it across profile monitors.
    return provider.__class__(), profile_context(context, profile_id)
