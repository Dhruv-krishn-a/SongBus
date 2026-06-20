from __future__ import annotations

import re
import unicodedata
from collections import defaultdict
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Tuple

from sqlalchemy.orm import Session

from app.models.schema import PlayHistory, PlaylistTrack, Track


class DataCleaner:
    """
    Industry-grade library cleaner.

    Goals:
    - Remove obvious junk/non-song entries.
    - Normalize noisy titles/artists.
    - Deduplicate safely without merging legitimate versions.
    - Preserve the best canonical track.
    - Reassign playlist/history references safely.
    """

    DURATION_TOLERANCE_SECONDS = 8
    TITLE_SIMILARITY_THRESHOLD = 0.97
    ARTIST_SIMILARITY_THRESHOLD = 0.96

    # Non-song content that should be deleted, not merged.
    JUNK_PATTERNS = [
        r"\breaction\b",
        r"\breacts?\b",
        r"\binterview\b",
        r"\bvlog\b",
        r"\bpodcast\b",
        r"\btrailer\b",
        r"\bteaser\b",
        r"\bbehind the scenes\b",
        r"\bmaking of\b",
        r"\bdocumentary\b",
        r"\bshort clip\b",
        r"\bfull album\b",
        r"\bfull show\b",
        r"\blive stream\b",
        r"\bstream highlights?\b",
        r"\bmashup\b",
        r"\bmegamix\b",
        r"\bfan edit\b",
        r"\btiktok edit\b",
        r"\bamv\b",
        r"\bdrum cover\b",
        r"\bdrum remix\b",
        r"\btop\s*\d+\b",
        r"\bmini mix\b",
        r"\bthis song will\b",
        r"\bcompilation\b",
        r"\bbass drops?\b",
        r"\bsubscribers?\b",
    ]

    # Noise that should be removed from titles during normalization.
    NOISE_PATTERNS = [
        r"\(official\s*audio\)", r"\[official\s*audio\]",
        r"\(official\s*video\)", r"\[official\s*video\]",
        r"\(lyrics\)", r"\[lyrics\]",
        r"\(audio\)", r"\[audio\]",
        r"\(video\)", r"\[video\]",
        r"\(hd\)", r"\[hd\]",
        r"\(hq\)", r"\[hq\]",
        r"\(4k\)", r"\[4k\]",
        r"\(full\s*song\)", r"\[full\s*song\]",
        r"\(full\s*video\)", r"\[full\s*video\]",
        r"\(lyric\s*video\)", r"\[lyric\s*video\]",
        r"\(visualizer\)", r"\[visualizer\]",
        r"\(topic\)", r"\[topic\]",
        r"\s*-\s*topic\b",
        r"\s*\|\s*topic\b",
        r"\s*\|.*$",
        r"\s*vevo\b",
    ]

    # Legitimate version markers that should usually remain separate tracks.
    LEGIT_VERSION_MARKERS = {
        "live": [r"\blive\b", r"\blive at\b", r"\bconcert\b", r"\bperformance\b"],
        "acoustic": [r"\bacoustic\b", r"\bunplugged\b", r"\bpiano version\b"],
        "remix": [r"\bremix\b", r"\brework\b", r"\bedit\b", r"\bremastered\b"],
        "instrumental": [r"\binstrumental\b", r"\bkaraoke\b", r"\borchestral\b"],
        "cover": [r"\bcover\b"],
    }

    # Versions that should be treated as junk, not kept.
    NONCANONICAL_VARIANTS = [
        r"\bslowed\b",
        r"\breverb\b",
        r"\bslowed\s*\+\s*reverb\b",
        r"\bnightcore\b",
        r"\bbass boosted\b",
        r"\bsped up\b",
        r"\b8d audio\b",
    ]

    SOURCE_PRIORITY = {
        "spotify": 50,
        "youtube": 40,
        "ytmusic": 40,
        "apple_music": 35,
        "soundcloud": 25,
        "history": 5,
        "import": 10,
    }

    # ---------------------------
    # Basic string normalization
    # ---------------------------

    @staticmethod
    def _safe_text(value: Any) -> str:
        return "" if value is None else str(value)

    @staticmethod
    def normalize_string(s: str) -> str:
        """
        Lowercase, remove accents, strip noisy suffixes, and normalize spaces.
        Good for matching.
        """
        if not s:
            return ""

        text = unicodedata.normalize("NFKD", str(s))
        text = text.encode("ascii", "ignore").decode("ascii", errors="ignore")
        text = text.lower().strip()

        for pattern in DataCleaner.NOISE_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # Replace punctuation with spaces, but keep letters/numbers.
        text = re.sub(r"[\(\)\[\]\{\}\.,!?:;\"'`~@#$%^&*_+=<>/\\-]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_artist_signature(artist: str) -> str:
        """
        Build a stable artist key:
        - remove accents
        - remove featuring credits
        - normalize punctuation
        """
        text = DataCleaner.normalize_string(artist)

        # Keep only primary artist portion.
        text = re.split(r"\b(feat\.?|ft\.?|featuring|with)\b", text, maxsplit=1)[0].strip()
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _normalize_title_core(title: str) -> str:
        """
        Normalize title for matching, but keep version markers like 'live' / 'acoustic'
        so legitimate variants don't collapse into the original.
        """
        text = DataCleaner._safe_text(title)
        text = unicodedata.normalize("NFKD", text)
        text = text.encode("ascii", "ignore").decode("ascii", errors="ignore")
        text = text.lower().strip()

        # Remove only obvious noise, not live/acoustic/remix.
        for pattern in DataCleaner.NOISE_PATTERNS:
            text = re.sub(pattern, "", text, flags=re.IGNORECASE)

        # Remove feature credits from title for matching.
        text = re.split(r"\b(feat\.?|ft\.?|featuring)\b", text, maxsplit=1)[0].strip()

        text = re.sub(r"[\(\)\[\]\{\}\.,!?:;\"'`~@#$%^&*_+=<>/\\|]", " ", text)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    @staticmethod
    def _title_similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    @staticmethod
    def _artist_similarity(a: str, b: str) -> float:
        return SequenceMatcher(None, a, b).ratio()

    # ---------------------------
    # Junk / variant detection
    # ---------------------------

    @staticmethod
    def is_junk_track(title: str, artist: str | None = None) -> bool:
        """
        Return True for non-song content that should be deleted.
        """
        text = f"{DataCleaner._safe_text(title)} {DataCleaner._safe_text(artist)}".lower()

        # Strong non-song signals.
        for pattern in DataCleaner.JUNK_PATTERNS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True

        # Slowed/reverb/nightcore/bass boosted are not canonical tracks for this cleaner.
        for pattern in DataCleaner.NONCANONICAL_VARIANTS:
            if re.search(pattern, text, flags=re.IGNORECASE):
                return True

        return False

    @staticmethod
    def get_track_version_type(title: str, artist: str | None = None) -> str:
        """
        Classify a track as:
        - original
        - live
        - acoustic
        - remix
        - instrumental
        - cover
        - junk
        """
        text = f"{DataCleaner._safe_text(title)} {DataCleaner._safe_text(artist)}".lower()

        if DataCleaner.is_junk_track(title, artist):
            return "junk"

        for version_type, patterns in DataCleaner.LEGIT_VERSION_MARKERS.items():
            for pattern in patterns:
                if re.search(pattern, text, flags=re.IGNORECASE):
                    return version_type

        return "original"

    @staticmethod
    def _should_keep_separate_versions(a_version: str, b_version: str) -> bool:
        """
        Keep legitimate versions separate if they are not the same kind.
        """
        if a_version == "junk" or b_version == "junk":
            return True

        # Original/unknown can be merged with mergeable noise only.
        protected = {"live", "acoustic", "remix", "instrumental", "cover"}
        if a_version in protected or b_version in protected:
            return a_version != b_version

        return False

    # ---------------------------
    # Duplicate detection
    # ---------------------------

    @staticmethod
    def _duration_matches(a: Track, b: Track) -> bool:
        da = getattr(a, "duration_ms", None)
        db = getattr(b, "duration_ms", None)
        if not da or not db:
            return True

        diff_ms = abs(int(da) - int(db))
        return diff_ms <= DataCleaner.DURATION_TOLERANCE_SECONDS * 1000

    @staticmethod
    def _track_match(a: Track, b: Track) -> bool:
        """
        Conservative duplicate matcher:
        - same artist signature
        - strong title similarity / match
        - duration close if available
        - do not merge different legitimate versions
        """
        title_a_raw = DataCleaner._safe_text(a.title)
        title_b_raw = DataCleaner._safe_text(b.title)
        artist_a_raw = DataCleaner._safe_text(a.artist)
        artist_b_raw = DataCleaner._safe_text(b.artist)

        version_a = DataCleaner.get_track_version_type(title_a_raw, artist_a_raw)
        version_b = DataCleaner.get_track_version_type(title_b_raw, artist_b_raw)

        if DataCleaner._should_keep_separate_versions(version_a, version_b):
            return False

        artist_a = DataCleaner._normalize_artist_signature(artist_a_raw)
        artist_b = DataCleaner._normalize_artist_signature(artist_b_raw)

        if not artist_a or not artist_b:
            return False

        if artist_a != artist_b:
            # Allow only very close artist matches, still requiring title match and duration match.
            if DataCleaner._artist_similarity(artist_a, artist_b) < DataCleaner.ARTIST_SIMILARITY_THRESHOLD:
                return False

        title_a = DataCleaner._normalize_title_core(title_a_raw)
        title_b = DataCleaner._normalize_title_core(title_b_raw)

        if not title_a or not title_b:
            return False

        if title_a == title_b:
            return DataCleaner._duration_matches(a, b)

        similarity = DataCleaner._title_similarity(title_a, title_b)
        if similarity < DataCleaner.TITLE_SIMILARITY_THRESHOLD:
            return False

        return DataCleaner._duration_matches(a, b)

    @staticmethod
    def _group_tracks(tracks: List[Track]) -> List[List[Track]]:
        """
        Create conservative duplicate groups.
        """
        buckets: Dict[Tuple[str, str, str], List[Track]] = defaultdict(list)

        for track in tracks:
            if DataCleaner.is_junk_track(track.title, track.artist):
                continue

            artist_key = DataCleaner._normalize_artist_signature(track.artist)
            title_key = DataCleaner._normalize_title_core(track.title)
            version = DataCleaner.get_track_version_type(track.title, track.artist)

            # Exact-ish bucket first.
            buckets[(artist_key, title_key, version)].append(track)

        groups: List[List[Track]] = []

        # First, flush exact buckets.
        for _, bucket in buckets.items():
            if len(bucket) == 1:
                groups.append(bucket)
                continue

            # Inside each bucket, split by actual conservative matching.
            local_groups: List[List[Track]] = []
            for tr in bucket:
                placed = False
                for g in local_groups:
                    if DataCleaner._track_match(g[0], tr):
                        g.append(tr)
                        placed = True
                        break
                if not placed:
                    local_groups.append([tr])

            groups.extend(local_groups)

        # The exact buckets are already robust enough because the normalization
        # strips punctuation, accents, and features.
        # We skip the O(N^2) second pass to prevent 8-minute freezes on large libraries.
        return groups

    # ---------------------------
    # Canonical scoring / merging
    # ---------------------------

    @staticmethod
    def _score_track(track: Track) -> int:
        score = 0

        if getattr(track, "lyrics", None) and not getattr(track, "lyrics_not_found", False):
            score += 300

        if getattr(track, "spotify_uri", None):
            score += 120

        if getattr(track, "external_id", None):
            score += 80

        if getattr(track, "matched_youtube_id", None):
            score += 60

        if getattr(track, "genre", None):
            score += 30

        if getattr(track, "mood", None):
            score += 30

        if getattr(track, "album", None):
            score += 15

        if getattr(track, "release_year", None):
            score += 10

        if getattr(track, "popularity", None) is not None:
            try:
                score += min(20, int(track.popularity) // 5)
            except Exception:
                pass

        if getattr(track, "duration_ms", None):
            score += 5

        source = DataCleaner._safe_text(getattr(track, "source", "")).lower()
        score += DataCleaner.SOURCE_PRIORITY.get(source, 0)

        # Prefer tracks that look like official sources over generic imports.
        version = DataCleaner.get_track_version_type(track.title, track.artist)
        if version == "original":
            score += 25
        elif version in {"live", "acoustic", "remix", "instrumental", "cover"}:
            score -= 10

        return score

    @staticmethod
    def _merge_first_non_empty(canonical: Track, duplicate: Track, field: str) -> bool:
        """
        Fill missing scalar fields only.
        """
        c_val = getattr(canonical, field, None)
        d_val = getattr(duplicate, field, None)

        if (c_val is None or c_val == "" or c_val == [] or c_val == {}) and d_val not in (None, "", [], {}):
            setattr(canonical, field, d_val)
            return True
        return False

    @staticmethod
    def _split_values(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            return [str(v).strip() for v in value if str(v).strip()]
        if isinstance(value, str):
            parts = [p.strip() for p in re.split(r"[,\|;/]", value) if p.strip()]
            return parts
        return [str(value).strip()] if str(value).strip() else []

    @staticmethod
    def _merge_multivalue_field(canonical: Track, duplicate: Track, field: str) -> bool:
        """
        Merge comma-separated or list-like metadata fields.
        """
        c_val = getattr(canonical, field, None)
        d_val = getattr(duplicate, field, None)

        c_items = DataCleaner._split_values(c_val)
        d_items = DataCleaner._split_values(d_val)

        if not c_items and d_items:
            if isinstance(c_val, (list, tuple, set)):
                setattr(canonical, field, list(dict.fromkeys(d_items)))
            else:
                setattr(canonical, field, ", ".join(dict.fromkeys(d_items)))
            return True

        if c_items and d_items:
            merged = list(dict.fromkeys(c_items + d_items))
            if isinstance(c_val, (list, tuple, set)):
                setattr(canonical, field, merged)
            else:
                setattr(canonical, field, ", ".join(merged))
            return True

        return False

    @staticmethod
    def _merge_track_data(canonical: Track, duplicate: Track) -> None:
        """
        Merge useful metadata from duplicate into canonical without overwriting
        better data.
        """
        scalar_fields = [
            "lyrics",
            "lyrics_not_found",
            "spotify_uri",
            "external_id",
            "matched_youtube_id",
            "album",
            "genre",
            "mood",
            "source",
            "thumbnail_url",
            "release_year",
            "popularity",
            "explicit",
            "bpm",
            "energy",
            "danceability",
            "valence",
            "ai_not_found",
            "last_enriched_at",
        ]

        # First, merge high-value scalar fields if canonical is missing them.
        for field in scalar_fields:
            DataCleaner._merge_first_non_empty(canonical, duplicate, field)

        # Merge semantic tag fields if they exist in schema.
        for field in ["themes", "emotions", "contexts"]:
            if hasattr(canonical, field) or hasattr(duplicate, field):
                DataCleaner._merge_multivalue_field(canonical, duplicate, field)

    # ---------------------------
    # Association reassignment
    # ---------------------------

    @staticmethod
    def _reassign_playlist_tracks(db: Session, duplicate_id: int, canonical_id: int) -> None:
        pt_entries = (
            db.query(PlaylistTrack)
            .filter(PlaylistTrack.track_id == duplicate_id)
            .all()
        )

        for pt in pt_entries:
            exists = (
                db.query(PlaylistTrack)
                .filter(
                    PlaylistTrack.playlist_id == pt.playlist_id,
                    PlaylistTrack.track_id == canonical_id,
                )
                .first()
            )

            if exists:
                db.delete(pt)
            else:
                pt.track_id = canonical_id

    @staticmethod
    def _reassign_play_history(db: Session, duplicate_id: int, canonical_id: int) -> None:
        ph_entries = (
            db.query(PlayHistory)
            .filter(PlayHistory.track_id == duplicate_id)
            .all()
        )

        for ph in ph_entries:
            ph.track_id = canonical_id

    # ---------------------------
    # Main cleanup entry point
    # ---------------------------

    @staticmethod
    def clean_database(db: Session, user_id: int, dry_run: bool = False) -> dict:
        """
        Clean a user's library.

        Returns:
            {
                "merged_groups": int,
                "deleted_duplicates": int,
                "deleted_junk": int,
                "kept_tracks": int,
                "dry_run": bool
            }
        """
        tracks = (
            db.query(Track)
            .filter(Track.owner_id == user_id)
            .all()
        )

        deleted_junk_count = 0
        deleted_duplicates_count = 0
        merged_groups_count = 0
        kept_count = 0

        try:
            # 1) Delete junk tracks first.
            junk_track_ids = []
            for track in tracks:
                is_junk = DataCleaner.is_junk_track(track.title, track.artist)
                is_not_on_spotify = (track.spotify_uri is None and track.last_enriched_at is not None)
                
                if is_junk or is_not_on_spotify:
                    junk_track_ids.append(track.id)
            
            deleted_junk_count = len(junk_track_ids)
            
            if junk_track_ids and not dry_run:
                db.query(PlaylistTrack).filter(PlaylistTrack.track_id.in_(junk_track_ids)).delete(synchronize_session=False)
                db.query(PlayHistory).filter(PlayHistory.track_id.in_(junk_track_ids)).delete(synchronize_session=False)
                db.query(Track).filter(Track.id.in_(junk_track_ids)).delete(synchronize_session=False)

            # Refresh remaining list for grouping.
            valid_tracks = [
                t for t in tracks
                if t.id not in junk_track_ids
            ]

            # 2) Build duplicate groups conservatively.
            groups = DataCleaner._group_tracks(valid_tracks)

            # 3) Merge duplicates within each group.
            for group in groups:
                if not group:
                    continue

                if len(group) == 1:
                    kept_count += 1
                    continue

                merged_groups_count += 1

                # Select canonical track by score.
                group_sorted = sorted(group, key=DataCleaner._score_track, reverse=True)
                canonical = group_sorted[0]
                duplicates = group_sorted[1:]

                for dup in duplicates:
                    if dry_run:
                        deleted_duplicates_count += 1
                        continue

                    # Merge metadata from duplicate into canonical.
                    DataCleaner._merge_track_data(canonical, dup)

                    # Reassign references before deletion.
                    DataCleaner._reassign_playlist_tracks(db, dup.id, canonical.id)
                    DataCleaner._reassign_play_history(db, dup.id, canonical.id)

                    # Delete duplicate track.
                    db.delete(dup)
                    deleted_duplicates_count += 1

                kept_count += 1

            if not dry_run:
                db.commit()

            return {
                "merged_groups": merged_groups_count,
                "deleted_duplicates": deleted_duplicates_count,
                "deleted_junk": deleted_junk_count,
                "kept_tracks": kept_count,
                "dry_run": dry_run,
            }

        except Exception:
            db.rollback()
            raise

    @staticmethod
    def preview_groups(db: Session, user_id: int, limit: int = 200) -> dict:
        """
        Safe preview of what would be merged.
        """
        tracks = (
            db.query(Track)
            .filter(Track.owner_id == user_id)
            .all()
        )

        valid_tracks = [t for t in tracks if not DataCleaner.is_junk_track(t.title, t.artist)]
        groups = DataCleaner._group_tracks(valid_tracks)

        preview = []
        for group in groups:
            if len(group) < 2:
                continue

            sorted_group = sorted(group, key=DataCleaner._score_track, reverse=True)
            canonical = sorted_group[0]

            preview.append(
                {
                    "canonical": {
                        "id": canonical.id,
                        "title": canonical.title,
                        "artist": canonical.artist,
                    },
                    "duplicates": [
                        {
                            "id": t.id,
                            "title": t.title,
                            "artist": t.artist,
                        }
                        for t in sorted_group[1:]
                    ],
                }
            )

            if len(preview) >= limit:
                break

        return {
            "groups": preview,
            "total_groups": len(preview),
        }