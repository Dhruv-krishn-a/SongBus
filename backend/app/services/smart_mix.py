import json
import hashlib
import re
from collections import Counter, defaultdict
from typing import Any, Dict, List, Set, Tuple

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

try:
    from sklearn.cluster import HDBSCAN
except ImportError:
    from hdbscan import HDBSCAN

from app.models.schema import Track
from app.services.analysis import _aicredits_chat_completion


# ---------------------------------------------------------------------------
# Lazy-loaded embedding model singleton
# ---------------------------------------------------------------------------

_EMBEDDING_MODEL = None


def _get_embedding_model():
    """
    Lazy-load the SentenceTransformer model on first use instead of at import time.
    Prevents blocking server startup and avoids re-downloading on cold caches.
    """
    global _EMBEDDING_MODEL
    if _EMBEDDING_MODEL is None:
        from sentence_transformers import SentenceTransformer
        _EMBEDDING_MODEL = SentenceTransformer("all-MiniLM-L6-v2")
    return _EMBEDDING_MODEL


# ---------------------------------------------------------------------------
# In-memory embedding cache (survives across button clicks within same session)
# ---------------------------------------------------------------------------

_EMBEDDING_CACHE: Dict[int, Tuple[str, np.ndarray]] = {}


def _get_cached_embeddings(
    track_ids: List[int],
    documents: List[str],
) -> np.ndarray:
    """
    Only re-encode tracks whose semantic document has changed since the last call.
    Uses an in-memory dict keyed by track_id -> (doc_hash, embedding_vector).
    """
    model = _get_embedding_model()
    embeddings = [None] * len(track_ids)
    indices_to_encode: List[int] = []
    docs_to_encode: List[str] = []

    for i, (tid, doc) in enumerate(zip(track_ids, documents)):
        doc_hash = hashlib.md5(doc.encode("utf-8")).hexdigest()
        cached = _EMBEDDING_CACHE.get(tid)
        if cached and cached[0] == doc_hash:
            embeddings[i] = cached[1]
        else:
            indices_to_encode.append(i)
            docs_to_encode.append(doc)

    if docs_to_encode:
        new_vectors = model.encode(docs_to_encode, show_progress_bar=False)
        for pos, vec in zip(indices_to_encode, new_vectors):
            embeddings[pos] = vec
            tid = track_ids[pos]
            doc_hash = hashlib.md5(documents[pos].encode("utf-8")).hexdigest()
            _EMBEDDING_CACHE[tid] = (doc_hash, vec)

    return np.array(embeddings)


# ---------------------------------------------------------------------------
# SmartMixEngine
# ---------------------------------------------------------------------------


class SmartMixEngine:
    """
    Production-grade hybrid playlist engine.

    Pipeline:
        1. Build semantic sentences from track metadata
        2. Encode via SentenceTransformers (cached)
        3. Cluster with HDBSCAN (natural clusters + noise detection)
        4. Build rich cluster summaries (emotional signatures, genre distribution,
           confidence with artist-diversity penalty)
        5. Send ONLY summaries to Gemini for poetic naming / merging
        6. Map cluster IDs back to real track IDs locally
        7. Collect noise + unused clusters into chunked "Deep Cuts" playlists

    Design decisions:
        - Artist is included at minimal weight so same-title songs remain
          distinguishable, but emotional tags dominate clustering.
        - Tracks with zero classification data are filtered out of the
          embedding pipeline and placed directly into Deep Cuts.
        - Gemini failure triggers a deterministic local fallback so the user
          always gets playlists.
    """

    MIN_TRACKS = 10

    # ------------------------------------------------------------------
    # Text helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _safe_text(value: Any) -> str:
        return "" if value is None else str(value).strip()

    @staticmethod
    def _split_tags(value: Any) -> List[str]:
        if value is None:
            return []
        if isinstance(value, (list, tuple, set)):
            raw_items = [str(v) for v in value]
        else:
            raw_items = [p.strip() for p in re.split(r"[,\|;/]", str(value))]
        return [item.strip() for item in raw_items if item.strip()]

    # ------------------------------------------------------------------
    # Semantic document builder
    # ------------------------------------------------------------------

    @staticmethod
    def _has_classification(track: Track) -> bool:
        """Return True if the track has at least one non-empty tag dimension."""
        for field in ("genre", "mood", "themes", "emotions", "contexts"):
            val = getattr(track, field, None)
            if val and str(val).strip():
                return True
        return False

    @staticmethod
    def _build_semantic_document(track: Track) -> str:
        """
        Build a natural-language sentence for the SentenceTransformer.

        SentenceTransformers are trained on full sentences, so embedding
        "A melancholic desi-hip-hop song about yearning evoking sadness.
         Perfect for late-night drives."
        produces dramatically better vectors than the raw tag bag
        "yearning lost-love nostalgia".

        Artist is appended as a lightweight token at the end so that
        same-title tracks (e.g. "Aadat" by Atif Aslam vs Ninja) remain
        distinguishable, but the emotional tags dominate the vector.
        """
        title = SmartMixEngine._safe_text(track.title)
        artist = SmartMixEngine._safe_text(track.artist)

        genres = SmartMixEngine._split_tags(getattr(track, "genre", None))
        moods = SmartMixEngine._split_tags(getattr(track, "mood", None))
        themes = SmartMixEngine._split_tags(getattr(track, "themes", None))
        emotions = SmartMixEngine._split_tags(getattr(track, "emotions", None))
        contexts = SmartMixEngine._split_tags(getattr(track, "contexts", None))

        parts: List[str] = []

        # Core sentence — emotion-first
        m_str = ", ".join(moods) if moods else "unknown"
        g_str = ", ".join(genres) if genres else "song"
        parts.append(f"A {m_str} {g_str} song")

        if themes:
            parts.append(f"about {', '.join(themes)}")
        if emotions:
            parts.append(f"evoking {', '.join(emotions)}")
        if contexts:
            parts.append(f"perfect for {', '.join(contexts)}")

        sentence = " ".join(parts) + "."

        # Title (useful for disambiguation, low weight by position)
        if title:
            sentence += f" Title: {title}."

        # Artist as a single hyphenated token so it survives as one unit
        if artist:
            artist_token = artist.lower().replace(" ", "-")
            sentence += f" By {artist_token}."

        return sentence

    # ------------------------------------------------------------------
    # Clustering
    # ------------------------------------------------------------------

    @staticmethod
    def _cluster_tracks(embeddings: np.ndarray) -> np.ndarray:
        """
        K-Means: Partitioning-based clustering.
        Determines the number of clusters dynamically based on library size
        and uses K-Means to partition all tracks into clean, balanced groups.
        """
        n = embeddings.shape[0]
        # Target cluster size ~80 tracks (balanced between 25 and 150)
        k = int(np.clip(n // 80, 4, 12))
        
        # Unit-normalize embeddings for cosine similarity equivalence in KMeans
        norms = np.linalg.norm(embeddings, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        norm_embeddings = embeddings / norms
        
        from sklearn.cluster import KMeans
        model = KMeans(n_clusters=k, random_state=42, n_init="auto")
        labels = model.fit_predict(norm_embeddings)
        return labels

    # ------------------------------------------------------------------
    # Cluster analysis helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _emotional_signature(tracks: List[Track], indices: List[int]) -> str:
        """Percentage-based emotional signature for the cluster."""
        total = len(indices)
        if total == 0:
            return ""

        tag_counts: Counter = Counter()
        for idx in indices:
            tr = tracks[idx]
            raw_tags: List[str] = []
            raw_tags.extend(SmartMixEngine._split_tags(getattr(tr, "themes", None)))
            raw_tags.extend(SmartMixEngine._split_tags(getattr(tr, "emotions", None)))
            raw_tags.extend(SmartMixEngine._split_tags(getattr(tr, "mood", None)))
            for tag in set(s.lower().replace("_", " ") for s in raw_tags if s):
                tag_counts[tag] += 1

        sig_lines: List[str] = []
        for tag, count in tag_counts.most_common(6):
            pct = int((count / total) * 100)
            if pct > 15:
                sig_lines.append(f"{pct}% {tag.title()}")

        return ", ".join(sig_lines) if sig_lines else "Mixed Emotions"

    @staticmethod
    def _genre_distribution(tracks: List[Track], indices: List[int]) -> str:
        """Top genres inside the cluster for Gemini context."""
        genre_counts: Counter = Counter()
        for idx in indices:
            for g in SmartMixEngine._split_tags(getattr(tracks[idx], "genre", None)):
                genre_counts[g.lower().replace("_", " ")] += 1

        top = [f"{tag.title()}" for tag, _ in genre_counts.most_common(4) if tag]
        return ", ".join(top) if top else "Unknown"

    @staticmethod
    def _cluster_confidence(
        embeddings: np.ndarray,
        indices: List[int],
        tracks: List[Track],
    ) -> float:
        """
        Cluster purity = avg cosine similarity to centroid.
        Penalised if a single artist dominates (>60% of the cluster).
        """
        if len(indices) < 2:
            return 1.0

        cluster_vecs = embeddings[indices]
        centroid = cluster_vecs.mean(axis=0).reshape(1, -1)
        sims = cosine_similarity(cluster_vecs, centroid).ravel()
        base_confidence = float(np.mean(sims))

        # Artist diversity penalty
        artist_counts: Counter = Counter()
        for idx in indices:
            a = SmartMixEngine._safe_text(tracks[idx].artist)
            if a:
                artist_counts[a.lower()] += 1

        if artist_counts:
            top_ratio = artist_counts.most_common(1)[0][1] / len(indices)
            if top_ratio > 0.70:
                base_confidence -= 0.30
            elif top_ratio > 0.60:
                base_confidence -= 0.15

        return round(max(0.05, base_confidence), 2)

    @staticmethod
    def _representative_tracks(
        embeddings: np.ndarray,
        indices: List[int],
        tracks: List[Track],
        top_n: int = 10,
    ) -> List[str]:
        """Top-N tracks closest to the cluster centroid."""
        if not indices:
            return []

        cluster_vecs = embeddings[indices]
        centroid = cluster_vecs.mean(axis=0).reshape(1, -1)
        sims = cosine_similarity(cluster_vecs, centroid).ravel()
        ranked = np.argsort(sims)[::-1][:top_n]

        samples: List[str] = []
        for pos in ranked:
            t = tracks[indices[pos]]
            samples.append(f"{t.title} by {t.artist}")
        return samples

    # ------------------------------------------------------------------
    # Cluster summary builder
    # ------------------------------------------------------------------

    @staticmethod
    def _build_cluster_summaries(
        tracks: List[Track],
        embeddings: np.ndarray,
        labels: np.ndarray,
    ) -> Dict[int, Dict[str, Any]]:
        clusters: Dict[int, List[int]] = defaultdict(list)
        for idx, label in enumerate(labels):
            if label != -1:
                clusters[int(label)].append(idx)

        summaries: Dict[int, Dict[str, Any]] = {}
        for cluster_id, indices in clusters.items():
            summaries[cluster_id] = {
                "cluster_id": cluster_id,
                "size": len(indices),
                "signature": SmartMixEngine._emotional_signature(tracks, indices),
                "genres": SmartMixEngine._genre_distribution(tracks, indices),
                "samples": SmartMixEngine._representative_tracks(embeddings, indices, tracks, top_n=10),
                "confidence": SmartMixEngine._cluster_confidence(embeddings, indices, tracks),
                "track_indices": indices,
            }

        return summaries

    # ------------------------------------------------------------------
    # Gemini prompt
    # ------------------------------------------------------------------

    @staticmethod
    def _build_prompt(
        cluster_summaries: Dict[int, Dict[str, Any]],
        total_tracks: int,
    ) -> str:
        blocks: List[str] = []
        for cid in sorted(cluster_summaries.keys()):
            c = cluster_summaries[cid]
            blocks.append(
                "\n".join([
                    f"Cluster ID: {cid}",
                    f"Track Count: {c['size']}",
                    f"Confidence (Purity): {c['confidence']}",
                    f"Dominant Genres: {c['genres']}",
                    f"Emotional Signature: {c['signature']}",
                    f"Representative Tracks: {', '.join(c['samples'])}",
                ])
            )

        clusters_text = "\n\n".join(blocks)

        return f"""\
You are an elite music curator.
Library Size: {total_tracks} Tracks

I have analyzed the user's library locally and grouped it into mathematically \
similar clusters using Dense Semantic Embeddings and HDBSCAN.
Your task is ONLY to name, describe, and merge clusters into playlists.

Rules:
- Create exactly 4 to 7 playlists.
- Use poetic, specific, emotionally evocative names. Never generic.
- Provide a single-sentence description for each playlist.
- You may merge clusters that share the same emotional vibe.
- Do NOT split a cluster across multiple playlists.
- Assign every cluster to at most one playlist.
- Hard constraint: each playlist should aim for 25-150 songs (sum the Track Counts).
- Never use double quotes inside playlist names or descriptions. If you need to quote something, use single quotes (e.g., 'Vibe') instead.
- Do not use unescaped quotes inside string values. Output strictly valid JSON.

Clusters:

{clusters_text}

Return exactly this JSON shape:
{{
  "playlists": [
    {{
      "name": "Monsoon Melancholy",
      "description": "Rain-soaked longing and memories that refuse to fade.",
      "cluster_ids": [4, 7]
    }}
  ]
}}
Do not use unescaped quotes inside string values. Output strictly valid JSON."""

    # ------------------------------------------------------------------
    # Local fallback when Gemini fails
    # ------------------------------------------------------------------

    @staticmethod
    def _fallback_playlist_name(summary: Dict[str, Any]) -> str:
        """Deterministic local name from the cluster's top tags."""
        sig = summary.get("signature", "")
        genres = summary.get("genres", "")

        # Pick the strongest emotion
        emotion = "Vibes"
        if sig and sig != "Mixed Emotions":
            first = sig.split(",")[0].strip()
            # Remove the percentage prefix
            parts = first.split("% ")
            emotion = parts[1] if len(parts) == 2 else parts[0]

        # Pick the strongest genre
        genre = "Mix"
        if genres and genres != "Unknown":
            genre = genres.split(",")[0].strip()

        return f"{emotion} {genre}" if emotion != genre else emotion

    @staticmethod
    def _generate_fallback_playlists(
        cluster_summaries: Dict[int, Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Create playlists purely from local cluster data when Gemini is unavailable."""
        playlists: List[Dict[str, Any]] = []
        sorted_clusters = sorted(
            cluster_summaries.values(), key=lambda c: c["size"], reverse=True
        )
        for c in sorted_clusters[: min(7, len(sorted_clusters))]:
            playlists.append({
                "name": SmartMixEngine._fallback_playlist_name(c),
                "description": f"Auto-generated from cluster with {c['size']} tracks.",
                "cluster_ids": [c["cluster_id"]],
            })
        return playlists

    # ------------------------------------------------------------------
    # AI result parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_ai_result(result: Any) -> Dict[str, Any]:
        if isinstance(result, dict):
            return result
        if isinstance(result, str):
            cleaned = re.sub(r"```(?:json)?", "", result, flags=re.IGNORECASE).strip()
            return json.loads(cleaned)
        raise ValueError("AI response was not valid JSON")

    # ------------------------------------------------------------------
    # Main entry point
    # ------------------------------------------------------------------

    @staticmethod
    def generate_ai_playlists_direct(tracks: List[Track]) -> dict:
        """
        Full pipeline: semantic docs → embeddings → HDBSCAN → Gemini naming → playlists.
        """
        if not tracks:
            return {"error": "No tracks provided"}

        valid_tracks = [t for t in tracks if getattr(t, "id", None) is not None]
        total_tracks = len(valid_tracks)
        if total_tracks < SmartMixEngine.MIN_TRACKS:
            return {"error": "Not enough tracks to form meaningful playlists."}

        # Separate classified vs unclassified tracks
        classified: List[Tuple[int, Track]] = []  # (original_index, track)
        unclassified_ids: List[int] = []

        for i, t in enumerate(valid_tracks):
            if SmartMixEngine._has_classification(t):
                classified.append((i, t))
            else:
                unclassified_ids.append(int(t.id))

        if len(classified) < SmartMixEngine.MIN_TRACKS:
            return {
                "error": "Not enough classified tracks. Run AI Classification first."
            }

        classified_tracks = [t for _, t in classified]
        track_ids = [int(t.id) for t in classified_tracks]

        # 1. Build semantic sentences
        documents = [
            SmartMixEngine._build_semantic_document(t) for t in classified_tracks
        ]

        # 2. Encode with cached embeddings
        try:
            embeddings = _get_cached_embeddings(track_ids, documents)
        except Exception as e:
            return {"error": f"Embedding generation failed: {e}"}

        # 3. HDBSCAN clustering
        try:
            labels = SmartMixEngine._cluster_tracks(embeddings)
        except Exception as e:
            return {"error": f"Clustering failed: {e}"}

        cluster_summaries = SmartMixEngine._build_cluster_summaries(
            classified_tracks, embeddings, labels
        )

        if not cluster_summaries:
            return {
                "error": "HDBSCAN found no valid clusters. Your library may need more diversity."
            }

        # 4. Ask Gemini to name/merge — with local fallback
        prompt = SmartMixEngine._build_prompt(cluster_summaries, total_tracks)
        try:
            parsed = _aicredits_chat_completion(
                model="google/gemini-2.5-flash",
                messages=[{"role": "user", "content": prompt}],
                temperature=0.6,
                max_tokens=2048,
                response_format={"type": "json_object"},
            )
            parsed_json = SmartMixEngine._parse_ai_result(parsed)
            ai_playlists = parsed_json.get("playlists", [])
            if not isinstance(ai_playlists, list) or not ai_playlists:
                raise ValueError("Empty playlists array")
        except Exception as e:
            print(f"SmartMix error during AI naming: {e}")
            import traceback
            traceback.print_exc()
            # Fallback: deterministic local naming
            ai_playlists = SmartMixEngine._generate_fallback_playlists(cluster_summaries)

        # 5. Map cluster IDs → real track IDs
        cluster_to_track_ids: Dict[int, List[int]] = {}
        for cid, summary in cluster_summaries.items():
            cluster_to_track_ids[cid] = [
                int(classified_tracks[idx].id) for idx in summary["track_indices"]
            ]

        used_clusters: Set[int] = set()
        seen_track_ids: Set[int] = set()
        final_playlists: List[Dict[str, Any]] = []
        playlist_confidences: List[float] = []

        for p in ai_playlists:
            if not isinstance(p, dict):
                continue
            name = str(p.get("name", "")).strip()
            if not name:
                continue

            raw_cluster_ids = p.get("cluster_ids", [])
            if not isinstance(raw_cluster_ids, list):
                raw_cluster_ids = []

            merged_track_ids: List[int] = []
            confidence_values: List[float] = []

            for raw_cid in raw_cluster_ids:
                try:
                    cid = int(raw_cid)
                except (ValueError, TypeError):
                    continue
                if cid not in cluster_summaries or cid in used_clusters:
                    continue

                used_clusters.add(cid)
                confidence_values.append(cluster_summaries[cid]["confidence"])

                for tid in cluster_to_track_ids.get(cid, []):
                    if tid not in seen_track_ids:
                        seen_track_ids.add(tid)
                        merged_track_ids.append(tid)

            if merged_track_ids:
                avg_conf = (
                    round(sum(confidence_values) / len(confidence_values), 2)
                    if confidence_values
                    else 0.0
                )
                final_playlists.append({
                    "name": name,
                    "description": str(p.get("description", "")).strip(),
                    "track_ids": merged_track_ids,
                    "confidence": avg_conf,
                })
                playlist_confidences.append(avg_conf)

        # 6. Collect noise + unused clusters + unclassified tracks into Deep Cuts
        deep_cut_ids: List[int] = []

        # HDBSCAN noise (label -1)
        for idx, label in enumerate(labels):
            if label == -1:
                tid = int(classified_tracks[idx].id)
                if tid not in seen_track_ids:
                    seen_track_ids.add(tid)
                    deep_cut_ids.append(tid)

        # Unused clusters
        for cid in cluster_summaries:
            if cid not in used_clusters:
                for tid in cluster_to_track_ids.get(cid, []):
                    if tid not in seen_track_ids:
                        seen_track_ids.add(tid)
                        deep_cut_ids.append(tid)

        # Unclassified tracks (never went through embeddings)
        for tid in unclassified_ids:
            if tid not in seen_track_ids:
                seen_track_ids.add(tid)
                deep_cut_ids.append(tid)

        # Split Deep Cuts into chunks of 150
        if deep_cut_ids:
            chunk_size = 150
            total_chunks = (len(deep_cut_ids) + chunk_size - 1) // chunk_size
            for i in range(0, len(deep_cut_ids), chunk_size):
                chunk = deep_cut_ids[i : i + chunk_size]
                suffix = f" {i // chunk_size + 1}" if total_chunks > 1 else ""
                final_playlists.append({
                    "name": f"Deep Cuts & Loose Ends{suffix}",
                    "description": "Tracks from smaller clusters, outliers, or uncategorized songs.",
                    "track_ids": chunk,
                    "confidence": 0.0,
                })

        # 7. Sort by confidence (strongest playlists first), filter tiny ones
        final_playlists.sort(key=lambda p: p.get("confidence", 0.0), reverse=True)
        cleaned = [p for p in final_playlists if len(p.get("track_ids", [])) >= 3]
        if not cleaned and final_playlists:
            cleaned = final_playlists

        return {
            "playlists": cleaned,
            "cluster_count": len(cluster_summaries),
            "track_count": total_tracks,
            "classified_count": len(classified),
            "unclassified_count": len(unclassified_ids),
        }