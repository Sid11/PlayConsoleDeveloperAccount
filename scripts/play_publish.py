#!/usr/bin/env python3
"""Google Play Console release pipeline CLI.

Wraps the Android Publisher API v3 (https://developers.google.com/android-publisher)
so a CI job can upload a build to a track, adjust a staged rollout, promote or halt a
release, update store listing text/graphics, or just check current status -- without
going through the Play Console UI for anything but the one-time, API-less steps
(creating the app itself and its policy declarations).

Every subcommand that changes something follows the same edit/commit lifecycle the API
requires: edits().insert() opens a draft, one or more calls mutate it, edits().commit()
makes it live. `status` uses the same insert() call but never commits, since it only reads.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import sys

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/androidpublisher"]

IMAGE_TYPES = [
    "icon",
    "featureGraphic",
    "phoneScreenshots",
    "sevenInchScreenshots",
    "tenInchScreenshots",
    "tvBanner",
    "tvScreenshot",
    "wearScreenshot",
    "promoGraphic",
]

TRACK_STATUSES = {"draft", "inProgress", "halted", "completed"}


def get_service(credentials_path: str):
    creds = service_account.Credentials.from_service_account_file(
        credentials_path, scopes=SCOPES
    )
    return build("androidpublisher", "v3", credentials=creds, cache_discovery=False)


def _fail(message: str) -> None:
    print(f"error: {message}", file=sys.stderr)
    sys.exit(1)


def _read_release_notes(path: str | None) -> list[dict] | None:
    """Read a directory of <language-code>.txt files into API releaseNotes entries."""
    if not path:
        return None
    if not os.path.isdir(path):
        _fail(f"--release-notes path is not a directory: {path}")
    notes = []
    for filename in sorted(os.listdir(path)):
        if not filename.endswith(".txt"):
            continue
        language = filename[: -len(".txt")]
        with open(os.path.join(path, filename), encoding="utf-8") as f:
            text = f.read().strip()
        if text:
            notes.append({"language": language, "text": text})
    return notes or None


def cmd_upload(service, args: argparse.Namespace) -> None:
    package_name = args.package
    edit = service.edits().insert(body={}, packageName=package_name).execute()
    edit_id = edit["id"]

    if args.artifact_type == "aab":
        result = (
            service.edits()
            .bundles()
            .upload(editId=edit_id, packageName=package_name, media_body=args.file)
            .execute()
        )
        version_code = result["versionCode"]
    else:
        result = (
            service.edits()
            .apks()
            .upload(editId=edit_id, packageName=package_name, media_body=args.file)
            .execute()
        )
        version_code = result["versionCode"]

    rollout = args.rollout
    release: dict = {"versionCodes": [str(version_code)]}
    notes = _read_release_notes(args.release_notes)
    if notes:
        release["releaseNotes"] = notes

    if rollout < 1.0:
        release["status"] = "inProgress"
        release["userFraction"] = rollout
    else:
        release["status"] = "completed"

    service.edits().tracks().update(
        editId=edit_id,
        track=args.track,
        packageName=package_name,
        body={"releases": [release]},
    ).execute()

    service.edits().commit(editId=edit_id, packageName=package_name).execute()
    print(
        f"Uploaded versionCode={version_code} to track={args.track} "
        f"(rollout={rollout}, status={release['status']}) for {package_name}"
    )


def _find_in_progress_release(service, package_name: str, edit_id: str, track: str) -> dict:
    track_data = (
        service.edits()
        .tracks()
        .get(editId=edit_id, packageName=package_name, track=track)
        .execute()
    )
    releases = track_data.get("releases", [])
    for release in releases:
        if release.get("status") == "inProgress":
            return release
    _fail(
        f"no in-progress (staged rollout) release found on track={track} for {package_name}; "
        f"current releases: {releases}"
    )
    raise AssertionError("unreachable")  # _fail always exits


def cmd_set_rollout(service, args: argparse.Namespace) -> None:
    package_name = args.package
    edit = service.edits().insert(body={}, packageName=package_name).execute()
    edit_id = edit["id"]

    release = _find_in_progress_release(service, package_name, edit_id, args.track)
    release["userFraction"] = args.rollout
    if args.rollout >= 1.0:
        release["status"] = "completed"
        release.pop("userFraction", None)

    service.edits().tracks().update(
        editId=edit_id,
        track=args.track,
        packageName=package_name,
        body={"releases": [release]},
    ).execute()
    service.edits().commit(editId=edit_id, packageName=package_name).execute()
    print(f"Set rollout on track={args.track} to {args.rollout} for {package_name}")


def cmd_promote(service, args: argparse.Namespace) -> None:
    package_name = args.package
    edit = service.edits().insert(body={}, packageName=package_name).execute()
    edit_id = edit["id"]

    source_track = (
        service.edits()
        .tracks()
        .get(editId=edit_id, packageName=package_name, track=args.from_track)
        .execute()
    )
    releases = source_track.get("releases", [])
    if not releases:
        _fail(f"no releases found on source track={args.from_track} for {package_name}")
    version_codes = releases[0]["versionCodes"]

    service.edits().tracks().update(
        editId=edit_id,
        track=args.to_track,
        packageName=package_name,
        body={"releases": [{"versionCodes": version_codes, "status": "completed"}]},
    ).execute()
    service.edits().commit(editId=edit_id, packageName=package_name).execute()
    print(
        f"Promoted versionCodes={version_codes} from track={args.from_track} "
        f"to track={args.to_track} for {package_name}"
    )


def cmd_halt(service, args: argparse.Namespace) -> None:
    package_name = args.package
    edit = service.edits().insert(body={}, packageName=package_name).execute()
    edit_id = edit["id"]

    release = _find_in_progress_release(service, package_name, edit_id, args.track)
    release["status"] = "halted"

    service.edits().tracks().update(
        editId=edit_id,
        track=args.track,
        packageName=package_name,
        body={"releases": [release]},
    ).execute()
    service.edits().commit(editId=edit_id, packageName=package_name).execute()
    print(f"Halted rollout on track={args.track} for {package_name}")


def cmd_update_listing(service, args: argparse.Namespace) -> None:
    package_name = args.package
    edit = service.edits().insert(body={}, packageName=package_name).execute()
    edit_id = edit["id"]

    body = {}
    if args.title:
        body["title"] = args.title
    if args.short_description:
        body["shortDescription"] = args.short_description
    if args.full_description:
        body["fullDescription"] = args.full_description
    if args.video_url:
        body["video"] = args.video_url
    if not body:
        _fail("update-listing requires at least one of --title/--short-description/"
              "--full-description/--video-url")

    service.edits().listings().update(
        editId=edit_id,
        packageName=package_name,
        language=args.language,
        body=body,
    ).execute()
    service.edits().commit(editId=edit_id, packageName=package_name).execute()
    print(f"Updated listing ({args.language}) for {package_name}: {sorted(body)}")


def cmd_upload_images(service, args: argparse.Namespace) -> None:
    package_name = args.package
    files = sorted(
        f
        for f in glob.glob(os.path.join(args.dir, "*"))
        if os.path.splitext(f)[1].lower() in (".png", ".jpg", ".jpeg")
    )
    if not files:
        _fail(f"no .png/.jpg images found in {args.dir}")

    edit = service.edits().insert(body={}, packageName=package_name).execute()
    edit_id = edit["id"]

    for path in files:
        service.edits().images().upload(
            editId=edit_id,
            packageName=package_name,
            language=args.language,
            imageType=args.image_type,
            media_body=path,
        ).execute()

    service.edits().commit(editId=edit_id, packageName=package_name).execute()
    print(
        f"Uploaded {len(files)} {args.image_type} image(s) ({args.language}) "
        f"for {package_name}: {[os.path.basename(f) for f in files]}"
    )


def cmd_status(service, args: argparse.Namespace) -> None:
    package_name = args.package
    # A throwaway, never-committed edit -- edits() are the only way to read track
    # state, but read-only use doesn't need (and must not perform) a commit.
    edit = service.edits().insert(body={}, packageName=package_name).execute()
    edit_id = edit["id"]

    tracks_to_check = [args.track] if args.track else None
    if tracks_to_check is None:
        all_tracks = service.edits().tracks().list(
            editId=edit_id, packageName=package_name
        ).execute()
        tracks_to_check = [t["track"] for t in all_tracks.get("tracks", [])]

    for track in tracks_to_check:
        track_data = (
            service.edits()
            .tracks()
            .get(editId=edit_id, packageName=package_name, track=track)
            .execute()
        )
        releases = track_data.get("releases", [])
        if not releases:
            print(f"[{track}] (no releases)")
            continue
        for release in releases:
            fraction = release.get("userFraction")
            fraction_str = f", userFraction={fraction}" if fraction is not None else ""
            print(
                f"[{track}] versionCodes={release.get('versionCodes')} "
                f"status={release.get('status')}{fraction_str} "
                f"name={release.get('name')}"
            )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Google Play Console release pipeline CLI (Android Publisher API v3)."
    )
    parser.add_argument(
        "--credentials",
        required=True,
        help="Path to a Google service-account JSON key with Play Developer API access.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def add_common(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--package", required=True, help="Android application ID, e.g. com.example.app")

    p_upload = subparsers.add_parser("upload", help="Upload a build to a track.")
    add_common(p_upload)
    p_upload.add_argument("--track", required=True)
    p_upload.add_argument("--file", required=True, help="Path to the .aab or .apk to upload.")
    p_upload.add_argument(
        "--artifact-type", choices=["aab", "apk"], default="aab", dest="artifact_type"
    )
    p_upload.add_argument(
        "--rollout", type=float, default=1.0,
        help="Fraction of users to roll out to (0.0-1.0). 1.0 = full/completed release.",
    )
    p_upload.add_argument(
        "--release-notes", dest="release_notes", default=None,
        help="Directory of <language-code>.txt files, e.g. en-US.txt.",
    )
    p_upload.set_defaults(func=cmd_upload)

    p_rollout = subparsers.add_parser(
        "set-rollout", help="Update the rollout percentage of an in-progress release, no new upload."
    )
    add_common(p_rollout)
    p_rollout.add_argument("--track", required=True)
    p_rollout.add_argument("--rollout", type=float, required=True)
    p_rollout.set_defaults(func=cmd_set_rollout)

    p_promote = subparsers.add_parser(
        "promote", help="Copy the current release of one track onto another track."
    )
    add_common(p_promote)
    p_promote.add_argument("--from-track", required=True, dest="from_track")
    p_promote.add_argument("--to-track", required=True, dest="to_track")
    p_promote.set_defaults(func=cmd_promote)

    p_halt = subparsers.add_parser("halt", help="Halt an in-progress staged rollout.")
    add_common(p_halt)
    p_halt.add_argument("--track", required=True)
    p_halt.set_defaults(func=cmd_halt)

    p_listing = subparsers.add_parser("update-listing", help="Update store listing text.")
    add_common(p_listing)
    p_listing.add_argument("--language", default="en-US")
    p_listing.add_argument("--title", default=None)
    p_listing.add_argument("--short-description", default=None, dest="short_description")
    p_listing.add_argument("--full-description", default=None, dest="full_description")
    p_listing.add_argument("--video-url", default=None, dest="video_url")
    p_listing.set_defaults(func=cmd_update_listing)

    p_images = subparsers.add_parser(
        "upload-images", help="Upload store graphics (icon, screenshots, feature graphic, ...)."
    )
    add_common(p_images)
    p_images.add_argument("--language", default="en-US")
    p_images.add_argument("--image-type", required=True, choices=IMAGE_TYPES, dest="image_type")
    p_images.add_argument("--dir", required=True, help="Directory of image files to upload.")
    p_images.set_defaults(func=cmd_upload_images)

    p_status = subparsers.add_parser(
        "status", help="Print current release/track status. Read-only, never commits."
    )
    add_common(p_status)
    p_status.add_argument("--track", default=None, help="Limit to one track; default all tracks.")
    p_status.set_defaults(func=cmd_status)

    return parser


def main(argv: list[str] | None = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)

    if not os.path.isfile(args.credentials):
        _fail(f"credentials file not found: {args.credentials}")

    service = get_service(args.credentials)
    try:
        args.func(service, args)
    except HttpError as e:
        _fail(f"Android Publisher API error: {e}")


if __name__ == "__main__":
    main()
