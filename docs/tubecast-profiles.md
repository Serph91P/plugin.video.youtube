# TubeCast phone profiles

This fork supports profile-aware playback from the matching
[TubeCast fork](https://github.com/Serph91P/script.tubecast).

## Setup

1. Add and sign in to each required profile in the YouTube add-on. YouTube
   remote watch history must also be enabled in the add-on and Google account.
2. Install matching builds of both forks. In TubeCast enable **Use a separate
   YouTube profile for each phone** and use the YouTube playback backend.
3. Connect only one phone at a time. On its first playback, select the existing
   signed-in YouTube profile on Kodi. This is an explicit pairing, not automatic
   recognition of a Google login. Repeat for each phone.
4. Later casts from that sender device reuse the association. The profile shown
   in Kodi can remain selected independently: authentication, watchtime, local
   history and end-of-playback actions use the cast's own profile context.

One phone must always represent the same account. A YouTube app reinstall,
cleared app data or a changed Lounge device ID may require pairing again.
Different YouTube channels under the same phone/account are not distinguished.

To change a pairing, use **YouTube settings > Users > Reset TubeCast phone
associations**. This forgets all phone pairings, not accounts or sign-ins.
Removing a profile or signing it out requires an explicit new selection;
cancelling playback never falls back to the globally selected profile.

## Companion API v1

The package contains `resources/tubecast-profile-api.json` with `version: 1`.
TubeCast checks the installed package marker before using this feature, so
replacing the fork with an incompatible upstream add-on is detected.

Playback accepts `cast_device=<sha256-of-sender-id>` and optional
`cast_name=<display-name>` in addition to the existing video and seek fields.
Neither field contains OAuth tokens. The name is display-only. This is a local
routing key on the existing trusted Kodi/Cast boundary, not an authentication
credential; it must not be used to authorize remote access.

Associations are stored atomically in `tubecast_profiles.json` in this add-on's
data directory as device hash to stable local profile UUID. Credentials remain
in the existing YouTube profile store. A corrupt/unwritable association file
aborts profile playback instead of overwriting data or silently using another
account. Use the reset action to repair a corrupt association file.

Only cast playbacks carry the internal `profile_id` handoff to the player
monitor. Each cast monitor creates a fresh context and provider/client, with
`AccessManager.set_user(..., switch_to=False)`; it never changes the persistent
global selected user. Non-cast playback retains upstream behavior.

## Verification

`python3 -m unittest discover -s tests -v` runs stdlib tests, including complete
production play/monitor modules against explicit Kodi boundary stubs. These
are not a native Kodi or real-account acceptance test.

Before release, test with phone A and phone B signed into different accounts:
set Kodi's displayed profile to the other account, pair each phone in turn,
play/stop/advance/reconnect and check the actual YouTube histories on both
accounts. Also test cancellation, deleted/signed-out profiles and reset. A new
account on an already paired phone requires resetting its pairing first.

## Repository packaging (not yet activated)

The fork-owned jobs in `Add-on Validations` test both profile routing and the
publication contract, then use the pinned shared packager for `addon.xml` and
`resources/`. After a successful completed `master` run, the separate notifier
can forward the immutable evidence to the Kodi repository. Pull-request packages
are test artifacts only; they can never dispatch a public repository update.

[Repository integration and activation gates](https://github.com/Serph91P/repository.serph91p/blob/feat/tubecast-youtube-distribution/addon-publication/YOUTUBE.md)
track the native LibreELEC test, dispatch-secret provisioning, initial version
selection and first-publication bootstrap. A merge onto `master` can publish once
the dispatch secret is configured, so keep this as a draft until publication is
explicitly approved. No release tag or upstream submission token is required.
